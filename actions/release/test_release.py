"""release.py's tests: python3 -m unittest discover -s actions/release -v"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import release

RELEASE = Path(__file__).resolve().parent / "release.py"
# git without the user's or the system's configuration (signed tags, hooks...)
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def temp_dir(test: unittest.TestCase) -> Path:
    path = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, path)
    return path


class Parse(unittest.TestCase):
    def test_semver(self) -> None:
        self.assertEqual(release.parse("1.20.3"), (1, 20, 3))

    def test_refuses_anything_else(self) -> None:
        for bad in ("1.2", "1.2.3.4", "01.2.3", "v1.2.3", "1.2.3-rc1", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                release.parse(bad)


class Decide(unittest.TestCase):
    def test_first_release(self) -> None:
        self.assertEqual(release.decide("0.1.0", []), "v0.1.0")

    def test_already_released(self) -> None:
        self.assertIsNone(release.decide("0.1.0", ["v0.1.0"]))

    def test_next_version(self) -> None:
        self.assertEqual(release.decide("0.2.0", ["v0.1.0"]), "v0.2.0")

    def test_below_the_latest_release(self) -> None:
        with self.assertRaisesRegex(ValueError, "0.1.5 is below the latest release v0.2.0"):
            release.decide("0.1.5", ["v0.1.0", "v0.2.0"])

    def test_ignores_other_tags(self) -> None:
        self.assertEqual(release.decide("0.1.0", ["latest", "v9", "vx.y.z"]), "v0.1.0")

    def test_compares_numbers_not_text(self) -> None:
        self.assertEqual(release.decide("0.10.0", ["v0.9.0"]), "v0.10.0")


class ReadVersion(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = temp_dir(self)

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text)
        return path

    def test_plain_file(self) -> None:
        self.assertEqual(release.read_version(self.write("VERSION", "0.1.0\n")), "0.1.0")

    def test_json(self) -> None:
        path = self.write("package.json", '{"name": "x", "version": "1.2.3"}')
        self.assertEqual(release.read_version(path), "1.2.3")

    def test_toml(self) -> None:
        path = self.write("pyproject.toml", '[project]\nname = "x"\nversion = "2.0.0"\n')
        self.assertEqual(release.read_version(path), "2.0.0")

    def test_missing_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "not found"):
            release.read_version(self.dir / "VERSION")

    def test_json_without_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "has no version"):
            release.read_version(self.write("package.json", '{"name": "x"}'))

    def test_toml_without_project_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "has no version"):
            release.read_version(self.write("pyproject.toml", '[tool.x]\nversion = "1.0.0"\n'))

    def test_other_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "use VERSION, a .json"):
            release.read_version(self.write("version.txt", "1.0.0"))


class Main(unittest.TestCase):
    """The CLI in a real git repository, as the action runs it."""

    def setUp(self) -> None:
        self.dir = temp_dir(self)
        self.git("init", "-q")
        self.git("commit", "-q", "--allow-empty", "-m", "init")
        (self.dir / "VERSION").write_text("0.2.0\n")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.dir, env=GIT_ENV, check=True)

    def run_release(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(RELEASE), *args], cwd=self.dir,
                              env=GIT_ENV, capture_output=True, text=True, check=False)

    def test_check_unreleased(self) -> None:
        result = self.run_release("check")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "release: v0.2.0 will be published")

    def test_check_released(self) -> None:
        self.git("tag", "v0.2.0")
        self.assertEqual(self.run_release("check").stdout.strip(), "release: already released")

    def test_check_below_the_latest(self) -> None:
        self.git("tag", "v0.3.0")
        result = self.run_release("check")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(),
                         "release: 0.2.0 is below the latest release v0.3.0")

    def test_next(self) -> None:
        self.assertEqual(self.run_release("next").stdout, "v0.2.0\n")

    def test_next_released(self) -> None:
        self.git("tag", "v0.2.0")
        self.assertEqual(self.run_release("next").stdout, "\n")

    def test_other_version_file(self) -> None:
        (self.dir / "package.json").write_text('{"version": "0.4.0"}')
        self.assertEqual(self.run_release("next", "package.json").stdout, "v0.4.0\n")

    def test_missing_version_file(self) -> None:
        (self.dir / "VERSION").unlink()
        result = self.run_release("check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("VERSION not found", result.stdout)

    def test_usage(self) -> None:
        for args in ((), ("publish",), ("check", "VERSION", "extra")):
            with self.subTest(args=args):
                self.assertEqual(self.run_release(*args).returncode, 2)


if __name__ == "__main__":
    unittest.main()
