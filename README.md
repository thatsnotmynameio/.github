# thatsnotmynameio/.github

The shared pieces of thatsnotmynameio's repositories, written once:

- **Reusable workflows** (`.github/workflows/`): `actionlint.yml`, `claude.yml`, `docs.yml`, `sonar.yml`.
- **Actions** (`actions/`): `release`, the release by version bump.
- **`scripts/bootstrap.sh`**: the GitHub settings a new repository needs (a template copies files only).
- **`SECURITY.md`**: the security policy of every repository of the organization without its own.

New repositories start from [thatsnotmynameio/template](https://github.com/thatsnotmynameio/template), which calls all of this.

## Calling a workflow or an action

Pin by SHA, with the version as a comment; Dependabot (`github-actions`) opens the pull request when a new version is released:

```yaml
jobs:
  actionlint:
    uses: thatsnotmynameio/.github/.github/workflows/actionlint.yml@<sha> # v0.1.0
```

| Piece | Inputs | Secrets | The caller grants | Check name |
| --- | --- | --- | --- | --- |
| `.github/workflows/actionlint.yml` | none | none | `contents: read` | `<job> / actionlint` |
| `.github/workflows/claude.yml` | `claude-args` | `secrets: inherit` (`CLAUDE_CODE_OAUTH_TOKEN`) | `contents: read`, `pull-requests: read`, `issues: read`, `id-token: write`, `actions: read` | `<job> / claude` |
| `.github/workflows/docs.yml` | none | none | `contents: read` | `<job> / docs.page check` |
| `.github/workflows/sonar.yml` | `coverage-artifact` | `secrets: inherit` (`SONAR_TOKEN`) | `contents: read` | `<job> / SonarQube` |
| `actions/release` | `mode` (`check` / `publish`), `version-file` (`VERSION`), `token` | none | `contents: write` for `publish` | the calling job's |

`claude.yml` keeps the caller's triggers: the caller declares `issue_comment`, `pull_request_review_comment`, `issues` and `pull_request_review`. `CLAUDE_CODE_OAUTH_TOKEN` and `SONAR_TOKEN` are organization secrets; a repository that uses them must have access to them.

## Release by version bump

The version file (`VERSION` by default, or a `.json`'s `version`, or a `.toml`'s `project.version`) is the release to publish:

- on pull requests, `mode: check` fails unless it is `MAJOR.MINOR.PATCH` and not below the latest `v*` tag;
- on pushes to `main`, `mode: publish` tags it `vX.Y.Z` and publishes a GitHub release with generated notes, unless the tag exists.

Both need a checkout with `fetch-depth: 0`. Versions start at `0.1.0`.

## Bootstrap

```sh
gh repo clone thatsnotmynameio/.github /tmp/thatsnotmynameio-github -- --depth 1
/tmp/thatsnotmynameio-github/scripts/bootstrap.sh thatsnotmynameio/<repo> [--checks "a,b,c"] [--sonar] [--template]
```

Clone it outside the target repository: a clone named `.github` inside it would collide with its own `.github/`.

Idempotent, as an admin of the repository:

- **Merge:** squash only (the pull request's title, the commits' messages), the branch deleted on merge, "update branch" on, no wiki or projects.
- **Security:** Dependabot alerts and security updates, private vulnerability reporting, secret scanning and push protection, CodeQL's default setup. On a private repository without GitHub Advanced Security, a refused one warns and the script goes on.
- **Ruleset `checks`:**
  - It targets the default branch. Its required status checks come from GitHub Actions and default to `version`, `actionlint / actionlint` and `docs / docs.page check`.
  - It also requires code scanning when CodeQL's default setup took. GitHub accepts that setup even for a repository with no code yet, and the rule doesn't block a pull request before CodeQL has analysed anything.
- **`--sonar`:** sets the variable `SONAR_ENABLED=true`. **`--template`:** marks the repository as a template.

The organization ruleset "main rule" (pull requests, squash, no force push or deletion, threads resolved) applies to every repository by itself.

## Developing

```sh
python3 -m unittest discover -s actions/release -v
python3 -m unittest discover -s scripts -v
shellcheck scripts/bootstrap.sh
actionlint
```

A pull request that bumps `VERSION` is a release: once it merges, the Release workflow publishes `vX.Y.Z`. Actions are pinned by SHA.
