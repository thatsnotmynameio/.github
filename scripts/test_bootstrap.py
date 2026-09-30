"""bootstrap.sh's tests against a fake gh: python3 -m unittest discover -s scripts -v

The fake gh logs each call (its arguments and stdin) and answers from
environment variables: FAKE_FAIL (a call whose arguments contain it fails),
FAKE_RULESET_ID (the id a rulesets query prints) and FAKE_VARIABLE (whether
the SONAR_ENABLED variable exists).
"""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / "bootstrap.sh"
REPO = "o/r"

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"args": args, "stdin": sys.stdin.read()}) + "\n")
fail = os.environ.get("FAKE_FAIL")
if fail and fail in " ".join(args):
    print(f"HTTP 403: refused ({fail})", file=sys.stderr)
    sys.exit(1)
path = next((a for a in args if a.startswith("repos/")), "")
if "-X" not in args and path.endswith("/rulesets"):
    print(os.environ.get("FAKE_RULESET_ID", ""))
elif "-X" not in args and "/actions/variables/" in path:
    sys.exit(0 if os.environ.get("FAKE_VARIABLE") else 1)
"""


class Bootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        gh = self.dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.log = self.dir / "log.jsonl"

    def run_script(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        environ = {**os.environ, "PATH": f"{self.dir}:{os.environ['PATH']}",
                   "FAKE_LOG": str(self.log), **env}
        return subprocess.run(["bash", str(SCRIPT), *args], env=environ,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              check=False)

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def find(self, method: str, path: str) -> list[dict]:
        """The calls with that method (-X) and exactly that path."""
        found = []
        for call in self.calls():
            args = call["args"]
            called = args[args.index("-X") + 1] if "-X" in args else "GET"
            if called == method and path in args:
                found.append(call)
        return found

    def ruleset(self, method: str, path: str) -> dict:
        (call,) = self.find(method, path)
        return json.loads(call["stdin"])

    def test_defaults(self) -> None:
        result = self.run_script(REPO)
        self.assertEqual(result.returncode, 0, result.stderr)
        (merge,) = [c for c in self.find("PATCH", f"repos/{REPO}")
                    if "allow_merge_commit=false" in c["args"]]
        for arg in ("allow_squash_merge=true", "allow_rebase_merge=false",
                    "squash_merge_commit_title=COMMIT_OR_PR_TITLE",
                    "squash_merge_commit_message=COMMIT_MESSAGES",
                    "delete_branch_on_merge=true", "allow_update_branch=true",
                    "has_wiki=false", "has_projects=false"):
            self.assertIn(arg, merge["args"])
        self.assertTrue(self.find("PUT", f"repos/{REPO}/vulnerability-alerts"))
        self.assertTrue(self.find("PUT", f"repos/{REPO}/automated-security-fixes"))
        self.assertTrue(self.find("PUT", f"repos/{REPO}/private-vulnerability-reporting"))
        (scanning,) = [c for c in self.find("PATCH", f"repos/{REPO}")
                       if "secret_scanning_push_protection" in c["stdin"]]
        self.assertEqual(json.loads(scanning["stdin"])["security_and_analysis"]
                         ["secret_scanning"]["status"], "enabled")
        self.assertTrue(self.find("PATCH", f"repos/{REPO}/code-scanning/default-setup"))

        body = self.ruleset("POST", f"repos/{REPO}/rulesets")
        self.assertEqual(body["name"], "checks")
        self.assertEqual(body["enforcement"], "active")
        self.assertEqual(body["conditions"]["ref_name"]["include"], ["~DEFAULT_BRANCH"])
        self.assertEqual([r["type"] for r in body["rules"]],
                         ["required_status_checks", "code_scanning"])
        checks = body["rules"][0]["parameters"]["required_status_checks"]
        self.assertEqual([c["context"] for c in checks],
                         ["version", "actionlint / actionlint", "docs / docs.page check"])
        self.assertEqual({c["integration_id"] for c in checks}, {15368})

        joined = [" ".join(c["args"]) for c in self.calls()]
        self.assertFalse(any("actions/variables" in j for j in joined))
        self.assertFalse(any("is_template=true" in j for j in joined))

    def test_updates_an_existing_ruleset(self) -> None:
        result = self.run_script(REPO, FAKE_RULESET_ID="7")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ruleset("PUT", f"repos/{REPO}/rulesets/7")["name"], "checks")
        self.assertFalse(self.find("POST", f"repos/{REPO}/rulesets"))

    def test_codeql_refused_warns_and_leaves_it_out(self) -> None:
        result = self.run_script(REPO, FAKE_FAIL="code-scanning")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning", result.stderr)
        body = self.ruleset("POST", f"repos/{REPO}/rulesets")
        self.assertEqual([r["type"] for r in body["rules"]], ["required_status_checks"])

    def test_options(self) -> None:
        result = self.run_script(REPO, "--checks", "build, test", "--sonar", "--template")
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = self.ruleset("POST", f"repos/{REPO}/rulesets")["rules"][0]["parameters"][
            "required_status_checks"]
        self.assertEqual([c["context"] for c in checks], ["build", "test"])
        (variable,) = self.find("POST", f"repos/{REPO}/actions/variables")
        self.assertIn("name=SONAR_ENABLED", variable["args"])
        self.assertIn("value=true", variable["args"])
        self.assertTrue([c for c in self.find("PATCH", f"repos/{REPO}")
                         if "is_template=true" in c["args"]])

    def test_existing_variable_is_updated(self) -> None:
        result = self.run_script(REPO, "--sonar", FAKE_VARIABLE="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.find("PATCH", f"repos/{REPO}/actions/variables/SONAR_ENABLED"))
        self.assertFalse(self.find("POST", f"repos/{REPO}/actions/variables"))

    def test_usage(self) -> None:
        for args in ((), ("--sonar",), (REPO, "--unknown"), (REPO, "other/repo"),
                     (REPO, "--checks")):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 2)

    def test_other_failures_stop(self) -> None:
        result = self.run_script(REPO, FAKE_FAIL="allow_merge_commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.find("POST", f"repos/{REPO}/rulesets"))


if __name__ == "__main__":
    unittest.main()
