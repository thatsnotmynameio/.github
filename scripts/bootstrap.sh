#!/usr/bin/env bash
# Applies the organization's GitHub settings to a repository. Idempotent: run
# it again at any time. "Use this template" copies files only, so every new
# repository runs it once.
#
# Usage: scripts/bootstrap.sh <owner/repo> [--checks "a,b,c"] [--sonar] [--template]
#   --checks    required status checks, comma-separated job names (a reusable
#               workflow's job reports as "<caller job> / <its job>")
#   --sonar     sets the variable SONAR_ENABLED=true, which turns the Sonar workflow on
#   --template  marks the repository as a template repository
#
# Needs gh, logged in as an admin of the repository, and python3.
set -euo pipefail

CHECKS="version,actionlint / actionlint,docs / docs.page check"
GITHUB_ACTIONS=15368 # the GitHub Actions app: a required check only counts from it
RULESET=checks

usage() {
  sed -n '6,10p' "$0" >&2
  exit 2
}

warn() {
  echo "warning: $*" >&2
}

# A security feature GitHub may refuse for the plan (a private repository
# without GitHub Advanced Security): warn and go on.
soft() {
  if "$@"; then
    return 0
  fi
  warn "refused: $*; GitHub Advanced Security may be required. Continuing."
  return 1
}

repo=""
sonar=false
template=false
while [ $# -gt 0 ]; do
  case "$1" in
    --checks)
      [ $# -ge 2 ] || usage
      CHECKS="$2"
      shift 2
      ;;
    --sonar)
      sonar=true
      shift
      ;;
    --template)
      template=true
      shift
      ;;
    -*) usage ;;
    *)
      [ -z "$repo" ] || usage
      repo="$1"
      shift
      ;;
  esac
done
[ -n "$repo" ] || usage

echo "Merge settings"
gh api -X PATCH "repos/$repo" --silent \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -f squash_merge_commit_title=COMMIT_OR_PR_TITLE -f squash_merge_commit_message=COMMIT_MESSAGES \
  -F delete_branch_on_merge=true -F allow_update_branch=true \
  -F has_wiki=false -F has_projects=false

echo "Security"
soft gh api -X PUT "repos/$repo/vulnerability-alerts" --silent || true
soft gh api -X PUT "repos/$repo/automated-security-fixes" --silent || true
soft gh api -X PUT "repos/$repo/private-vulnerability-reporting" --silent || true
soft gh api -X PATCH "repos/$repo" --silent --input - <<'JSON' || true
{"security_and_analysis": {"secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "enabled"}}}
JSON
codeql=false
if soft gh api -X PATCH "repos/$repo/code-scanning/default-setup" --silent -f state=configured; then
  codeql=true
fi

echo "Ruleset \"$RULESET\""
# Code scanning is required only when CodeQL runs: a required check that never
# comes would block every pull request.
body=$(CHECKS="$CHECKS" CODEQL="$codeql" APP="$GITHUB_ACTIONS" NAME="$RULESET" python3 - <<'PY'
import json
import os

checks = [c.strip() for c in os.environ["CHECKS"].split(",") if c.strip()]
rules = [{
    "type": "required_status_checks",
    "parameters": {
        "strict_required_status_checks_policy": False,
        "do_not_enforce_on_create": False,
        "required_status_checks": [
            {"context": c, "integration_id": int(os.environ["APP"])} for c in checks
        ],
    },
}]
if os.environ["CODEQL"] == "true":
    rules.append({
        "type": "code_scanning",
        "parameters": {"code_scanning_tools": [{
            "tool": "CodeQL",
            "alerts_threshold": "errors",
            "security_alerts_threshold": "high_or_higher",
        }]},
    })
print(json.dumps({
    "name": os.environ["NAME"],
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": rules,
}))
PY
)
id=$(gh api "repos/$repo/rulesets" --jq ".[] | select(.source_type == \"Repository\" and .name == \"$RULESET\") | .id")
if [ -n "$id" ]; then
  gh api -X PUT "repos/$repo/rulesets/$id" --silent --input - <<<"$body"
else
  gh api -X POST "repos/$repo/rulesets" --silent --input - <<<"$body"
fi

if [ "$sonar" = true ]; then
  echo "Variable SONAR_ENABLED"
  if gh api "repos/$repo/actions/variables/SONAR_ENABLED" --silent 2>/dev/null; then
    gh api -X PATCH "repos/$repo/actions/variables/SONAR_ENABLED" --silent \
      -f name=SONAR_ENABLED -f value=true
  else
    gh api -X POST "repos/$repo/actions/variables" --silent -f name=SONAR_ENABLED -f value=true
  fi
fi

if [ "$template" = true ]; then
  echo "Template repository"
  gh api -X PATCH "repos/$repo" --silent -F is_template=true
fi

echo
echo "Result"
gh api "repos/$repo" --jq '{allow_squash_merge, allow_merge_commit, allow_rebase_merge, delete_branch_on_merge, allow_update_branch, is_template, security_and_analysis}'
gh api "repos/$repo/rulesets" --jq '.[] | "ruleset: \(.name) (\(.source_type), \(.enforcement))"'
