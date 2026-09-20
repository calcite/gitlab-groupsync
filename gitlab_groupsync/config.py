"""Configuration loading, validation, and credential resolution."""

import os
import re
import stat
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from onacol import (  # type: ignore[import-untyped]
    ConfigManager,
    ConfigValidationError,
    OnacolException,
)

ENV_PREFIX = "GL_GROUPSYNC_"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigurationError(Exception):
    """A safe, user-facing configuration error."""


def _new_manager(config_path: str | None = None) -> ConfigManager:
    default_config = resources.files("gitlab_groupsync").joinpath("default_config.yaml")
    try:
        with resources.as_file(default_config) as default_path:
            return ConfigManager(
                str(default_path),
                optional_files=[config_path] if config_path else [],
                env_var_prefix=ENV_PREFIX,
            )
    except (OSError, OnacolException) as exc:
        raise ConfigurationError("could not load configuration YAML") from exc


def write_config_template(output: TextIO) -> None:
    """Write defaults without Onacol schema metadata."""
    _new_manager().generate_config_example(output)


def load_config(config_path: str | None, cli_args: list[str]) -> Mapping[str, Any]:
    """Load every configuration layer and validate the merged result once."""
    manager = _new_manager(config_path)
    try:
        manager.config_from_env_vars()
        manager.config_from_cli_args(cli_args)
        manager.validate()
    except ConfigValidationError as exc:
        raise ConfigurationError(str(exc)) from exc
    except OnacolException as exc:
        raise ConfigurationError("invalid environment or CLI override") from exc

    config = manager.config
    _validate_semantics(config)
    return config


def _validate_semantics(config: Mapping[str, Any]) -> None:
    allowed = {
        "gitlab": {
            "url",
            "group",
            "token_env",
            "token_file",
            "git_transport",
            "ca_bundle",
        },
        "storage": {"destination"},
        "sync": {
            "include_shared_projects",
            "include_archived_projects",
            "workers",
            "api_timeout_seconds",
            "git_timeout_seconds",
            "max_attempts",
            "full_reconcile_hours",
            "incremental_overlap_seconds",
        },
        "inventory": {"root_group", "groups", "projects"},
    }
    unknown_sections = set(config) - set(allowed)
    if unknown_sections:
        raise ConfigurationError("unknown top-level configuration section")
    for section, keys in allowed.items():
        unknown = set(config[section]) - keys
        if unknown:
            raise ConfigurationError(f"unknown setting in {section}")

    gitlab = config["gitlab"]
    parsed_url = urlsplit(gitlab["url"])
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
        or parsed_url.username is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ConfigurationError("gitlab.url must be an HTTP(S) base URL")
    group = gitlab["group"]
    if isinstance(group, str) and (not group.strip() or not _valid_full_path(group)):
        raise ConfigurationError("gitlab.group must be a numeric ID or full path")
    if isinstance(group, int) and (isinstance(group, bool) or group < 1):
        raise ConfigurationError("gitlab.group numeric ID must be positive")

    token_env = gitlab["token_env"]
    token_file = gitlab["token_file"]
    if bool(token_env) == bool(token_file):
        raise ConfigurationError(
            "configure exactly one of gitlab.token_env or token_file"
        )
    if token_env and not _ENV_NAME.fullmatch(token_env):
        raise ConfigurationError(
            "gitlab.token_env must be an environment variable name"
        )
    if token_file and not str(token_file).strip():
        raise ConfigurationError("gitlab.token_file must not be blank")

    destination = Path(config["storage"]["destination"]).expanduser()
    if not destination.is_absolute():
        raise ConfigurationError("storage.destination must be an absolute path")

    inventory = config["inventory"]
    root = inventory["root_group"]
    groups = inventory["groups"]
    projects = inventory["projects"]
    if root is None:
        if groups or projects:
            raise ConfigurationError("inventory entries require inventory.root_group")
        return

    _validate_inventory_entry(root, "inventory.root_group", {"id", "full_path"})
    _validate_inventory_list(groups, "inventory.groups", {"id", "full_path", "wiki"})
    _validate_inventory_list(
        projects,
        "inventory.projects",
        {"id", "full_path", "repository", "wiki", "work_items"},
    )
    root_matches = [item for item in groups if item["id"] == root["id"]]
    if len(root_matches) != 1 or root_matches[0]["full_path"] != root["full_path"]:
        raise ConfigurationError(
            "inventory.groups must contain the matching root group"
        )
    root_path = root["full_path"]
    if any(not _is_within(path=item["full_path"], root=root_path) for item in groups):
        raise ConfigurationError("inventory group is outside the configured root")
    if not config["sync"]["include_shared_projects"] and any(
        not _is_within(path=item["full_path"], root=root_path) for item in projects
    ):
        raise ConfigurationError("inventory project is outside the configured root")


def _validate_inventory_list(
    entries: list[Mapping[str, Any]], label: str, allowed_keys: set[str]
) -> None:
    ids: set[int] = set()
    paths: set[str] = set()
    for entry in entries:
        _validate_inventory_entry(entry, label, allowed_keys)
        if entry["id"] in ids:
            raise ConfigurationError(f"{label} contains a duplicate ID")
        if entry["full_path"] in paths:
            raise ConfigurationError(f"{label} contains a duplicate path")
        ids.add(entry["id"])
        paths.add(entry["full_path"])


def _validate_inventory_entry(
    entry: Mapping[str, Any], label: str, allowed_keys: set[str]
) -> None:
    if set(entry) != allowed_keys:
        raise ConfigurationError(f"{label} entry has missing or unknown settings")
    if isinstance(entry["id"], bool) or entry["id"] < 1:
        raise ConfigurationError(f"{label} IDs must be positive")
    if not _valid_full_path(entry["full_path"]):
        raise ConfigurationError(f"{label} full_path is invalid")


def _valid_full_path(value: str) -> bool:
    return (
        bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and "\x00" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _is_within(*, path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")


def load_token(config: Mapping[str, Any]) -> str:
    """Resolve token material without adding it to the configuration object."""
    gitlab = config["gitlab"]
    env_name = gitlab["token_env"]
    if env_name:
        token = os.environ.get(env_name, "").strip()
        if not token:
            raise ConfigurationError(
                "configured token environment variable is unset or empty"
            )
        return token

    token_path = Path(gitlab["token_file"]).expanduser()
    try:
        file_stat = token_path.lstat()
        mode = file_stat.st_mode
        if (
            not stat.S_ISREG(mode)
            or file_stat.st_uid != os.getuid()
            or mode & (stat.S_IRWXG | stat.S_IRWXO)
        ):
            raise ConfigurationError(
                "token file must be regular and accessible only by its owner"
            )
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigurationError("token file cannot be read") from exc
    if not token:
        raise ConfigurationError("token file is empty")
    return token
