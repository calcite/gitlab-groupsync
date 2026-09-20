"""Durable state, locking, local status, and atomic publication tests."""

import errno
import json
import os
import sqlite3
import threading
from pathlib import Path

import pytest

from gitlab_groupsync import state
from gitlab_groupsync.gitlab_api import DriftObject, InventoryDiff
from gitlab_groupsync.state import (
    AtomicWriteError,
    DestinationLock,
    IdentityMismatchError,
    LockContentionError,
    StateError,
    StateStore,
    atomic_write_json,
    destination_is_locked,
    local_status,
    normalize_instance_url,
    write_manifest,
    write_resource_metadata,
)


def _drift() -> InventoryDiff:
    return InventoryDiff(
        (DriftObject("project", 2, None, "root/new"),),
        (DriftObject("group", 3, "root/old", None),),
        (DriftObject("project", 4, "root/a", "root/b"),),
        (DriftObject("group", 5, "root/reused", "root/reused"),),
    )


def test_schema_identity_managed_layout_and_all_transaction_models(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    unrelated = destination / "keep.txt"
    destination.mkdir()
    unrelated.write_text("keep")
    with StateStore.initialize_destination(
        destination, "HTTPS://GitLab.Example:443/base/", 10
    ) as store:
        assert store.schema_version == state.SCHEMA_VERSION
        store.bind_identity("https://gitlab.example/base", 10)
        store.upsert_object("project", 20, "root/project")
        store.upsert_object("project", 20, "root/renamed", missing=True)
        store.upsert_resource(
            "project",
            20,
            "repository",
            "error",
            last_attempt_at="2026-09-20T01:00:00+00:00",
            last_success_at="2026-09-19T01:00:00+00:00",
            revision="abc",
            branch="main",
            last_error="network",
            retained_content=True,
            limitations=("default branch only",),
        )
        first_run = store.begin_run(started_at="2026-09-20T02:00:00+00:00")
        second_run = store.begin_run(started_at="2026-09-20T03:00:00+00:00")
        assert second_run > first_run
        store.finish_run(second_run, "partial", 1, "one resource failed")
        store.set_checkpoint("project:20", "incremental", "boundary")
        store.enqueue_retry("project:20", "item:1", "network")
        store.enqueue_retry(
            "project:20",
            "item:1",
            "timeout",
            details="retry",
            next_attempt_at="later",
        )
        store.complete_retry("project:20", "missing")
        store.upsert_work_item(
            global_id=200,
            project_id=20,
            iid=2,
            item_type="task",
            web_url="https://gitlab.example/root/project/-/issues/2",
            content_path="content/2.md",
            raw_path=".sync/raw/2.json",
            source_updated_at="source-time",
            content_hash="hash",
            status="ok",
            last_attempt_at="attempt",
            last_success_at="success",
        )
        recovery_id = store.record_recovery(
            "publication",
            "project",
            20,
            "staged",
            source_path="staging/a",
            destination_path="content/a",
            details={"revision": "abc"},
        )
        drift_id = store.record_drift(_drift(), run_id=second_run)
        snapshot = store.status_snapshot()

        assert recovery_id == 1
        assert drift_id == 1
        assert snapshot["identity"] == {
            "instance_url": "https://gitlab.example/base",
            "root_group_id": 10,
        }
        assert snapshot["latest_run"]["outcome"] == "partial"
        assert snapshot["latest_run"]["interrupted"] is False
        assert snapshot["resources"] == {
            "total": 1,
            "by_status": {"error": 1},
            "retained_content": 1,
        }
        assert snapshot["freshness"]["last_success_at"].startswith("2026-09-19")
        assert snapshot["resource_details"][0]["object_id"] == 20
        assert snapshot["resource_details"][0]["retained_content"] is True
        assert snapshot["drift"]["added"][0]["id"] == 2
        assert store.get_resource("project", 20, "repository")["branch"] == "main"
        assert store.work_item(20, 2)["item_type"] == "task"
        assert store.work_item_by_global_id(200)["iid"] == 2
        assert store.work_items_for_project(20)[0]["global_id"] == 200
        assert store.work_item(20, 999) is None
        assert store.work_item_by_global_id(999) is None
        assert len(store.objects()) == 1
        with pytest.raises(StateError, match="does not exist"):
            store.update_recovery(999, "complete")

    assert unrelated.read_text() == "keep"
    for relative in state.MANAGED_DIRECTORIES:
        assert (destination / relative).is_dir()
    connection = sqlite3.connect(destination / ".sync/state.sqlite3")
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "identity",
            "objects",
            "resources",
            "runs",
            "checkpoints",
            "retry_queue",
            "drift_snapshots",
            "recovery_records",
            "work_items",
        } <= tables
        assert connection.execute("SELECT attempts FROM retry_queue").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT outcome FROM runs WHERE id = ?", (first_run,)
            ).fetchone()[0]
            == "interrupted"
        )
    finally:
        connection.close()


def test_transactions_rollback_and_identity_mismatch(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://gitlab.example", 1
    ) as store:
        with pytest.raises(RuntimeError):
            with store.transaction() as connection:
                connection.execute(
                    "INSERT INTO checkpoints VALUES ('scope', 'name', 'value', 'now')"
                )
                raise RuntimeError("rollback")
        assert (
            store._connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
            == 0
        )
        with pytest.raises(IdentityMismatchError, match="different GitLab"):
            store.bind_identity("https://other.example", 1)
        with pytest.raises(IdentityMismatchError):
            store.bind_identity("https://gitlab.example", 2)
        run_id = store.begin_run()
        store.finish_run(run_id, "success", 0)
        with pytest.raises(StateError, match="not active"):
            store.finish_run(run_id, "success", 0)

    with pytest.raises(IdentityMismatchError):
        StateStore.initialize_destination(destination, "https://gitlab.example", 999)
    with StateStore(destination / ".sync/state.sqlite3") as reopened:
        assert reopened.schema_version == state.SCHEMA_VERSION


def test_local_status_is_read_only_and_reports_interrupted_run(tmp_path: Path) -> None:
    destination = tmp_path / "missing"
    assert local_status(destination)["initialized"] is False
    assert not destination.exists()

    with StateStore.initialize_destination(
        destination, "https://gitlab.example", 1
    ) as store:
        store.begin_run(started_at="2026-09-20T00:00:00+00:00")
    database = destination / ".sync/state.sqlite3"
    before = database.stat().st_mtime_ns
    report = local_status(destination)
    assert report["initialized"] is True
    assert report["latest_run"]["interrupted"] is True
    assert database.stat().st_mtime_ns == before


def test_lock_contention_probe_release_and_cli_process_semantics(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    first = DestinationLock(destination).acquire()
    assert destination_is_locked(destination) is True
    with pytest.raises(LockContentionError):
        DestinationLock(destination).acquire()
    first.release()
    first.release()
    assert destination_is_locked(destination) is False


def test_process_death_releases_kernel_lock(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    ready_read, ready_write = os.pipe()
    exit_read, exit_write = os.pipe()
    process_id = os.fork()
    if process_id == 0:  # pragma: no cover - child coverage is not returned
        os.close(ready_read)
        os.close(exit_write)
        child_lock = DestinationLock(destination).acquire()
        assert child_lock.path.name == "lock"
        os.write(ready_write, b"1")
        os.read(exit_read, 1)
        os._exit(0)
    os.close(ready_write)
    os.close(exit_read)
    try:
        assert os.read(ready_read, 1) == b"1"
        with pytest.raises(LockContentionError):
            DestinationLock(destination).acquire()
        os.write(exit_write, b"1")
        os.waitpid(process_id, 0)
        with DestinationLock(destination):
            assert destination_is_locked(destination) is True
    finally:
        os.close(ready_read)
        os.close(exit_write)
    with DestinationLock(destination):
        assert destination_is_locked(destination) is True
    assert destination_is_locked(destination) is False


def test_lock_errors_are_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "corpus"
    (destination / ".sync").mkdir(parents=True)
    (destination / ".sync/lock").touch()
    real_flock = state.fcntl.flock

    def fail_flock(file_number: int, operation: int) -> None:
        del file_number, operation
        raise OSError(errno.EIO, "unsafe detail")

    monkeypatch.setattr(state.fcntl, "flock", fail_flock)
    with pytest.raises(StateError, match="inspect"):
        destination_is_locked(destination)
    with pytest.raises(StateError, match="acquire"):
        DestinationLock(destination).acquire()
    monkeypatch.setattr(state.fcntl, "flock", real_flock)

    def fail_open(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(StateError, match="inspect"):
        destination_is_locked(destination)


def test_lock_rejects_symlinked_destination_before_touching_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(StateError, match="safely create"):
        DestinationLock(linked).acquire()
    with pytest.raises(StateError, match="safely inspect"):
        destination_is_locked(linked)
    assert not (target / ".sync").exists()


def test_serialized_writes_from_threads(tmp_path: Path) -> None:
    with StateStore.initialize_destination(
        tmp_path / "corpus", "https://gitlab.example", 1
    ) as store:
        threads = [
            threading.Thread(
                target=store.upsert_object,
                args=("project", number, f"root/{number}"),
            )
            for number in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        count = store._connection.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        assert count == 20


def test_atomic_json_manifest_metadata_and_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nested/metadata.json"
    atomic_write_json(target, {"b": 2, "a": 1})
    assert json.loads(target.read_text()) == {"a": 1, "b": 2}
    original = target.read_bytes()

    def fail_replace(source: str, destination: Path) -> None:
        del destination
        os.unlink(source)
        raise OSError("replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(AtomicWriteError, match="atomically"):
        atomic_write_json(target, {"changed": True})
    assert target.read_bytes() == original
    assert list(target.parent.glob("*.tmp")) == []
    monkeypatch.undo()

    status = {
        "identity": {"instance_url": "x", "root_group_id": 1},
        "current_run": False,
        "latest_run": None,
        "resources": {},
        "freshness": {},
        "drift": None,
    }
    write_manifest(tmp_path, status)
    write_resource_metadata(tmp_path / "content/project.json", {"id": 1})
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["identity"]["root_group_id"] == 1
    assert manifest["run_state"] == {"current": False, "latest": None}
    assert "coverage" in manifest
    assert json.loads((tmp_path / "content/project.json").read_text()) == {"id": 1}
    with pytest.raises(AtomicWriteError):
        atomic_write_json(tmp_path / "bad.json", {"bad": object()})


def test_schema_and_initialization_failures(tmp_path: Path) -> None:
    newer = tmp_path / "newer.sqlite3"
    connection = sqlite3.connect(newer)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(StateError, match="newer"):
        StateStore(newer)
    with pytest.raises(StateError, match="unsupported"):
        StateStore(newer, read_only=True)

    conflict = tmp_path / "conflict.sqlite3"
    connection = sqlite3.connect(conflict)
    connection.execute("CREATE TABLE identity (value TEXT)")
    connection.close()
    with pytest.raises(StateError, match="migrate"):
        StateStore(conflict)

    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    with pytest.raises(StateError, match="managed destination"):
        StateStore.initialize_destination(blocked, "https://gitlab.example", 1)
    with pytest.raises(StateError, match="open destination"):
        StateStore(tmp_path / "absent/state.sqlite3", read_only=True)


def test_version_one_resource_schema_migrates_branch_column(tmp_path: Path) -> None:
    database = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE resources (
        object_kind TEXT, object_id INTEGER, kind TEXT, status TEXT,
        last_attempt_at TEXT, last_success_at TEXT, revision TEXT, last_error TEXT,
        retained_content INTEGER, limitations_json TEXT,
        PRIMARY KEY (object_kind, object_id, kind))"""
    )
    connection.execute("PRAGMA user_version = 1")
    connection.close()
    with StateStore(database) as store:
        assert store.schema_version == state.SCHEMA_VERSION
        columns = {
            row[1] for row in store._connection.execute("PRAGMA table_info(resources)")
        }
        assert "branch" in columns
        assert (
            store._connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'work_items'"
            ).fetchone()[0]
            == 1
        )

    broken = tmp_path / "broken-v1.sqlite3"
    connection = sqlite3.connect(broken)
    connection.execute("PRAGMA user_version = 1")
    connection.close()
    with pytest.raises(StateError, match="migrate"):
        StateStore(broken)

    broken_v2 = tmp_path / "broken-v2.sqlite3"
    connection = sqlite3.connect(broken_v2)
    connection.execute("CREATE TABLE work_items (value TEXT)")
    connection.execute("PRAGMA user_version = 2")
    connection.close()
    with pytest.raises(StateError, match="migrate"):
        StateStore(broken_v2)


def test_version_three_object_schema_migration_and_failure(tmp_path: Path) -> None:
    database = tmp_path / "v3.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE objects (
        kind TEXT, global_id INTEGER, full_path TEXT, observed_at TEXT,
        missing_from_scope INTEGER, PRIMARY KEY (kind, global_id))"""
    )
    connection.execute(
        """CREATE TABLE work_items (
        global_id INTEGER PRIMARY KEY, project_id INTEGER, iid INTEGER,
        item_type TEXT, web_url TEXT, content_path TEXT, raw_path TEXT,
        source_updated_at TEXT, content_hash TEXT, status TEXT,
        last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
        missing_from_scope INTEGER, UNIQUE(project_id, iid))"""
    )
    connection.execute("PRAGMA user_version = 3")
    connection.close()
    with StateStore(database) as store:
        columns = {
            row[1] for row in store._connection.execute("PRAGMA table_info(objects)")
        }
        assert {"stale_path", "status_reason", "evidence_json"} <= columns

    broken = tmp_path / "broken-v3.sqlite3"
    connection = sqlite3.connect(broken)
    connection.execute("CREATE TABLE objects (stale_path TEXT)")
    connection.execute("PRAGMA user_version = 3")
    connection.close()
    with pytest.raises(StateError, match="migrate"):
        StateStore(broken)

    v4 = tmp_path / "v4.sqlite3"
    connection = sqlite3.connect(v4)
    connection.execute(
        """CREATE TABLE work_items (
        global_id INTEGER PRIMARY KEY, project_id INTEGER, iid INTEGER,
        item_type TEXT, web_url TEXT, content_path TEXT, raw_path TEXT,
        source_updated_at TEXT, content_hash TEXT, status TEXT,
        last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
        missing_from_scope INTEGER, UNIQUE(project_id, iid))"""
    )
    connection.execute("PRAGMA user_version = 4")
    connection.close()
    with StateStore(v4) as store:
        indexes = store._connection.execute("PRAGMA index_list(work_items)").fetchall()
        assert any(row[1] == "active_work_item_iid" and row[4] for row in indexes)

    broken_v4 = tmp_path / "broken-v4.sqlite3"
    connection = sqlite3.connect(broken_v4)
    connection.execute("CREATE TABLE work_items (value TEXT)")
    connection.execute("PRAGMA user_version = 4")
    connection.close()
    with pytest.raises(StateError, match="migrate"):
        StateStore(broken_v4)


def test_url_normalization_nondefault_port() -> None:
    assert (
        normalize_instance_url("HTTP://GITLAB.EXAMPLE:8080/path/")
        == "http://gitlab.example:8080/path"
    )
