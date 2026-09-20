"""Tests for the CLI and configuration foundation."""

import io
import stat
from copy import deepcopy
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from gitlab_groupsync import cli
from gitlab_groupsync import config as config_module
from gitlab_groupsync.config import ConfigurationError


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        "gitlab:\n  url: https://user.example.test\n"
        "storage:\n  destination: /tmp/reference\n"
        "sync:\n  workers: 2\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def valid_config(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.delenv("GL_GROUPSYNC__SYNC__WORKERS", raising=False)
    return deepcopy(dict(config_module.load_config(None, [])))


def test_installed_command_name() -> None:
    scripts = {
        entry.name: entry.value
        for entry in metadata.distribution("gitlab-groupsync").entry_points
        if entry.group == "console_scripts"
    }
    assert scripts == {"gl-groupsync": "gitlab_groupsync.cli:main"}


def test_root_and_command_help(runner: CliRunner) -> None:
    root = runner.invoke(cli.main, ["--help"])
    assert root.exit_code == 0
    for command in ("config-template", "discover", "sync", "status", "doctor"):
        assert command in root.output
        result = runner.invoke(cli.main, [command, "--help"])
        assert result.exit_code == 0
        assert "--help" in result.output

    assert "--output" in runner.invoke(cli.main, ["config-template", "--help"]).output
    assert "--replace-root" in runner.invoke(cli.main, ["discover", "--help"]).output
    assert "--full" in runner.invoke(cli.main, ["sync", "--help"]).output
    assert "--json" in runner.invoke(cli.main, ["status", "--help"]).output


def test_config_template_is_schema_and_secret_free(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "template-secret")
    output = tmp_path / "config.yaml"
    result = runner.invoke(cli.main, ["config-template", "--output", str(output)])
    assert result.exit_code == 0
    template = output.read_text(encoding="utf-8")

    assert "oc_schema" not in template
    assert "oc_default" not in template
    assert "token_env: GITLAB_TOKEN" in template
    assert "template-secret" not in template
    assert "inventory:" in template


def test_layering_and_config_reference_injection(
    runner: CliRunner,
    config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def capture(config: Any, token: str, *, report: Any, full: bool) -> int:
        observed["config"] = config
        observed["token"] = token
        observed["report"] = report
        observed["full"] = full
        return 0

    monkeypatch.setattr(cli, "run_sync", capture)
    result = runner.invoke(
        cli.main,
        [
            "sync",
            "--config",
            str(config_file),
            "--sync--workers",
            "8",
        ],
        env={
            "GL_GROUPSYNC__SYNC__WORKERS": "6",
            "GITLAB_TOKEN": "injected-secret",
        },
    )
    assert result.exit_code == 0
    assert observed["config"]["gitlab"]["url"] == "https://user.example.test"
    assert observed["config"]["sync"]["workers"] == 8
    assert "token" not in observed["config"]["gitlab"]
    assert observed["token"] == "injected-secret"
    assert observed["full"] is False
    result = runner.invoke(
        cli.main,
        ["sync", "--config", str(config_file), "--full"],
        env={"GITLAB_TOKEN": "injected-secret"},
    )
    assert result.exit_code == 0
    assert observed["full"] is True


def test_sync_setup_and_partial_exit_codes(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = runner.invoke(cli.main, ["sync", "--full"], env={"GITLAB_TOKEN": "secret"})
    assert result.exit_code == 2
    assert "run discover" in result.output
    assert "secret" not in result.output

    monkeypatch.setattr(cli, "run_sync", lambda *args, **kwargs: 1)
    result = runner.invoke(cli.main, ["sync"], env={"GITLAB_TOKEN": "secret"})
    assert result.exit_code == 1


def test_discover_requires_file_and_reports_safe_failure(
    runner: CliRunner, config_file: Path
) -> None:
    missing = runner.invoke(cli.main, ["discover"])
    assert missing.exit_code == 2
    result = runner.invoke(
        cli.main,
        ["discover", "--config", str(config_file)],
        env={"GITLAB_TOKEN": "secret"},
    )
    assert result.exit_code == 2
    assert "Discovery failed" in result.output
    assert "secret" not in result.output


@pytest.mark.parametrize(
    ("args", "environment", "message"),
    [
        (["sync", "--sync--workers", "0"], {}, "Invalid configuration"),
        (
            ["status", "--gitlab--url", "file:///tmp/gitlab"],
            {},
            "HTTP(S) base URL",
        ),
        (
            ["status"],
            {"GL_GROUPSYNC__UNKNOWN__VALUE": "x"},
            "invalid environment or CLI override",
        ),
    ],
)
def test_invalid_configuration_exits_two(
    runner: CliRunner,
    args: list[str],
    environment: dict[str, str],
    message: str,
) -> None:
    result = runner.invoke(cli.main, args, env=environment)
    assert result.exit_code == 2
    assert message in result.output


def test_validation_diagnostics_do_not_leak_token(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "highly-sensitive-value")
    result = runner.invoke(cli.main, ["sync", "--sync--workers", "0"])
    assert result.exit_code == 2
    assert "highly-sensitive-value" not in result.output


def test_missing_token_is_configuration_exit_two(runner: CliRunner) -> None:
    result = runner.invoke(cli.main, ["doctor"], env={"GITLAB_TOKEN": ""})
    assert result.exit_code == 2
    assert "configured token environment variable is unset or empty" in result.output


def test_malformed_yaml_is_a_safe_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("gitlab: [\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="could not load configuration YAML"):
        config_module.load_config(str(path), [])


def test_semantic_validation(valid_config: dict[str, Any]) -> None:
    inventory = valid_config["inventory"]
    inventory["root_group"] = {"id": 1, "full_path": "engineering"}
    inventory["groups"] = [
        {"id": 1, "full_path": "engineering", "wiki": False},
        {"id": 2, "full_path": "engineering/team", "wiki": True},
    ]
    inventory["projects"] = [
        {
            "id": 10,
            "full_path": "engineering/team/project",
            "repository": True,
            "wiki": False,
            "work_items": True,
        }
    ]
    config_module._validate_semantics(valid_config)


def test_shared_project_may_be_outside_root(valid_config: dict[str, Any]) -> None:
    config = _inventory_config(valid_config)
    config["sync"]["include_shared_projects"] = True
    config["inventory"]["projects"][0]["full_path"] = "external/shared"
    config_module._validate_semantics(config)


def _assert_semantic_error(
    valid_config: dict[str, Any], mutate: Any, message: str
) -> None:
    candidate = deepcopy(valid_config)
    mutate(candidate)
    with pytest.raises(ConfigurationError, match=message):
        config_module._validate_semantics(candidate)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda c: c.update(extra={}), "unknown top-level"),
        (lambda c: c["sync"].update(typo=1), "unknown setting in sync"),
        (lambda c: c["gitlab"].update(url="https://user:pass@example.test"), "HTTP"),
        (lambda c: c["gitlab"].update(group="../other"), "full path"),
        (lambda c: c["gitlab"].update(group=0), "positive"),
        (lambda c: c["gitlab"].update(token_file="/tmp/token"), "exactly one"),
        (lambda c: c["gitlab"].update(token_env="INVALID-NAME"), "variable name"),
        (
            lambda c: c["gitlab"].update(token_env=None, token_file="   "),
            "must not be blank",
        ),
        (lambda c: c["storage"].update(destination="relative"), "absolute path"),
        (lambda c: c["inventory"].update(groups=[{}]), "require.*root_group"),
    ],
)
def test_top_level_semantic_errors(
    valid_config: dict[str, Any], mutate: Any, message: str
) -> None:
    _assert_semantic_error(valid_config, mutate, message)


def _inventory_config(valid_config: dict[str, Any]) -> dict[str, Any]:
    config = deepcopy(valid_config)
    config["inventory"] = {
        "root_group": {"id": 1, "full_path": "root"},
        "groups": [{"id": 1, "full_path": "root", "wiki": False}],
        "projects": [
            {
                "id": 2,
                "full_path": "root/project",
                "repository": False,
                "wiki": False,
                "work_items": False,
            }
        ],
    }
    return config


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda i: i["root_group"].pop("full_path"), "missing or unknown"),
        (lambda i: i["root_group"].update(id=True), "IDs must be positive"),
        (lambda i: i["root_group"].update(full_path="root//child"), "full_path"),
        (lambda i: i["groups"].append(dict(i["groups"][0])), "duplicate ID"),
        (
            lambda i: i["groups"].append({"id": 3, "full_path": "root", "wiki": False}),
            "duplicate path",
        ),
        (lambda i: i["groups"][0].update(id=3), "matching root"),
        (
            lambda i: i["groups"].append(
                {"id": 3, "full_path": "outside", "wiki": False}
            ),
            "group is outside",
        ),
        (
            lambda i: i["projects"][0].update(full_path="outside/project"),
            "project is outside",
        ),
    ],
)
def test_inventory_semantic_errors(
    valid_config: dict[str, Any], mutate: Any, message: str
) -> None:
    config = _inventory_config(valid_config)
    mutate(config["inventory"])
    with pytest.raises(ConfigurationError, match=message):
        config_module._validate_semantics(config)


def test_token_from_environment(
    valid_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "  secret-from-env  ")
    assert config_module.load_token(valid_config) == "secret-from-env"
    monkeypatch.delenv("GITLAB_TOKEN")
    with pytest.raises(ConfigurationError, match="unset or empty"):
        config_module.load_token(valid_config)


def test_token_from_protected_file(
    valid_config: dict[str, Any], tmp_path: Path
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(" file-secret\n", encoding="utf-8")
    token_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    valid_config["gitlab"].update(token_env=None, token_file=str(token_file))
    assert config_module.load_token(valid_config) == "file-secret"

    token_file.chmod(stat.S_IRUSR | stat.S_IRGRP)
    with pytest.raises(ConfigurationError, match="only by its owner"):
        config_module.load_token(valid_config)


def test_token_file_read_errors(valid_config: dict[str, Any], tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    valid_config["gitlab"].update(token_env=None, token_file=str(token_file))
    with pytest.raises(ConfigurationError, match="cannot be read"):
        config_module.load_token(valid_config)

    token_file.write_text("  \n", encoding="utf-8")
    token_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with pytest.raises(ConfigurationError, match="is empty"):
        config_module.load_token(valid_config)


def test_config_manager_io_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenManager:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            raise OSError("sensitive path detail")

    monkeypatch.setattr(config_module, "ConfigManager", BrokenManager)
    with pytest.raises(ConfigurationError, match="could not load configuration YAML"):
        config_module._new_manager()


def test_template_writer_uses_one_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    managers: list[object] = []

    class FakeManager:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            managers.append(self)

        def generate_config_example(self, output: io.StringIO) -> None:
            output.write("generated\n")

    monkeypatch.setattr(config_module, "ConfigManager", FakeManager)
    output = io.StringIO()
    config_module.write_config_template(output)
    assert output.getvalue() == "generated\n"
    assert len(managers) == 1
