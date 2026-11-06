"""Command-line interface for GitLab Groupsync."""

from collections.abc import Mapping
from typing import Any, TextIO

import click

from gitlab_groupsync.config import (
    ConfigurationError,
    load_config,
    load_token,
    write_config_template,
)
from gitlab_groupsync.diagnostics import render_doctor, render_status, run_doctor
from gitlab_groupsync.discovery import refresh_catalog
from gitlab_groupsync.gitlab_api import (
    DiscoveryError,
    GitLabClient,
    discover_inventory,
)
from gitlab_groupsync.orchestrator import SyncSetupError, run_sync
from gitlab_groupsync.state import (
    LockContentionError,
    StateError,
    local_status,
)

COMMAND_CONTEXT = {
    "ignore_unknown_options": True,
    "allow_extra_args": True,
}


def _config_option(*, required: bool = False):
    return click.option(
        "--config",
        type=click.Path(exists=True, dir_okay=False, path_type=str),
        required=required,
        help="YAML configuration layered on top of bundled defaults.",
    )


def _load_config_or_usage(
    config_path: str | None, cli_args: list[str]
) -> Mapping[str, Any]:
    try:
        return load_config(config_path, cli_args)
    except ConfigurationError as exc:
        raise click.UsageError(f"Invalid configuration: {exc}") from exc


def _load_token_or_usage(config: Mapping[str, Any]) -> str:
    try:
        return load_token(config)
    except ConfigurationError as exc:
        raise click.UsageError(f"Invalid configuration: {exc}") from exc


class DiscoveryClickError(click.ClickException):
    """A fatal discovery failure using the specified setup/discovery exit code."""

    exit_code = 2


class LockClickError(click.ClickException):
    """Destination lock contention using the specified operational exit code."""

    exit_code = 3


@click.group()
@click.version_option(package_name="gitlab-groupsync", prog_name="gl-groupsync")
def main() -> None:
    """Maintain a selected local reference copy of a GitLab group."""


@main.command("config-template")
@click.option(
    "--output",
    type=click.File("w"),
    required=True,
    help="Write the schema-free YAML template to this file.",
)
def config_template(output: TextIO) -> None:
    """Write an editable YAML configuration template."""
    write_config_template(output)


@main.command(context_settings=COMMAND_CONTEXT)
@_config_option(required=True)
@click.option(
    "--replace-root",
    is_flag=True,
    help="Approve replacing an inventory whose stable root group ID changed.",
)
@click.pass_context
def discover(ctx: click.Context, config: str, replace_root: bool) -> None:
    """Refresh the generated inventory in CONFIG."""
    resolved = _load_config_or_usage(config, ctx.args)
    token = _load_token_or_usage(resolved)
    gitlab = resolved["gitlab"]
    sync_config = resolved["sync"]
    try:
        with GitLabClient(
            gitlab["url"],
            token,
            timeout=sync_config["api_timeout_seconds"],
            max_attempts=sync_config["max_attempts"],
            ca_bundle=gitlab["ca_bundle"],
        ) as client:
            inventory = discover_inventory(
                client,
                gitlab["group"],
                include_shared=sync_config["include_shared_projects"],
                include_archived=sync_config["include_archived_projects"],
            )
            lfs_objects = {}
            for project in inventory.projects:
                lfs_objects[project.id] = client.project_lfs_objects(project.id)
                if lfs_objects[project.id] is None:
                    click.echo(
                        f"LFS availability unknown for {project.full_path} "
                        "(project statistics unavailable); preserving any existing "
                        "LFS selection.",
                        err=True,
                    )
        refresh_catalog(
            config, inventory, replace_root=replace_root, lfs_objects=lfs_objects
        )
    except DiscoveryError as exc:
        raise DiscoveryClickError(f"Discovery failed: {exc}") from exc
    click.echo(
        f"Discovered {len(inventory.groups)} groups and "
        f"{len(inventory.projects)} projects; refreshed {config}"
    )


@main.command(context_settings=COMMAND_CONTEXT)
@_config_option()
@click.option("--full", is_flag=True, help="Force a full reconciliation pass.")
@click.pass_context
def sync(ctx: click.Context, config: str | None, full: bool) -> None:
    """Synchronize selected GitLab resources once."""
    resolved = _load_config_or_usage(config, ctx.args)
    token = _load_token_or_usage(resolved)
    try:
        exit_code = run_sync(resolved, token, report=click.echo, full=full)
    except LockContentionError as exc:
        raise LockClickError(str(exc)) from exc
    except SyncSetupError as exc:
        raise DiscoveryClickError(f"Synchronization failed: {exc}") from exc
    if exit_code:
        raise click.exceptions.Exit(exit_code)


@main.command(context_settings=COMMAND_CONTEXT)
@_config_option()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def status(ctx: click.Context, config: str | None, as_json: bool) -> None:
    """Report local synchronization status without contacting GitLab."""
    resolved = _load_config_or_usage(config, ctx.args)
    try:
        report = local_status(resolved["storage"]["destination"])
    except StateError as exc:
        raise DiscoveryClickError(f"Could not read status: {exc}") from exc
    click.echo(render_status(report, as_json=as_json))


@main.command(context_settings=COMMAND_CONTEXT)
@_config_option()
@click.pass_context
def doctor(ctx: click.Context, config: str | None) -> None:
    """Validate setup and GitLab connectivity without changing content."""
    resolved = _load_config_or_usage(config, ctx.args)
    token = _load_token_or_usage(resolved)
    report = run_doctor(resolved, token)
    click.echo(render_doctor(report))
    if not report.healthy:
        raise click.exceptions.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
