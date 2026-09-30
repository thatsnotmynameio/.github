# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Semantic versions: the version file's version is the release to publish.

Usage:
    python3 release.py check [version-file]   # MAJOR.MINOR.PATCH, not below the latest release
    python3 release.py next [version-file]    # the tag to publish (vX.Y.Z), or nothing if released

The version file (default VERSION, relative to the current directory) is
VERSION (the whole file), a .json (its top-level "version") or a .toml (its
project.version). A pull request bumps it; the Release workflow publishes that
version once it merges. Tags are read from git (`v*`), so the checkout needs
them (fetch-depth: 0).
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")

type Version = tuple[int, int, int]


def parse(version: str) -> Version:
    """MAJOR.MINOR.PATCH as numbers; anything else is refused."""
    match = SEMVER.fullmatch(version)
    if match is None:
        raise ValueError(f"{version!r} is not MAJOR.MINOR.PATCH")
    return int(match[1]), int(match[2]), int(match[3])


def released(tags: list[str]) -> list[Version]:
    """The versions the `vX.Y.Z` tags name; other tags are ignored."""
    versions = []
    for tag in tags:
        try:
            versions.append(parse(tag.removeprefix("v")))
        except ValueError:
            continue
    return versions


def decide(version: str, tags: list[str]) -> str | None:
    """The tag to publish for `version`, None when it is already released."""
    current = parse(version)
    done = released(tags)
    if current in done:
        return None
    if done and current < max(done):
        latest = ".".join(map(str, max(done)))
        raise ValueError(f"{version} is below the latest release v{latest}")
    return f"v{version}"


def read_version(path: Path) -> str:
    """The version the file holds, by its kind."""
    if not path.is_file():
        raise ValueError(f"{path} not found")
    text = path.read_text()
    if path.suffix == "":
        return text.strip()
    if path.suffix == ".json":
        version = json.loads(text).get("version")
    elif path.suffix == ".toml":
        version = tomllib.loads(text).get("project", {}).get("version")
    else:
        raise ValueError(
            f"{path}: use VERSION, a .json with a version or a .toml with project.version"
        )
    if version is None:
        raise ValueError(f"{path} has no version")
    return str(version)


def git_tags() -> list[str]:
    """This repository's version tags."""
    result = subprocess.run(["git", "tag", "--list", "v*"], capture_output=True, text=True,
                            check=True)
    return result.stdout.split()


def main(argv: list[str]) -> int:
    """Run `check` or `next`; print the outcome."""
    if len(argv) not in (2, 3) or argv[1] not in ("check", "next"):
        print(__doc__)
        return 2
    path = Path(argv[2] if len(argv) == 3 else "VERSION")
    try:
        tag = decide(read_version(path), git_tags())
    except ValueError as error:
        print(f"release: {error}")
        return 1
    if argv[1] == "next":
        print(tag or "")
    else:
        print(f"release: {tag} will be published" if tag else "release: already released")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
