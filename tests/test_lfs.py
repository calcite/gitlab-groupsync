"""Opt-in LFS discovery, configuration, and real payload transfer contracts."""

import base64
import hashlib
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from click.testing import CliRunner
from ruamel.yaml import YAML

from gitlab_groupsync import cli
from gitlab_groupsync.config import ConfigurationError, load_config
from gitlab_groupsync.discovery import refresh_catalog
from gitlab_groupsync.git_sync import (
    GitOutput,
    GitResourceSynchronizer,
    GitRunner,
    GitSyncError,
    LocalConflictError,
)
from gitlab_groupsync.gitlab_api import (
    DiscoveryError,
    GitLabClient,
    Inventory,
    InventoryObject,
)


def _catalog() -> Inventory:
    root = InventoryObject(1, "root")
    return Inventory(
        root,
        (root,),
        tuple(InventoryObject(i, f"root/p{i}") for i in range(2, 7)),
        True,
    )


def _document() -> dict[str, Any]:
    return {
        "inventory": {
            "root_group": {"id": 1, "full_path": "root"},
            "groups": [{"id": 1, "full_path": "root", "wiki": False}],
            "projects": [
                {
                    "id": i,
                    "full_path": f"root/old{i}",
                    "repository": True,
                    "wiki": False,
                    "work_items": False,
                    **({"lfs": True} if i in (2, 3, 4) else {}),
                }
                for i in range(2, 6)
            ],
        }
    }


def _write_yaml(path: Path, value: Any) -> None:
    with path.open("w") as output:
        YAML().dump(value, output)


def test_catalog_lfs_evidence_preserves_intent_and_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_yaml(path, _document())
    refresh_catalog(path, _catalog(), lfs_objects={2: True, 3: False, 4: None, 6: True})
    projects = YAML(typ="safe").load(path)["inventory"]["projects"]
    assert [(p["id"], p.get("lfs")) for p in projects] == [
        (2, True),
        (3, None),
        (4, True),
        (5, None),
        (6, False),
    ]
    assert projects[0]["full_path"] == "root/p2"
    assert projects[-1]["repository"] is False
    assert load_config(str(path), [])["inventory"]["projects"][0]["lfs"] is True
    # Absence followed by reappearance loses the old selection.
    refresh_catalog(path, Inventory(_catalog().root_group, _catalog().groups, (), True))
    refresh_catalog(path, _catalog(), lfs_objects={2: True})
    assert YAML(typ="safe").load(path)["inventory"]["projects"][0]["lfs"] is False


@pytest.mark.parametrize("lfs", [None, False, True, "yes", 1])
def test_optional_lfs_config_validation(tmp_path: Path, lfs: Any) -> None:
    document = _document()
    project = document["inventory"]["projects"][0]
    project.pop("lfs")
    if lfs is not None:
        project["lfs"] = lfs
    path = tmp_path / "config.yaml"
    _write_yaml(path, document)
    if isinstance(lfs, str) or type(lfs) is int:
        with pytest.raises(ConfigurationError):
            load_config(str(path), [])
    else:
        assert load_config(str(path), [])["inventory"]["projects"][0].get(
            "lfs", False
        ) == bool(lfs)
    project.update(lfs=True, repository=False)
    _write_yaml(path, document)
    with pytest.raises(ConfigurationError, match="requires repository:true"):
        load_config(str(path), [])


@pytest.mark.parametrize(
    ("statistics", "expected"),
    [
        (None, None),
        ({}, None),
        ({"lfs_objects_size": 0}, False),
        ({"lfs_objects_size": 42}, True),
    ],
)
def test_project_lfs_statistics(statistics: Any, expected: bool | None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["statistics"] == "true"
        return httpx.Response(
            200,
            json={
                "id": 2,
                "path_with_namespace": "root/p2",
                "lfs_enabled": True,
                "statistics": statistics,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = GitLabClient(
            "https://git.example", "token", timeout=1, max_attempts=1, client=http
        )
        assert client.project_lfs_objects(2) is expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": 3},
        {"statistics": []},
        {"statistics": {"lfs_objects_size": -1}},
        {"statistics": {"lfs_objects_size": True}},
        {"statistics": {"lfs_objects_size": "42"}},
    ],
)
def test_invalid_project_lfs_statistics_are_not_authoritative(overrides: Any) -> None:
    value = {"id": 2, "path_with_namespace": "root/p2", **overrides}
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=value))
    ) as http:
        client = GitLabClient(
            "https://git.example", "token", timeout=1, max_attempts=1, client=http
        )
        with pytest.raises(DiscoveryError, match="project LFS statistics"):
            client.project_lfs_objects(2)


def test_discover_unknown_statistics_and_failure_atomicity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Client:
        fail = False

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def project_lfs_objects(self, project_id: int) -> bool | None:
            if self.fail and project_id == 4:
                raise DiscoveryError("GitLab returned HTTP 503 for projects/4")
            return None

    client = Client()
    monkeypatch.setattr(cli, "GitLabClient", lambda *a, **k: client)
    monkeypatch.setattr(cli, "discover_inventory", lambda *a, **k: _catalog())
    path = tmp_path / "config.yaml"
    _write_yaml(path, _document())
    args = ["discover", "--config", str(path)]
    result = CliRunner().invoke(cli.main, args, env={"GITLAB_TOKEN": "secret"})
    assert result.exit_code == 0, result.output
    assert "LFS availability unknown for root/p2" in result.output
    assert YAML(typ="safe").load(path)["inventory"]["projects"][0]["lfs"] is True
    before = path.read_bytes()
    client.fail = True
    result = CliRunner().invoke(cli.main, args, env={"GITLAB_TOKEN": "secret"})
    assert result.exit_code == 2
    assert path.read_bytes() == before


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True, capture_output=True
    ).stdout.strip()


@pytest.fixture
def lfs_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    if shutil.which("git-lfs") is None:
        pytest.fail("git-lfs is required for LFS integration tests")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    _git("init", "--bare", str(remote))
    _git("init", str(work))
    _git("config", "user.name", "Test", cwd=work)
    _git("config", "user.email", "test@example.test", cwd=work)
    _git("lfs", "install", "--local", cwd=work)
    _git("lfs", "track", "*.bin", cwd=work)
    (work / "asset.bin").write_bytes(b"current payload\x00")
    _git("add", ".", cwd=work)
    _git("commit", "-m", "LFS file", cwd=work)
    _git("branch", "-M", "main", cwd=work)
    _git("remote", "add", "origin", str(remote), cwd=work)
    _git("push", "-u", "origin", "main", cwd=work)
    return remote, work


def _object(root: Path, payload: bytes) -> Path:
    oid = hashlib.sha256(payload).hexdigest()
    return root / oid[:2] / oid[2:4] / oid


def test_lfs_opt_in_at_unchanged_commit_and_local_conflicts(
    tmp_path: Path, lfs_remote: tuple[Path, Path]
) -> None:
    remote, _ = lfs_remote
    target = tmp_path / "checkout"
    sync = GitResourceSynchronizer(GitRunner(15), tmp_path / "staging")
    initial = sync.sync(target, str(remote), "main", "project:2:repository")
    assert (
        (target / "asset.bin")
        .read_text()
        .startswith("version https://git-lfs.github.com/spec/v1")
    )
    assert not list((target / ".git/lfs/objects").glob("*/*/*"))
    hydrated = sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert hydrated.revision == initial.revision
    assert (target / "asset.bin").read_bytes() == b"current payload\x00"
    assert _git("status", "--porcelain", cwd=target) == ""
    assert (
        sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
        == hydrated
    )
    (target / "asset.bin").write_bytes(b"local edit")
    with pytest.raises(LocalConflictError):
        sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert (target / "asset.bin").read_bytes() == b"local edit"


def test_lfs_first_publication_incremental_exact_scope_and_disable(
    tmp_path: Path, lfs_remote: tuple[Path, Path]
) -> None:
    remote, work = lfs_remote
    # A historical-only object and another branch must not be fetched.
    (work / "old.bin").write_bytes(b"history only")
    _git("add", ".", cwd=work)
    _git("commit", "-m", "old file", cwd=work)
    (work / "old.bin").unlink()
    _git("add", "-A", cwd=work)
    _git("commit", "-m", "remove old file", cwd=work)
    _git("push", cwd=work)
    _git("checkout", "-b", "other", cwd=work)
    (work / "other.bin").write_bytes(b"other branch")
    _git("add", ".", cwd=work)
    _git("commit", "-m", "other", cwd=work)
    _git("push", "origin", "other", cwd=work)
    _git("checkout", "main", cwd=work)
    target = tmp_path / "checkout"
    sync = GitResourceSynchronizer(GitRunner(15), tmp_path / "staging")
    sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    objects = target / ".git/lfs/objects"
    assert _object(objects, b"current payload\x00").exists()
    assert not _object(objects, b"history only").exists()
    assert not _object(objects, b"other branch").exists()
    _git("config", "lfs.fetchrecentalways", "true", cwd=target)
    _git("config", "lfs.fetchrecentcommitsdays", "7", cwd=target)
    _git("config", "lfs.fetchinclude", "does-not-match", cwd=target)
    _git("config", "lfs.fetchexclude", "*", cwd=target)
    (work / "asset.bin").write_bytes(b"next payload")
    _git("add", ".", cwd=work)
    _git("commit", "-m", "update asset", cwd=work)
    _git("push", cwd=work)
    sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert (target / "asset.bin").read_bytes() == b"next payload"
    assert not _object(objects, b"history only").exists()
    (work / "asset.bin").write_bytes(b"disabled payload")
    _git("add", ".", cwd=work)
    _git("commit", "-m", "disabled update", cwd=work)
    _git("push", cwd=work)
    sync.sync(target, str(remote), "main", "project:2:repository")
    assert (
        (target / "asset.bin")
        .read_text()
        .startswith("version https://git-lfs.github.com/spec/v1")
    )
    assert not _object(objects, b"disabled payload").exists()
    assert _object(objects, b"next payload").exists()


def test_lfs_checkout_silent_skip_is_not_published(
    tmp_path: Path, lfs_remote: tuple[Path, Path]
) -> None:
    class LostObjectRunner(GitRunner):
        lose_object = True

        def run(self, args: list[str], **kwargs: Any) -> GitOutput:
            if args[-2:] == ["lfs", "checkout"] and self.lose_object:
                for path in (Path(args[1]) / ".git/lfs/objects").glob("*/*/*"):
                    path.unlink()
            return super().run(args, **kwargs)

    remote, _ = lfs_remote
    runner = LostObjectRunner(15)
    sync = GitResourceSynchronizer(runner, tmp_path / "staging")
    target = tmp_path / "checkout"
    with pytest.raises(GitSyncError, match="unmaterialized files"):
        sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert not target.exists()
    runner.lose_object = False
    sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert (target / "asset.bin").read_bytes() == b"current payload\x00"


def test_missing_lfs_object_preserves_previous_tree_and_retries(
    tmp_path: Path, lfs_remote: tuple[Path, Path]
) -> None:
    remote, work = lfs_remote
    payload = b"current payload\x00"
    source = _object(remote / "lfs/objects", payload)
    saved = source.read_bytes()
    source.unlink()
    target = tmp_path / "checkout"
    sync = GitResourceSynchronizer(GitRunner(15), tmp_path / "staging")
    with pytest.raises(GitSyncError):
        sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert not target.exists()
    assert list((tmp_path / "staging").iterdir()) == []
    source.write_bytes(saved)
    previous = sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    (work / "asset.bin").write_bytes(b"missing next payload")
    _git("add", ".", cwd=work)
    _git("commit", "-m", "next", cwd=work)
    _git("push", cwd=work)
    next_source = _object(remote / "lfs/objects", b"missing next payload")
    next_source.unlink()
    with pytest.raises(GitSyncError):
        sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert _git("rev-parse", "HEAD", cwd=target) == previous.revision
    assert (target / "asset.bin").read_bytes() == payload
    _git("lfs", "push", "--all", "origin", cwd=work)
    sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert (target / "asset.bin").read_bytes() == b"missing next payload"


def test_missing_lfs_executable_is_an_isolated_git_error(
    tmp_path: Path, lfs_remote: tuple[Path, Path]
) -> None:
    class MissingLfsRunner(GitRunner):
        def run(self, args: list[str], **kwargs: Any) -> GitOutput:
            if "lfs" in args:
                raise GitSyncError("git: lfs unavailable")
            return super().run(args, **kwargs)

    remote, _ = lfs_remote
    sync = GitResourceSynchronizer(MissingLfsRunner(15), tmp_path / "staging")
    target = tmp_path / "checkout"
    sync.sync(target, str(remote), "main", "project:2:repository")
    before = (target / "asset.bin").read_bytes()
    with pytest.raises(GitSyncError, match="lfs unavailable"):
        sync.sync(target, str(remote), "main", "project:2:repository", lfs=True)
    assert (target / "asset.bin").read_bytes() == before


def test_real_lfs_http_askpass_authentication_redaction_and_retry(
    tmp_path: Path, lfs_remote: tuple[Path, Path]
) -> None:
    payload = b"current payload\x00"
    token = "private-lfs-test-token"
    authorization = "Basic " + base64.b64encode(f"oauth2:{token}".encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        fail = True
        authenticated = False
        downloaded = False

        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.headers.get("Authorization") != authorization:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="LFS"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            Handler.authenticated = True
            oid = hashlib.sha256(payload).hexdigest()
            body = json.dumps(
                {"message": f"{token}: denied"}
                if self.fail
                else {
                    "objects": [
                        {
                            "oid": oid,
                            "size": len(payload),
                            "actions": {
                                "download": {
                                    "href": f"http://127.0.0.1:{self.server.server_port}/objects/{oid}",
                                }
                            },
                        }
                    ],
                }
            ).encode()
            self.send_response(403 if self.fail else 200)
            self.send_header("Content-Type", "application/vnd.git-lfs+json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            Handler.downloaded = True
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            pass

    remote, _ = lfs_remote
    target = tmp_path / "checkout"
    sync = GitResourceSynchronizer(GitRunner(15), tmp_path / "staging")
    sync.sync(target, str(remote), "main", "project:2:repository")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        _git(
            "config",
            "lfs.url",
            f"http://127.0.0.1:{server.server_port}/lfs",
            cwd=target,
        )
        with pytest.raises(GitSyncError) as failure:
            sync.sync(
                target,
                str(remote),
                "main",
                "project:2:repository",
                lfs=True,
                token=token,
            )
        assert token not in str(failure.value)
        assert "[REDACTED]" in str(failure.value)
        assert Handler.authenticated
        Handler.fail = False
        sync.sync(
            target, str(remote), "main", "project:2:repository", lfs=True, token=token
        )
        assert Handler.downloaded
        assert (target / "asset.bin").read_bytes() == payload
        assert token not in (target / ".git/config").read_text()
        assert _git("remote", "get-url", "origin", cwd=target) == str(remote)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
