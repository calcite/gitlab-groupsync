"""Check source, installed, lockfile, changelog and optional release-tag versions."""

import argparse
import os
import tomllib
from importlib.metadata import version
from pathlib import Path

from gitlab_groupsync import __version__


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG"))
    args = parser.parse_args()
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    locked = tomllib.loads(Path("uv.lock").read_text())["package"]
    lock_version = next(
        item["version"] for item in locked if item["name"] == "gitlab-groupsync"
    )
    versions = {
        "pyproject.toml": project["version"],
        "runtime": __version__,
        "installed metadata": version(project["name"]),
        "uv.lock": lock_version,
    }
    if len(set(versions.values())) != 1:
        raise SystemExit(f"Release version mismatch: {versions}")
    declared = project["version"]
    if args.tag and args.tag != f"v{declared}":
        raise SystemExit(f"Release tag {args.tag!r} must match v{declared}")
    if f"## {declared} (" not in Path("CHANGELOG.md").read_text():
        raise SystemExit(f"CHANGELOG.md has no dated entry for {declared}")
    print(f"Release metadata consistent: {declared}")


if __name__ == "__main__":
    main()
