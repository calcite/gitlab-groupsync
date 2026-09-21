"""Real-repository tests for the safe Git subprocess and resource adapter."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from gitlab_groupsync.git_sync import (
    GitOutput,
    GitResourceSynchronizer,
    GitRunner,
    GitSyncError,
    LocalConflictError,
    PathSafetyError,
    credential_free_remote,
    project_path,
    wiki_remote,
)


def _run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True, capture_output=True
    ).stdout.strip()


def _remote(tmp_path: Path, branch: str = "main") -> tuple[Path, Path]:
    remote = tmp_path / f"{branch}.git"
    work = tmp_path / f"{branch}-work"
    _run("init", "--bare", str(remote))
    _run("init", str(work))
    _run("config", "user.email", "test@example.test", cwd=work)
    _run("config", "user.name", "Test", cwd=work)
    (work / "kept.txt").write_text("one\n")
    (work / "deleted.txt").write_text("delete me\n")
    _run("add", ".", cwd=work)
    _run("commit", "-m", "first", cwd=work)
    _run("branch", "-M", branch, cwd=work)
    _run("remote", "add", "origin", str(remote), cwd=work)
    _run("push", "-u", "origin", branch, cwd=work)
    _run("symbolic-ref", "HEAD", f"refs/heads/{branch}", cwd=remote)
    return remote, work


def test_real_initial_incremental_noop_delete_rename_and_force_push(
    tmp_path: Path,
) -> None:
    remote, work = _remote(tmp_path)
    syncer = GitResourceSynchronizer(GitRunner(5), tmp_path / "staging")
    checkout = tmp_path / "content/repository"

    first = syncer.sync(checkout, str(remote), "main", "project:1:repository")
    assert first.revision == _run("rev-parse", "HEAD", cwd=work)
    assert (checkout / "kept.txt").read_text() == "one\n"
    first_mtime = (checkout / "kept.txt").stat().st_mtime_ns
    unchanged = syncer.sync(checkout, str(remote), "main", "project:1:repository")
    assert unchanged.revision == first.revision
    assert (checkout / "kept.txt").stat().st_mtime_ns == first_mtime

    (work / "kept.txt").write_text("two\n")
    (work / "deleted.txt").unlink()
    _run("add", "-A", cwd=work)
    _run("commit", "-m", "second", cwd=work)
    _run("push", cwd=work)
    changed = syncer.sync(checkout, str(remote), "main", "project:1:repository")
    assert changed.revision == _run("rev-parse", "HEAD", cwd=work)
    assert (checkout / "kept.txt").read_text() == "two\n"
    assert not (checkout / "deleted.txt").exists()

    _run("branch", "-m", "trunk", cwd=work)
    _run("push", "origin", "trunk", cwd=work)
    _run("symbolic-ref", "HEAD", "refs/heads/trunk", cwd=remote)
    renamed = syncer.sync(checkout, str(remote), "trunk", "project:1:repository")
    assert renamed.branch == "trunk"

    _run("reset", "--hard", "HEAD~1", cwd=work)
    (work / "kept.txt").write_text("rewritten\n")
    _run("add", ".", cwd=work)
    _run("commit", "-m", "rewritten", cwd=work)
    _run("push", "--force", "origin", "trunk", cwd=work)
    forced = syncer.sync(checkout, str(remote), "trunk", "project:1:repository")
    assert forced.revision == _run("rev-parse", "HEAD", cwd=work)
    assert (checkout / "kept.txt").read_text() == "rewritten\n"
    assert _run("remote", "get-url", "origin", cwd=checkout) == str(remote)


def test_runner_scopes_safe_directory_for_different_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.geteuid() != 0:
        pytest.skip("changing repository ownership requires root")
    monkeypatch.delenv("SUDO_UID", raising=False)
    repository = tmp_path / "uid-mapped"
    _run("init", str(repository))
    for path in (repository, *repository.rglob("*")):
        os.chown(path, 1000, -1)

    runner = GitRunner(5)
    with pytest.raises(GitSyncError, match="dubious ownership"):
        runner.run(["-C", str(repository), "status"])
    output = runner.run(["-C", str(repository), "status"], safe_directory=repository)
    assert "On branch" in output.stdout


def test_remote_head_empty_wiki_branch_and_local_conflicts(tmp_path: Path) -> None:
    remote, _ = _remote(tmp_path, "wiki-home")
    syncer = GitResourceSynchronizer(GitRunner(5), tmp_path / "staging")
    head = syncer.remote_head(str(remote))
    assert head is not None and head[0] == "wiki-home"

    empty = tmp_path / "empty.git"
    _run("init", "--bare", str(empty))
    assert syncer.remote_head(str(empty)) is None

    checkout = tmp_path / "wiki"
    syncer.sync(checkout, str(remote), "wiki-home", "project:1:wiki")
    (checkout / "kept.txt").write_text("local")
    with pytest.raises(LocalConflictError):
        syncer.sync(checkout, str(remote), "wiki-home", "project:1:wiki")
    _run("checkout", "--", "kept.txt", cwd=checkout)
    (checkout / "untracked.txt").write_text("local")
    with pytest.raises(LocalConflictError):
        syncer.sync(checkout, str(remote), "wiki-home", "project:1:wiki")


def test_path_collision_containment_and_remote_validation(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    managed = project_path(destination, "root/team/app", 10)
    assert project_path(destination, "root/team/app", 10) == managed
    with pytest.raises(PathSafetyError, match="identity"):
        project_path(destination, "root/team/app", 11)
    with pytest.raises(PathSafetyError, match="unsafe"):
        project_path(destination, "root/../escape", 1)

    collision = destination / "content/projects/root/other"
    collision.mkdir()
    with pytest.raises(PathSafetyError, match="unmanaged"):
        project_path(destination, "root/other", 2)
    symlink = destination / "content/projects/link"
    symlink.symlink_to(tmp_path)
    with pytest.raises(PathSafetyError, match="unsafe"):
        project_path(destination, "link/project", 3)
    linked_destination = tmp_path / "linked-corpus"
    linked_destination.symlink_to(destination, target_is_directory=True)
    with pytest.raises(PathSafetyError, match="symlink"):
        project_path(linked_destination, "root/app", 10)
    file_destination = tmp_path / "file-corpus"
    file_destination.write_text("not a directory")
    with pytest.raises(PathSafetyError, match="directory"):
        project_path(file_destination, "root/app", 10)
    unsafe_root = tmp_path / "unsafe-root"
    unsafe_root.mkdir()
    (unsafe_root / "content").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PathSafetyError, match="symlink ancestor"):
        project_path(unsafe_root, "root/app", 10)

    assert (
        credential_free_remote("https://user:secret@git.example/root/app.git")
        == "https://git.example/root/app.git"
    )
    assert (
        wiki_remote("git@git.example:root/app.git")
        == "git@git.example:root/app.wiki.git"
    )
    with pytest.raises(GitSyncError, match="unsafe"):
        credential_free_remote("-bad")
    with pytest.raises(GitSyncError, match="end in"):
        wiki_remote("https://git.example/root/app")


def test_unmanaged_resource_staging_and_checkout_failures(tmp_path: Path) -> None:
    remote, work = _remote(tmp_path)
    syncer = GitResourceSynchronizer(GitRunner(5), tmp_path / "staging")
    destination = tmp_path / "repository"
    destination.mkdir()
    with pytest.raises(PathSafetyError, match="unmanaged"):
        syncer.sync(destination, str(remote), "main", "project:1:repository")

    class FailingRunner:
        calls = 0

        def run(self, args: list[str], **kwargs: object) -> object:
            del args, kwargs
            self.calls += 1
            raise GitSyncError("injected")

    staging = tmp_path / "failed-staging"
    failing = GitResourceSynchronizer(FailingRunner(), staging)  # type: ignore[arg-type]
    target = tmp_path / "never-published"
    with pytest.raises(GitSyncError, match="injected"):
        failing.sync(target, str(remote), "main", "project:1:repository")
    assert not target.exists()
    assert list(staging.iterdir()) == []

    checkout = tmp_path / "checkout-failure"
    syncer.sync(checkout, str(remote), "main", "project:2:repository")
    (work / "kept.txt").write_text("next\n")
    _run("add", ".", cwd=work)
    _run("commit", "-m", "next", cwd=work)
    _run("push", cwd=work)

    class CheckoutFailRunner:
        def __init__(self) -> None:
            self.real = GitRunner(5)

        def run(self, args: list[str], **kwargs: object) -> GitOutput:
            if "checkout" in args:
                raise GitSyncError("checkout injected")
            return self.real.run(args, **kwargs)  # type: ignore[arg-type]

    broken = GitResourceSynchronizer(
        CheckoutFailRunner(),
        tmp_path / "staging-2",  # type: ignore[arg-type]
    )
    with pytest.raises(GitSyncError, match="inconsistent"):
        broken.sync(checkout, str(remote), "main", "project:2:repository")


def test_staging_publish_race_marker_mismatch_and_bad_remote_head(
    tmp_path: Path,
) -> None:
    remote, _ = _remote(tmp_path)
    real = GitRunner(5)
    target = tmp_path / "race"

    class RaceRunner:
        def run(self, args: list[str], **kwargs: object) -> GitOutput:
            result = real.run(args, **kwargs)  # type: ignore[arg-type]
            if "checkout" in args:
                target.mkdir()
            return result

    syncer = GitResourceSynchronizer(
        RaceRunner(),
        tmp_path / "staging",  # type: ignore[arg-type]
    )
    with pytest.raises(PathSafetyError, match="appeared"):
        syncer.sync(target, str(remote), "main", "project:1:repository")

    normal = GitResourceSynchronizer(real, tmp_path / "other-staging")
    checkout = tmp_path / "normal"
    normal.sync(checkout, str(remote), "main", "project:1:repository")
    (checkout / ".git/gitlab-groupsync").write_text("different\n")
    with pytest.raises(PathSafetyError, match="identity"):
        normal.sync(checkout, str(remote), "main", "project:1:repository")

    class HeadRunner:
        def run(self, args: list[str], **kwargs: object) -> GitOutput:
            del args, kwargs
            return GitOutput("abc\tHEAD\n", "")

    invalid_head = GitResourceSynchronizer(
        HeadRunner(),
        tmp_path / "unused",  # type: ignore[arg-type]
    )
    with pytest.raises(GitSyncError, match="default branch"):
        invalid_head.remote_head("remote")


def test_runner_timeout_kills_group_and_https_secret_is_redacted(
    tmp_path: Path,
) -> None:
    slow = tmp_path / "slow"
    pid_file = tmp_path / "child.pid"
    slow.write_text(f"#!/bin/sh\nsleep 30 & echo $! > {pid_file}\nwait\n")
    slow.chmod(0o700)
    with pytest.raises(GitSyncError, match="timed out"):
        GitRunner(0.1, executable=str(slow)).run(["version"])
    child_pid = int(pid_file.read_text())
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    else:
        pytest.fail("timed-out child process survived")

    inspect = tmp_path / "inspect"
    inspect.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\"\n"
        "printf '%s\\n' "
        '"$GIT_LFS_SKIP_SMUDGE|$GIT_TERMINAL_PROMPT|$GIT_SSH_COMMAND|'
        '$GIT_SSL_CAINFO"\n'
        '"$GIT_ASKPASS" Password\n'
    )
    inspect.chmod(0o700)
    output = GitRunner(2, executable=str(inspect), ca_bundle="/safe/ca.pem").run(
        ["fetch", "https://git.example/repo.git"],
        token="top-secret",
        safe_directory=tmp_path / "managed repository",
    )
    assert "top-secret" not in output.stdout
    assert "[REDACTED]" in output.stdout
    assert "1|0|ssh -o BatchMode=yes|/safe/ca.pem" in output.stdout
    assert f"safe.directory={tmp_path / 'managed repository'}" in output.stdout
    assert "top-secret" not in repr(output)
    with pytest.raises(GitSyncError, match="token-bearing Git arguments"):
        GitRunner(2, executable=str(inspect)).run(
            ["fetch", "https://git.example/top-secret/repo.git"],
            token="top-secret",
        )

    failed = tmp_path / "failed"
    failed.write_text(
        "#!/bin/sh\n"
        "printf 'server said %s\\n' \"$GL_GROUPSYNC_GIT_TOKEN\"\n"
        "printf 'authentication rejected %s\\n' "
        '"$GL_GROUPSYNC_GIT_TOKEN" >&2\n'
        "exit 4\n"
    )
    failed.chmod(0o700)
    with pytest.raises(GitSyncError) as failure:
        GitRunner(2, executable=str(failed)).run(
            ["-C", "/checkout", "fetch"],
            token="top-secret",
            resource_key="project:42:repository",
        )
    message = str(failure.value)
    assert "top-secret" not in message
    assert "project:42:repository: Git operation failed (fetch)" in message
    assert "stdout: server said [REDACTED]" in message
    assert "stderr: authentication rejected [REDACTED]" in message
    with pytest.raises(GitSyncError, match="execute"):
        GitRunner(2, executable=str(tmp_path / "missing")).run(["version"])

    stubborn = tmp_path / "stubborn"
    stubborn.write_text("#!/bin/sh\ntrap '' TERM\nwhile :; do sleep 1; done\n")
    stubborn.chmod(0o700)
    with pytest.raises(GitSyncError, match="timed out"):
        GitRunner(0.05, executable=str(stubborn)).run(["version"])


def test_project_marker_invalid_json(tmp_path: Path) -> None:
    target = tmp_path / "corpus/content/projects/root/app"
    target.mkdir(parents=True)
    (target / "project.json").write_text("[]")
    with pytest.raises(PathSafetyError, match="invalid"):
        project_path(tmp_path / "corpus", "root/app", 1)


def test_remote_url_validation_with_port() -> None:
    assert (
        credential_free_remote("ssh://user@git.example:2222/root/app.git")
        == "ssh://user@git.example:2222/root/app.git"
    )
    with pytest.raises(GitSyncError, match="unsafe"):
        credential_free_remote("ftp://git.example/root/app.git")


def test_sync_rejects_symlinked_staging_root(tmp_path: Path) -> None:
    staging = tmp_path / "container/.sync/staging"
    staging.parent.mkdir(parents=True)
    staging.symlink_to(tmp_path, target_is_directory=True)
    syncer = GitResourceSynchronizer(GitRunner(1), staging)
    with pytest.raises(PathSafetyError, match="staging"):
        syncer.sync(
            tmp_path / "container/content/repository",
            "https://git.example/root/app.git",
            "main",
            "project:1:repository",
        )
    with pytest.raises(GitSyncError, match="token-bearing Git remote"):
        syncer.sync(
            tmp_path / "container/content/repository",
            "https://git.example/secret/app.git",
            "main",
            "project:1:repository",
            token="secret",
        )
    with pytest.raises(GitSyncError, match="token-bearing Git remote"):
        syncer.remote_head("https://git.example/secret/app.git", token="secret")
