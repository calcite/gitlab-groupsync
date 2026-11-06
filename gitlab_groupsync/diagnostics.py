"""Local status rendering and read-only setup diagnostics."""

import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from gitlab_groupsync.gitlab_api import (
    DiscoveryError,
    GitLabClient,
    discover_inventory,
)


@dataclass(frozen=True)
class DiagnosticCheck:
    """One doctor observation with stable machine-readable fields."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    """Complete doctor result."""

    checks: tuple[DiagnosticCheck, ...]

    @property
    def healthy(self) -> bool:
        return all(check.ok for check in self.checks)


class DiagnosticClient(Protocol):
    """Read-only GitLab operations needed by doctor."""

    def __enter__(self) -> "DiagnosticClient": ...

    def __exit__(self, *args: object) -> None: ...

    def get_object(self, endpoint: str) -> Mapping[str, Any]: ...

    def get_optional_object(self, endpoint: str) -> Mapping[str, Any] | None: ...

    def probe(self, endpoint: str) -> int: ...

    def iter_list(
        self, endpoint: str, params: Mapping[str, str | int | bool]
    ) -> Any: ...


def render_status(status: Mapping[str, Any], *, as_json: bool) -> str:
    """Render the local status projection for humans or automation."""
    if as_json:
        return json.dumps(status, indent=2, sort_keys=True)
    if not status["initialized"]:
        state = "uninitialized"
        if status["current_run"]:
            state += " (destination lock held)"
        return f"Destination: {state}"

    identity = status["identity"]
    latest = status["latest_run"]
    if latest is None:
        run_text = "none"
    else:
        run_text = latest["outcome"]
        if latest["interrupted"]:
            run_text += " (interrupted)"
    resources = status["resources"]
    freshness = status["freshness"]
    drift = status["drift"]
    drift_counts = "none"
    if drift is not None:
        drift_counts = ", ".join(
            f"{name}={len(drift[name])}"
            for name in ("added", "absent", "renamed", "path_reused")
        )
    return "\n".join(
        (
            "Destination: initialized",
            f"Identity: {identity['instance_url']} root={identity['root_group_id']}",
            f"Run: {run_text}; active={str(status['current_run']).lower()}",
            f"Resources: {resources['total']}; "
            f"retained={resources['retained_content']}; "
            f"states={resources['by_status']}",
            f"Freshness: attempt={freshness['last_attempt_at'] or 'never'}; "
            f"success={freshness['last_success_at'] or 'never'}",
            f"Drift: {drift_counts}",
        )
    )


def run_doctor(
    config: Mapping[str, Any],
    token: str,
    *,
    client_factory: Callable[..., DiagnosticClient] = GitLabClient,
    git_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DoctorReport:
    """Check local and remote prerequisites without mutating configuration/content."""
    checks = [DiagnosticCheck("configuration", True, "valid")]
    try:
        result = git_runner(
            ["git", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        git_ok = result.returncode == 0 and result.stdout.startswith("git version ")
        detail = (
            result.stdout.strip() if git_ok else "Git executable/version unavailable"
        )
    except (OSError, subprocess.SubprocessError):
        git_ok, detail = False, "Git executable/version unavailable"
    checks.append(DiagnosticCheck("git", git_ok, detail))

    if any(project.get("lfs", False) for project in config["inventory"]["projects"]):
        try:
            result = git_runner(
                ["git", "lfs", "version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            lfs_ok = result.returncode == 0 and result.stdout.startswith("git-lfs/")
            detail = result.stdout.strip() if lfs_ok else "Git LFS unavailable"
        except (OSError, subprocess.SubprocessError):
            lfs_ok, detail = False, "Git LFS unavailable"
        checks.append(DiagnosticCheck("git_lfs", lfs_ok, detail))

    gitlab = config["gitlab"]
    if gitlab["git_transport"] == "ssh":
        try:
            result = git_runner(
                ["ssh", "-V"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            ssh_ok = result.returncode == 0
            version = (result.stderr or result.stdout).strip()
            detail = version if ssh_ok and version else "SSH executable unavailable"
        except (OSError, subprocess.SubprocessError):
            ssh_ok, detail = False, "SSH executable unavailable"
        checks.append(DiagnosticCheck("ssh", ssh_ok, detail))

    sync = config["sync"]
    try:
        client_context = client_factory(
            gitlab["url"],
            token,
            timeout=sync["api_timeout_seconds"],
            max_attempts=sync["max_attempts"],
            ca_bundle=gitlab["ca_bundle"],
        )
        with client_context as client:
            root_ref = quote(str(gitlab["group"]), safe="")
            root = client.get_object(f"groups/{root_ref}")
            checks.extend(
                (
                    DiagnosticCheck("tls", True, _tls_detail(gitlab)),
                    DiagnosticCheck("authentication", True, "token accepted"),
                    DiagnosticCheck(
                        "root_visibility", True, f"visible root ID {root.get('id')}"
                    ),
                )
            )
            metadata = client.get_optional_object("metadata")
            source = "metadata"
            if metadata is None:
                metadata = client.get_optional_object("version")
                source = "version"
            detail = (
                f"{source}: {metadata.get('version', 'available')}"
                if metadata is not None
                else "metadata/version endpoint unavailable"
            )
            checks.append(DiagnosticCheck("server_metadata", True, detail))
            live = discover_inventory(
                client,  # type: ignore[arg-type]
                gitlab["group"],
                include_shared=sync["include_shared_projects"],
                include_archived=sync["include_archived_projects"],
            )
            checks.append(
                DiagnosticCheck(
                    "discovery",
                    True,
                    f"{len(live.groups)} groups, {len(live.projects)} projects",
                )
            )
            checks.append(_check_capabilities(config, client, live))
    except DiscoveryError as exc:
        message = str(exc)
        reached_server = "HTTP " in message
        if not any(check.name == "tls" for check in checks):
            checks.append(
                DiagnosticCheck(
                    "tls",
                    reached_server,
                    _tls_detail(gitlab)
                    if reached_server
                    else _safe_remote_failure(message),
                )
            )
        if not any(check.name == "authentication" for check in checks):
            checks.append(
                DiagnosticCheck("authentication", False, _safe_remote_failure(message))
            )
        if not any(check.name == "root_visibility" for check in checks):
            checks.append(
                DiagnosticCheck("root_visibility", False, _safe_remote_failure(message))
            )
        if any(check.name == "root_visibility" and check.ok for check in checks):
            checks.append(
                DiagnosticCheck(
                    "remote_diagnostics", False, _safe_remote_failure(message)
                )
            )
    return DoctorReport(tuple(checks))


def _tls_detail(gitlab: Mapping[str, Any]) -> str:
    ca_bundle = gitlab["ca_bundle"]
    return (
        f"verified with custom CA {ca_bundle}" if ca_bundle else "verification enabled"
    )


def _safe_remote_failure(message: str) -> str:
    if "HTTP 401" in message:
        return "GitLab rejected authentication (HTTP 401)"
    if "HTTP 403" in message:
        return "GitLab denied access (HTTP 403)"
    return message


def _check_capabilities(
    config: Mapping[str, Any], client: DiagnosticClient, live: Any
) -> DiagnosticCheck:
    live_groups = {item.id for item in live.groups}
    live_projects = {item.id for item in live.projects}
    failures: list[str] = []
    probes = 0
    for group in config["inventory"]["groups"]:
        if group["wiki"]:
            probes += 1
            if group["id"] not in live_groups:
                failures.append(f"group {group['id']} is not visible")
            elif client.probe(f"groups/{group['id']}/wikis") != 200:
                failures.append(f"group wiki {group['id']} is unavailable")
    for project in config["inventory"]["projects"]:
        selected = any(project[name] for name in ("repository", "wiki", "work_items"))
        if selected and project["id"] not in live_projects:
            failures.append(f"project {project['id']} is not visible")
            continue
        for setting, endpoint in (
            ("wiki", "wikis"),
            ("work_items", "issues"),
        ):
            if project[setting]:
                probes += 1
                if client.probe(f"projects/{project['id']}/{endpoint}") != 200:
                    failures.append(
                        f"project {setting.replace('_', ' ')} "
                        f"{project['id']} is unavailable"
                    )
    if failures:
        return DiagnosticCheck("requested_capabilities", False, "; ".join(failures))
    return DiagnosticCheck(
        "requested_capabilities", True, f"{probes} selected API capabilities available"
    )


def render_doctor(report: DoctorReport) -> str:
    """Render all doctor checks without secret-bearing values."""
    lines = [
        f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}"
        for check in report.checks
    ]
    lines.append("Healthy" if report.healthy else "Partial failures detected")
    return "\n".join(lines)
