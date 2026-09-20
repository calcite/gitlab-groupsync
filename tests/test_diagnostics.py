"""Local status rendering and doctor tests using read-only fakes."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from gitlab_groupsync import cli
from gitlab_groupsync.config import load_config
from gitlab_groupsync.diagnostics import (
    DiagnosticCheck,
    DoctorReport,
    render_doctor,
    render_status,
    run_doctor,
)
from gitlab_groupsync.gitlab_api import DiscoveryError
from gitlab_groupsync.state import DestinationLock, StateError


@pytest.fixture
def doctor_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.delenv("GL_GROUPSYNC__SYNC__WORKERS", raising=False)
    config = deepcopy(dict(load_config(None, [])))
    config["gitlab"].update(
        url="https://gitlab.example/base", group="root", ca_bundle="ca.pem"
    )
    config["storage"]["destination"] = str(tmp_path / "corpus")
    config["inventory"] = {
        "root_group": {"id": 1, "full_path": "root"},
        "groups": [{"id": 1, "full_path": "root", "wiki": True}],
        "projects": [
            {
                "id": 2,
                "full_path": "root/project",
                "repository": True,
                "wiki": True,
                "work_items": True,
            }
        ],
    }
    return config


class FakeDoctorClient:
    metadata: dict[str, Any] | None = {"version": "18.4.0"}
    version: dict[str, Any] | None = {"version": "18.4.0"}
    probe_status: dict[str, int] = {}
    failure: str | None = None
    calls: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).calls.append(f"init:{args[0]}:{kwargs['ca_bundle']}")

    def __enter__(self) -> "FakeDoctorClient":
        return self

    def __exit__(self, *args: object) -> None:
        type(self).calls.append("close")

    def get_object(self, endpoint: str) -> dict[str, Any]:
        type(self).calls.append(endpoint)
        if self.failure:
            raise DiscoveryError(self.failure)
        return {"id": 1, "full_path": "root"}

    def get_optional_object(self, endpoint: str) -> dict[str, Any] | None:
        type(self).calls.append(endpoint)
        return self.metadata if endpoint == "metadata" else self.version

    def iter_list(self, endpoint: str, params: dict[str, Any]) -> Any:
        type(self).calls.append(endpoint)
        if endpoint.endswith("descendant_groups"):
            return iter(())
        return iter(({"id": 2, "path_with_namespace": "root/project"},))

    def probe(self, endpoint: str) -> int:
        type(self).calls.append(endpoint)
        return self.probe_status.get(endpoint, 200)


def _git_success(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args[0], 0, "git version 2.47.3\n", "")


def _checks(report: DoctorReport) -> dict[str, DiagnosticCheck]:
    return {check.name: check for check in report.checks}


def test_doctor_success_metadata_capabilities_and_custom_ca(
    doctor_config: dict[str, Any],
) -> None:
    FakeDoctorClient.calls = []
    FakeDoctorClient.metadata = {"version": "18.4.0"}
    FakeDoctorClient.probe_status = {}
    FakeDoctorClient.failure = None
    report = run_doctor(
        doctor_config,
        "secret",
        client_factory=FakeDoctorClient,
        git_runner=_git_success,
    )
    assert report.healthy is True
    checks = _checks(report)
    assert checks["git"].detail == "git version 2.47.3"
    assert checks["tls"].detail == "verified with custom CA ca.pem"
    assert checks["server_metadata"].detail == "metadata: 18.4.0"
    assert checks["requested_capabilities"].detail.startswith("3 selected")
    assert "groups/1/wikis" in FakeDoctorClient.calls
    assert "projects/2/issues" in FakeDoctorClient.calls
    assert "secret" not in render_doctor(report)


def test_doctor_metadata_fallback_and_absence_are_healthy(
    doctor_config: dict[str, Any],
) -> None:
    doctor_config["inventory"]["groups"][0]["wiki"] = False
    doctor_config["inventory"]["projects"][0].update(
        repository=False, wiki=False, work_items=False
    )
    FakeDoctorClient.metadata = None
    FakeDoctorClient.version = {"version": "17.0"}
    report = run_doctor(
        doctor_config,
        "token",
        client_factory=FakeDoctorClient,
        git_runner=_git_success,
    )
    assert _checks(report)["server_metadata"].detail == "version: 17.0"
    assert _checks(report)["requested_capabilities"].detail.startswith("0 selected")

    FakeDoctorClient.version = None
    report = run_doctor(
        doctor_config,
        "token",
        client_factory=FakeDoctorClient,
        git_runner=_git_success,
    )
    assert report.healthy is True
    assert "unavailable" in _checks(report)["server_metadata"].detail


def test_doctor_git_auth_tls_discovery_and_capability_failures(
    doctor_config: dict[str, Any],
) -> None:
    def missing_git(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError

    FakeDoctorClient.failure = "GitLab returned HTTP 401 for groups/root"
    report = run_doctor(
        doctor_config,
        "token",
        client_factory=FakeDoctorClient,
        git_runner=missing_git,
    )
    checks = _checks(report)
    assert report.healthy is False
    assert checks["git"].ok is False
    assert checks["tls"].ok is True
    assert checks["authentication"].ok is False
    assert "401" in checks["root_visibility"].detail

    FakeDoctorClient.failure = "TLS certificate verification failed"
    report = run_doctor(
        doctor_config,
        "token",
        client_factory=FakeDoctorClient,
        git_runner=lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "bad", ""),
    )
    assert _checks(report)["tls"].ok is False

    FakeDoctorClient.failure = "GitLab returned HTTP 403 for groups/root"
    report = run_doctor(
        doctor_config,
        "token",
        client_factory=FakeDoctorClient,
        git_runner=_git_success,
    )
    assert "denied access" in _checks(report)["authentication"].detail

    FakeDoctorClient.failure = None
    FakeDoctorClient.probe_status = {
        "groups/1/wikis": 404,
        "projects/2/wikis": 404,
    }
    report = run_doctor(
        doctor_config,
        "token",
        client_factory=FakeDoctorClient,
        git_runner=_git_success,
    )
    assert _checks(report)["requested_capabilities"].ok is False
    assert "group wiki" in _checks(report)["requested_capabilities"].detail


def test_doctor_invisible_selection_and_late_remote_failure(
    doctor_config: dict[str, Any],
) -> None:
    doctor_config["inventory"]["groups"].append(
        {"id": 9, "full_path": "root/hidden", "wiki": True}
    )
    doctor_config["inventory"]["projects"].append(
        {
            "id": 8,
            "full_path": "root/hidden",
            "repository": True,
            "wiki": False,
            "work_items": False,
        }
    )
    FakeDoctorClient.failure = None
    FakeDoctorClient.probe_status = {}
    report = run_doctor(
        doctor_config,
        "token",
        client_factory=FakeDoctorClient,
        git_runner=_git_success,
    )
    detail = _checks(report)["requested_capabilities"].detail
    assert "group 9" in detail and "project 8" in detail

    class BrokenMetadataClient(FakeDoctorClient):
        def get_optional_object(self, endpoint: str) -> None:
            raise DiscoveryError("metadata malformed")

    report = run_doctor(
        doctor_config,
        "token",
        client_factory=BrokenMetadataClient,
        git_runner=_git_success,
    )
    assert _checks(report)["remote_diagnostics"].ok is False


def test_status_rendering_human_and_json() -> None:
    uninitialized = {
        "initialized": False,
        "current_run": True,
    }
    assert "uninitialized" in render_status(uninitialized, as_json=False)
    status = {
        "initialized": True,
        "identity": {"instance_url": "https://gitlab", "root_group_id": 1},
        "current_run": False,
        "latest_run": {"outcome": "running", "interrupted": True},
        "resources": {"total": 2, "retained_content": 1, "by_status": {"ok": 2}},
        "freshness": {"last_attempt_at": None, "last_success_at": "then"},
        "drift": {
            "added": [1],
            "absent": [],
            "renamed": [],
            "path_reused": [],
        },
    }
    human = render_status(status, as_json=False)
    assert "interrupted" in human
    assert "retained=1" in human
    assert "added=1" in human
    assert json.loads(render_status(status, as_json=True)) == status
    no_run = dict(status, latest_run=None, drift=None)
    assert "Run: none" in render_status(no_run, as_json=False)


def test_status_cli_is_local_and_doctor_cli_exit_codes(
    doctor_config: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "status-corpus"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "gitlab:\n  url: https://gitlab.example\n  group: root\n"
        "  token_env: NEVER_LOAD_THIS\n"
        f"storage:\n  destination: {destination}\n"
    )
    monkeypatch.setattr(cli, "_load_token_or_usage", lambda config: pytest.fail())
    monkeypatch.setattr(cli, "GitLabClient", lambda *a, **k: pytest.fail())
    result = CliRunner().invoke(
        cli.main, ["status", "--config", str(config_path), "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["initialized"] is False
    assert not destination.exists()

    healthy = DoctorReport((DiagnosticCheck("all", True, "healthy"),))
    monkeypatch.setattr(cli, "_load_token_or_usage", lambda config: "token")
    monkeypatch.setattr(cli, "run_doctor", lambda config, token: healthy)
    result = CliRunner().invoke(cli.main, ["doctor", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "Healthy" in result.output

    partial = DoctorReport((DiagnosticCheck("git", False, "missing"),))
    monkeypatch.setattr(cli, "run_doctor", lambda config, token: partial)
    result = CliRunner().invoke(cli.main, ["doctor", "--config", str(config_path)])
    assert result.exit_code == 1
    assert "Partial failures" in result.output


def test_status_cli_state_error_and_sync_lock_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"storage:\n  destination: {destination}\n")

    def fail_status(path: str) -> Any:
        raise StateError("bad")

    monkeypatch.setattr(cli, "local_status", fail_status)
    result = CliRunner().invoke(cli.main, ["status", "--config", str(config_path)])
    assert result.exit_code == 2
    assert "Could not read status" in result.output
    monkeypatch.undo()

    with DestinationLock(destination):
        result = CliRunner().invoke(
            cli.main,
            ["sync", "--config", str(config_path)],
            env={"GITLAB_TOKEN": "secret"},
        )
    assert result.exit_code == 3
    assert "destination lock" in result.output


def test_render_doctor_failure_and_subprocess_exception(
    doctor_config: dict[str, Any],
) -> None:
    FakeDoctorClient.failure = None
    FakeDoctorClient.probe_status = {}

    def timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired("git", 10)

    report = run_doctor(
        doctor_config,
        "token",
        client_factory=FakeDoctorClient,
        git_runner=timeout,
    )
    assert report.healthy is False
    assert render_doctor(report).endswith("Partial failures detected")
