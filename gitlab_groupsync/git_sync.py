"""Safe, one-way synchronization of detached Git working trees."""

import os
import shutil
import signal
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from gitlab_groupsync.path_safety import (
    UnsafePathError,
    assert_no_symlinks,
    contained_path,
    fsync_directories,
)
from gitlab_groupsync.reconcile import ReconcileError, ensure_object_directory


class GitSyncError(Exception):
    """A redacted operational Git resource failure."""


class LocalConflictError(GitSyncError):
    """A managed checkout contains local tracked or untracked changes."""


class PathSafetyError(GitSyncError):
    """A destination path is unsafe or collides with unmanaged content."""


@dataclass(frozen=True)
class GitOutput:
    """Captured successful Git command output."""

    stdout: str
    stderr: str


@dataclass(frozen=True)
class GitResourceResult:
    """Result of synchronizing one independently managed Git resource."""

    status: str
    revision: str | None = None
    branch: str | None = None


class GitRunner:
    """Testable subprocess adapter with fixed noninteractive security controls."""

    def __init__(
        self,
        timeout: float,
        *,
        executable: str = "git",
        ca_bundle: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.executable = executable
        self.ca_bundle = ca_bundle

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        token: str | None = None,
        resource_key: str | None = None,
        safe_directory: Path | None = None,
    ) -> GitOutput:
        if token and any(token in value for value in args):
            raise GitSyncError("refusing token-bearing Git arguments")
        command = [
            self.executable,
            "-c",
            "submodule.recurse=false",
            "-c",
            "credential.helper=",
        ]
        if safe_directory is not None:
            command.extend(("-c", f"safe.directory={safe_directory.absolute()}"))
        command.extend(args)
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_LFS_SKIP_SMUDGE": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
            }
        )
        if self.ca_bundle:
            environment["GIT_SSL_CAINFO"] = self.ca_bundle
        askpass: Path | None = None
        if token is not None:
            descriptor, name = tempfile.mkstemp(prefix="gl-groupsync-askpass-")
            askpass = Path(name)
            try:
                script = (
                    b'#!/bin/sh\ncase "$1" in '
                    b'*Username*) printf "%s\\n" oauth2;; '
                    b'*) printf "%s\\n" "$GL_GROUPSYNC_GIT_TOKEN";; esac\n'
                )
                os.write(descriptor, script)
            finally:
                os.close(descriptor)
            askpass.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            environment["GIT_ASKPASS"] = str(askpass)
            environment["GL_GROUPSYNC_GIT_TOKEN"] = token
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                raise GitSyncError("Git operation timed out") from None
            if token:
                stdout = stdout.replace(token, "[REDACTED]")
                stderr = stderr.replace(token, "[REDACTED]")
            if process.returncode != 0:
                operation = (
                    args[2]
                    if len(args) > 2 and args[0] == "-C"
                    else args[0]
                    if args
                    else "command"
                )
                message = f"Git operation failed ({operation})"
                if resource_key:
                    message = f"{resource_key}: {message}"
                details = []
                if stdout.strip():
                    details.append(f"stdout: {stdout.strip()}")
                if stderr.strip():
                    details.append(f"stderr: {stderr.strip()}")
                if details:
                    message = f"{message}\n" + "\n".join(details)
                raise GitSyncError(message)
            return GitOutput(stdout, stderr)
        except OSError as exc:
            raise GitSyncError("could not execute Git") from exc
        finally:
            if askpass is not None:
                askpass.unlink(missing_ok=True)


def credential_free_remote(value: str) -> str:
    """Validate a clone URL and remove any accidental HTTP user information."""
    if "://" not in value:
        if value.startswith("-") or "\n" in value or "\r" in value:
            raise GitSyncError("GitLab returned an unsafe Git remote")
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "ssh"} or not parsed.hostname:
        raise GitSyncError("GitLab returned an unsafe Git remote")
    host = parsed.hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    if parsed.scheme == "ssh" and parsed.username:
        host = f"{parsed.username}@{host}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def wiki_remote(project_remote: str) -> str:
    """Derive GitLab's documented sibling project-wiki repository URL."""
    remote = credential_free_remote(project_remote)
    suffix = ".git"
    if not remote.endswith(suffix):
        raise GitSyncError("project clone URL does not end in .git")
    return f"{remote[: -len(suffix)]}.wiki.git"


def project_path(destination: Path, full_path: str, project_id: int) -> Path:
    """Create or validate a contained, non-symlink managed project directory."""
    try:
        return ensure_object_directory(destination, "project", full_path, project_id)
    except (ReconcileError, UnsafePathError) as exc:
        raise PathSafetyError(str(exc)) from exc


class GitResourceSynchronizer:
    """Synchronize one branch into a detached managed checkout."""

    def __init__(self, runner: GitRunner, staging_root: Path) -> None:
        self.runner = runner
        self.staging_root = staging_root

    def sync(
        self,
        destination: Path,
        remote: str,
        branch: str,
        resource_key: str,
        *,
        token: str | None = None,
    ) -> GitResourceResult:
        remote = credential_free_remote(remote)
        if token and token in remote:
            raise GitSyncError("refusing a token-bearing Git remote")
        try:
            assert_no_symlinks(destination, include_leaf=False)
            contained_path(
                self.staging_root.parent.parent,
                self.staging_root.relative_to(self.staging_root.parent.parent),
            )
        except (UnsafePathError, ValueError) as exc:
            raise PathSafetyError("unsafe Git resource or staging path") from exc
        marker_value = f"{resource_key}\n"
        if destination.exists():
            marker = destination / ".git" / "gitlab-groupsync"
            if (
                destination.is_symlink()
                or (destination / ".git").is_symlink()
                or marker.is_symlink()
                or not marker.is_file()
            ):
                raise PathSafetyError("destination collides with unmanaged resource")
            if marker.read_text(encoding="utf-8") != marker_value:
                raise PathSafetyError("managed resource identity does not match")
            status = self.runner.run(
                [
                    "-C",
                    str(destination),
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ],
                resource_key=resource_key,
                safe_directory=destination,
            )
            if status.stdout:
                raise LocalConflictError("local tracked or untracked changes detected")
            self.runner.run(
                ["-C", str(destination), "remote", "set-url", "origin", remote],
                resource_key=resource_key,
                safe_directory=destination,
            )
            self.runner.run(
                [
                    "-C",
                    str(destination),
                    "fetch",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "origin",
                    f"+refs/heads/{branch}:refs/remotes/origin/gl-groupsync",
                ],
                token=token,
                resource_key=resource_key,
                safe_directory=destination,
            )
            revision = self._revision(destination, resource_key)
            current = self.runner.run(
                ["-C", str(destination), "rev-parse", "--verify", "HEAD"],
                resource_key=resource_key,
                safe_directory=destination,
            )
            if current.stdout.strip() == revision:
                return GitResourceResult("ok", revision, branch)
            try:
                self.runner.run(
                    [
                        "-C",
                        str(destination),
                        "checkout",
                        "--detach",
                        "--force",
                        revision,
                    ],
                    resource_key=resource_key,
                    safe_directory=destination,
                )
            except GitSyncError as exc:
                raise GitSyncError(
                    f"{resource_key}: Git checkout failed; resource may be "
                    f"inconsistent: {exc}"
                ) from None
            return GitResourceResult("ok", revision, branch)

        self.staging_root.mkdir(parents=True, exist_ok=True)
        assert_no_symlinks(self.staging_root)
        staging = Path(tempfile.mkdtemp(prefix="git-", dir=self.staging_root))
        try:
            self.runner.run(["init", str(staging)], resource_key=resource_key)
            self.runner.run(
                ["-C", str(staging), "remote", "add", "origin", remote],
                resource_key=resource_key,
                safe_directory=staging,
            )
            self.runner.run(
                [
                    "-C",
                    str(staging),
                    "fetch",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "origin",
                    f"+refs/heads/{branch}:refs/remotes/origin/gl-groupsync",
                ],
                token=token,
                resource_key=resource_key,
                safe_directory=staging,
            )
            revision = self._revision(staging, resource_key)
            self.runner.run(
                ["-C", str(staging), "checkout", "--detach", revision],
                resource_key=resource_key,
                safe_directory=staging,
            )
            marker = staging / ".git" / "gitlab-groupsync"
            with marker.open("w", encoding="utf-8") as output:
                output.write(marker_value)
                output.flush()
                os.fsync(output.fileno())
            fsync_directories((marker.parent, staging, staging.parent))
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise PathSafetyError("resource appeared during staged publication")
            os.replace(staging, destination)
            fsync_directories((destination.parent,))
            return GitResourceResult("ok", revision, branch)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def remote_head(
        self,
        remote: str,
        *,
        token: str | None = None,
        resource_key: str | None = None,
    ) -> tuple[str, str] | None:
        """Resolve a remote's own HEAD branch and commit, or confirm it is empty."""
        remote = credential_free_remote(remote)
        if token and token in remote:
            raise GitSyncError("refusing a token-bearing Git remote")
        output = self.runner.run(
            ["ls-remote", "--symref", remote, "HEAD"],
            token=token,
            resource_key=resource_key,
        )
        if not output.stdout.strip():
            return None
        branch: str | None = None
        revision: str | None = None
        for line in output.stdout.splitlines():
            if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
                branch = line.removeprefix("ref: refs/heads/").removesuffix("\tHEAD")
            elif line.endswith("\tHEAD"):
                revision = line.split("\t", 1)[0]
        if not branch or not revision:
            raise GitSyncError("could not determine remote default branch")
        return branch, revision

    def _revision(self, checkout: Path, resource_key: str) -> str:
        return self.runner.run(
            ["-C", str(checkout), "rev-parse", "refs/remotes/origin/gl-groupsync"],
            resource_key=resource_key,
            safe_directory=checkout,
        ).stdout.strip()
