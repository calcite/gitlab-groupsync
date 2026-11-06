"""Operational documentation, generated guide, and sample-corpus contracts."""

import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

from gitlab_groupsync.search_guide import search_guide_content, write_search_guide

ROOT = Path(__file__).parent.parent


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_search_guide_is_deterministic_complete_and_noop(tmp_path: Path) -> None:
    guide = search_guide_content()
    required = (
        "Search `content/`",
        "`.sync/` internal state",
        "`stale/` retained or quarantined",
        "`manifest.json`",
        "freshness",
        "provenance",
        "default branches",
        "issues and tasks",
        "untrusted data",
        "original GitLab object",
        "not a development checkout",
        "read-only bind mount",
        "rg --hidden --no-ignore -g '!.git' 'pattern' content/",
        "binary documents",
        "optional LFS selection",
        "attachments",
        "not atomic snapshots",
        "atomic per item",
    )
    assert all(value in guide for value in required)
    write_search_guide(tmp_path)
    path = tmp_path / "SEARCH_GUIDE.md"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    write_search_guide(tmp_path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_checked_in_sample_matches_generator_and_contains_required_evidence(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "sample"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples/generate_sample_corpus.py"),
            "--output",
            str(generated),
        ],
        cwd=ROOT,
        check=True,
    )
    checked_in = ROOT / "examples/sample-corpus"
    assert _files(generated) == _files(checked_in)
    paths = set(_files(checked_in))
    assert Path("manifest.json") in paths
    assert Path("SEARCH_GUIDE.md") in paths
    assert any("/repository/" in f"/{path.as_posix()}/" for path in paths)
    assert any(
        "/projects/" in f"/{path.as_posix()}/" and "/wiki/" in f"/{path.as_posix()}/"
        for path in paths
    )
    assert any(
        "/groups/" in f"/{path.as_posix()}/" and "/wiki/" in f"/{path.as_posix()}/"
        for path in paths
    )
    assert any("/work-items/1.md" in f"/{path.as_posix()}" for path in paths)
    assert any(path.as_posix().startswith("stale/objects/") for path in paths)
    assert any(path.as_posix().startswith("stale/components/") for path in paths)
    all_text = "\n".join(value.decode("utf-8") for value in _files(checked_in).values())
    assert "Fixture-only" in all_text or "fixture-only" in all_text
    assert "Human Conversations" in all_text
    assert "System Activity" in all_text
    assert "## Provenance" in all_text
    assert "[local](2.md)" in all_text
    assert "/-/issues/1" in all_text
    assert "/-/work_items/2" in all_text
    assert "state.sqlite3" not in {path.name for path in paths}
    assert not any(".git" in path.parts for path in paths)
    assert "PRIVATE-TOKEN" not in all_text


def test_config_scheduler_and_live_test_examples_are_safe_and_complete() -> None:
    yaml = YAML(typ="safe")
    bootstrap_text = (ROOT / "examples/config.bootstrap.yaml").read_text()
    discovered_text = (ROOT / "examples/config.discovered-ce.yaml").read_text()
    bootstrap = yaml.load(bootstrap_text)
    discovered = yaml.load(discovered_text)
    for text in (bootstrap_text, discovered_text):
        assert "oc_schema" not in text and "oc_default" not in text
        assert "PRIVATE-TOKEN" not in text
    assert bootstrap["inventory"] == {
        "root_group": None,
        "groups": [],
        "projects": [],
    }
    assert all(not group["wiki"] for group in discovered["inventory"]["groups"])
    assert discovered["inventory"]["projects"][0] == {
        "id": 1000,
        "full_path": "engineering/platform/reference-app",
        "repository": True,
        "lfs": False,
        "wiki": True,
        "work_items": True,
    }

    service = (ROOT / "examples/systemd/gl-groupsync.service").read_text()
    timer = (ROOT / "examples/systemd/gl-groupsync.timer").read_text()
    cron = (ROOT / "examples/cron.example").read_text()
    assert "gl-groupsync sync --config" in service
    assert "OnCalendar=hourly" in timer
    assert "full_reconcile_hours" in timer and "not auto-installed" in timer
    assert "gl-groupsync sync --config" in cron and "17 * * * *" in cron
    assert "full_reconcile_hours" in cron

    live = (ROOT / "docs/LIVE_TESTING.md").read_text()
    for name in (
        "GL_GROUPSYNC_LIVE_URL",
        "GL_GROUPSYNC_LIVE_ROOT_GROUP",
        "GL_GROUPSYNC_LIVE_TOKEN",
        "GL_GROUPSYNC_LIVE_EXPECTED_VERSION",
    ):
        assert name in live
    assert "pytest -m live" in live
    assert "forbidden" in live and "separate explicit authorization" in live
    capabilities = (ROOT / "docs/CAPABILITIES.md").read_text()
    assert "not live-tested" in capabilities
    assert "No disposable GitLab instance" in capabilities
    assert "issue_type=issue" in capabilities and "issue_type=task" in capabilities
    assert "WorkItemWidgetHierarchy" in capabilities
    assert "fixture-only and not live-tested" in capabilities


def test_readme_and_acceptance_matrix_cover_operational_contract() -> None:
    readme = (ROOT / "README.md").read_text()
    required = (
        "Python 3.13",
        "uv tool install",
        "config-template",
        "discover",
        "inventory",
        "sync --config",
        "--full",
        "status --config",
        "doctor --config",
        "GL_GROUPSYNC__SYNC__WORKERS",
        "token_env",
        "token_file",
        "git_transport: https",
        "git_transport: ssh",
        "ca_bundle",
        "content/",
        "manifest.json",
        "local_conflict",
        "retry queue",
        "stale/",
        "quarantine",
        "Exit codes",
        "systemd",
        "cron",
        "not live-tested",
    )
    assert all(value in readme for value in required)
    matrix = (ROOT / "docs/ACCEPTANCE_TEST_MATRIX.md").read_text()
    assert all(f"| {number} |" in matrix for number in range(1, 17))
    assert "fixture-only and not live-tested" in matrix
