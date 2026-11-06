"""Check an isolated installed distribution, not the source checkout."""

import subprocess
import sys
import tempfile
from importlib import metadata, resources
from pathlib import Path

import gitlab_groupsync
from gitlab_groupsync.config import load_config


def main() -> None:
    expected = sys.argv[1]
    if (
        metadata.version("gitlab-groupsync") != expected
        or gitlab_groupsync.__version__ != expected
    ):
        raise SystemExit("Installed distribution and runtime version do not match")
    installed = Path(gitlab_groupsync.__file__).resolve()
    recorded = Path(
        metadata.distribution("gitlab-groupsync").locate_file(
            "gitlab_groupsync/__init__.py"
        )
    ).resolve()
    if installed != recorded:
        raise SystemExit("Smoke test imported source outside the isolated installation")
    if (
        not resources.files("gitlab_groupsync")
        .joinpath("default_config.yaml")
        .is_file()
    ):
        raise SystemExit("Installed distribution is missing default_config.yaml")
    if load_config(None, [])["inventory"]["projects"] != []:
        raise SystemExit("Installed default configuration did not load correctly")
    with tempfile.TemporaryDirectory() as directory:
        output = subprocess.run(
            ["gl-groupsync", "--version"],
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
        )
        if output.stdout.strip() != f"gl-groupsync, version {expected}":
            raise SystemExit("Installed CLI reports an unexpected version")
        subprocess.run(["gl-groupsync", "--help"], cwd=directory, check=True)
        config = Path(directory) / "config.yaml"
        subprocess.run(
            ["gl-groupsync", "config-template", "--output", str(config)],
            cwd=directory,
            check=True,
        )
        template = config.read_text()
        if "inventory:" not in template or "oc_schema" in template:
            raise SystemExit("Installed CLI could not generate a valid template")
    print(f"Installed distribution smoke test passed: {expected}")


if __name__ == "__main__":
    main()
