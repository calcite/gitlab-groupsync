"""Durable destination state, kernel locking, and atomic metadata publication."""

import errno
import fcntl
import json
import os
import sqlite3
import tempfile
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit, urlunsplit

from gitlab_groupsync.gitlab_api import InventoryDiff
from gitlab_groupsync.path_safety import (
    UnsafePathError,
    assert_no_symlinks,
    contained_path,
)

SCHEMA_VERSION = 1
MANAGED_DIRECTORIES = (
    "content",
    "stale",
    ".sync/raw",
    ".sync/staging",
)


class StateError(Exception):
    """A safe error while accessing destination state."""


class IdentityMismatchError(StateError):
    """The destination is already bound to another source identity."""


class LockContentionError(StateError):
    """Another process owns the destination lock."""


class AtomicWriteError(StateError):
    """Atomic metadata publication failed."""


@dataclass(frozen=True)
class DestinationIdentity:
    """Stable source identity bound to one destination."""

    instance_url: str
    root_group_id: int


def utc_now() -> str:
    """Return a stable UTC timestamp suitable for lexical comparison."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize_instance_url(value: str) -> str:
    """Normalize a validated GitLab base URL for durable identity comparison."""
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if port is not None and not (
        (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    ):
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, host, path, "", ""))


class DestinationLock:
    """A process-scoped, nonblocking Linux advisory lock."""

    def __init__(self, destination: str | Path) -> None:
        self.path = Path(destination) / ".sync" / "lock"
        self._file: Any = None

    def acquire(self) -> Self:
        try:
            self.path = contained_path(
                self.path.parent.parent, ".sync/lock", create_parents=True
            )
            lock_file = self.path.open("a+")
        except (OSError, UnsafePathError) as exc:
            raise StateError("could not safely create destination lock") from exc
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock_file.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise LockContentionError(
                    "another synchronization owns the destination lock"
                ) from exc
            raise StateError("could not acquire destination lock") from exc
        self._file = lock_file
        return self

    def release(self) -> None:
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None

    def __enter__(self) -> Self:
        return self.acquire()

    def __exit__(self, *args: object) -> None:
        self.release()


def destination_is_locked(destination: str | Path) -> bool:
    """Probe lock ownership without creating files or retaining the lock."""
    try:
        path = contained_path(Path(destination), ".sync/lock")
    except UnsafePathError as exc:
        raise StateError("could not safely inspect destination lock") from exc
    try:
        lock_file = path.open("r+")
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StateError("could not inspect destination lock") from exc
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return True
            raise StateError("could not inspect destination lock") from exc
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        lock_file.close()


class StateStore:
    """Serialized transactional access to one destination's SQLite state."""

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self._mutex = threading.RLock()
        try:
            if read_only:
                uri = f"{self.path.resolve().as_uri()}?mode=ro"
                self._connection = sqlite3.connect(
                    uri, uri=True, check_same_thread=False
                )
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(self.path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            if not read_only:
                self._connection.execute("PRAGMA journal_mode = WAL")
                version = self.schema_version
                if version > SCHEMA_VERSION:
                    raise StateError(
                        "destination state schema is newer than this application"
                    )
                if version == 0:
                    self._create_schema()
                self._connection.execute(
                    "UPDATE resources SET revision = NULL "
                    "WHERE kind = 'work_items' AND revision IS NOT NULL"
                )
                self._connection.commit()
            elif self.schema_version != SCHEMA_VERSION:
                raise StateError("unsupported destination state schema")
        except sqlite3.Error as exc:
            raise StateError("could not open destination state") from exc

    @classmethod
    def initialize_destination(
        cls, destination: str | Path, instance_url: str, root_group_id: int
    ) -> "StateStore":
        """Create managed layout and bind its durable identity."""
        root = Path(destination)
        try:
            assert_no_symlinks(root)
            root.mkdir(parents=True, exist_ok=True)
            for relative in MANAGED_DIRECTORIES:
                managed = root / relative
                assert_no_symlinks(managed)
                managed.mkdir(parents=True, exist_ok=True)
                if not managed.is_dir():  # pragma: no cover - mkdir race defense
                    raise StateError("managed destination path is not a directory")
        except (OSError, UnsafePathError) as exc:
            raise StateError(
                "could not create managed destination directories"
            ) from exc
        store = cls(root / ".sync" / "state.sqlite3")
        try:
            store.bind_identity(instance_url, root_group_id)
        except Exception:
            store.close()
            raise
        return store

    @property
    def schema_version(self) -> int:
        with self._mutex:
            row = self._connection.execute("PRAGMA user_version").fetchone()
            return int(row[0])

    def close(self) -> None:
        with self._mutex:
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize one immediate transaction and roll it back on failure."""
        with self._mutex:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def _create_schema(self) -> None:
        statements = (
            """CREATE TABLE identity (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                instance_url TEXT NOT NULL,
                root_group_id INTEGER NOT NULL CHECK (root_group_id > 0)
            )""",
            """CREATE TABLE objects (
                kind TEXT NOT NULL,
                global_id INTEGER NOT NULL,
                full_path TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                missing_from_scope INTEGER NOT NULL DEFAULT 0,
                stale_path TEXT,
                status_reason TEXT,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (kind, global_id)
            )""",
            """CREATE TABLE resources (
                object_kind TEXT NOT NULL,
                object_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                last_attempt_at TEXT,
                last_success_at TEXT,
                revision TEXT,
                branch TEXT,
                last_error TEXT,
                retained_content INTEGER NOT NULL DEFAULT 0,
                limitations_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (object_kind, object_id, kind)
            )""",
            """CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                outcome TEXT NOT NULL,
                exit_code INTEGER,
                message TEXT
            )""",
            """CREATE TABLE checkpoints (
                scope TEXT NOT NULL,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (scope, name)
            )""",
            """CREATE TABLE retry_queue (
                scope TEXT NOT NULL,
                item_key TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                next_attempt_at TEXT,
                error_category TEXT NOT NULL,
                details TEXT,
                PRIMARY KEY (scope, item_key)
            )""",
            """CREATE TABLE drift_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES runs(id),
                observed_at TEXT NOT NULL,
                drift_json TEXT NOT NULL
            )""",
            """CREATE TABLE recovery_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                object_kind TEXT NOT NULL,
                object_id INTEGER NOT NULL,
                source_path TEXT,
                destination_path TEXT,
                state TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE work_items (
                global_id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                iid INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                web_url TEXT NOT NULL,
                content_path TEXT NOT NULL,
                raw_path TEXT NOT NULL,
                source_updated_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                last_attempt_at TEXT NOT NULL,
                last_success_at TEXT,
                last_error TEXT,
                missing_from_scope INTEGER NOT NULL DEFAULT 0
            )""",
        )
        try:
            with self.transaction() as connection:
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    """CREATE UNIQUE INDEX active_work_item_iid
                    ON work_items(project_id, iid)
                    WHERE missing_from_scope = 0"""
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.Error as exc:
            raise StateError("could not initialize destination state") from exc

    def bind_identity(self, instance_url: str, root_group_id: int) -> None:
        """Bind once, rejecting accidental destination reuse."""
        identity = DestinationIdentity(
            normalize_instance_url(instance_url), root_group_id
        )
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT instance_url, root_group_id FROM identity WHERE singleton = 1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO identity VALUES (1, ?, ?)",
                    (identity.instance_url, identity.root_group_id),
                )
            elif (row["instance_url"], row["root_group_id"]) != (
                identity.instance_url,
                identity.root_group_id,
            ):
                raise IdentityMismatchError(
                    "destination belongs to a different GitLab instance or root group"
                )

    def upsert_object(
        self,
        kind: str,
        global_id: int,
        full_path: str,
        *,
        missing: bool = False,
        stale_path: str | None = None,
        reason: str | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO objects VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kind, global_id) DO UPDATE SET
                    full_path=excluded.full_path,
                    observed_at=excluded.observed_at,
                    missing_from_scope=excluded.missing_from_scope,
                    stale_path=excluded.stale_path,
                    status_reason=excluded.status_reason,
                    evidence_json=excluded.evidence_json""",
                (
                    kind,
                    global_id,
                    full_path,
                    utc_now(),
                    missing,
                    stale_path,
                    reason,
                    json.dumps(evidence or {}, sort_keys=True),
                ),
            )

    def get_object(self, kind: str, global_id: int) -> dict[str, Any] | None:
        with self._mutex:
            row = self._connection.execute(
                "SELECT * FROM objects WHERE kind = ? AND global_id = ?",
                (kind, global_id),
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["missing_from_scope"] = bool(value["missing_from_scope"])
        value["evidence"] = json.loads(value.pop("evidence_json"))
        return value

    def objects(self, kind: str | None = None) -> tuple[dict[str, Any], ...]:
        with self._mutex:
            if kind is None:
                rows = self._connection.execute(
                    "SELECT * FROM objects ORDER BY kind, global_id"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM objects WHERE kind = ? ORDER BY global_id", (kind,)
                ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value["missing_from_scope"] = bool(value["missing_from_scope"])
            value["evidence"] = json.loads(value.pop("evidence_json"))
            values.append(value)
        return tuple(values)

    def upsert_resource(
        self,
        object_kind: str,
        object_id: int,
        kind: str,
        status: str,
        *,
        last_attempt_at: str | None = None,
        last_success_at: str | None = None,
        revision: str | None = None,
        branch: str | None = None,
        last_error: str | None = None,
        retained_content: bool = False,
        limitations: tuple[str, ...] = (),
    ) -> None:
        if kind == "work_items":
            revision = None
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(object_kind, object_id, kind) DO UPDATE SET
                    status=excluded.status,
                    last_attempt_at=excluded.last_attempt_at,
                    last_success_at=excluded.last_success_at,
                    revision=excluded.revision,
                    branch=excluded.branch,
                    last_error=excluded.last_error,
                    retained_content=excluded.retained_content,
                    limitations_json=excluded.limitations_json""",
                (
                    object_kind,
                    object_id,
                    kind,
                    status,
                    last_attempt_at,
                    last_success_at,
                    revision,
                    branch,
                    last_error,
                    retained_content,
                    json.dumps(limitations),
                ),
            )

    def get_resource(
        self, object_kind: str, object_id: int, kind: str
    ) -> dict[str, Any] | None:
        """Return one resource row for failure-state preservation."""
        with self._mutex:
            row = self._connection.execute(
                """SELECT * FROM resources
                WHERE object_kind = ? AND object_id = ? AND kind = ?""",
                (object_kind, object_id, kind),
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["retained_content"] = bool(value["retained_content"])
        value["limitations"] = tuple(json.loads(value.pop("limitations_json")))
        return value

    def resources_for_object(
        self, object_kind: str, object_id: int
    ) -> dict[str, dict[str, Any]]:
        """Return public resource metadata keyed by component kind."""
        with self._mutex:
            rows = self._connection.execute(
                """SELECT r.kind, r.status, r.last_attempt_at, r.last_success_at,
                CASE WHEN r.kind = 'work_items' THEN NULL ELSE r.revision END
                    AS revision,
                r.branch, r.last_error, r.retained_content, r.limitations_json,
                CASE WHEN r.object_kind = 'project' AND r.kind = 'work_items'
                    THEN (SELECT COUNT(*) FROM work_items AS wi
                          WHERE wi.project_id = r.object_id)
                    ELSE NULL END AS item_count
                FROM resources AS r
                WHERE r.object_kind = ? AND r.object_id = ? ORDER BY r.kind""",
                (object_kind, object_id),
            ).fetchall()
        return {
            row["kind"]: {
                "status": row["status"],
                "last_attempt_at": row["last_attempt_at"],
                "last_success_at": row["last_success_at"],
                "revision": row["revision"],
                "item_count": row["item_count"],
                "branch": row["branch"],
                "last_error": row["last_error"],
                "retained_content": bool(row["retained_content"]),
                "limitations": json.loads(row["limitations_json"]),
            }
            for row in rows
        }

    def begin_run(self, *, started_at: str | None = None) -> int:
        """Durably interrupt abandoned runs and start a new attempt."""
        timestamp = started_at or utc_now()
        with self.transaction() as connection:
            connection.execute(
                """UPDATE runs
                SET finished_at = ?, outcome = 'interrupted', exit_code = 1
                WHERE outcome = 'running'""",
                (timestamp,),
            )
            cursor = connection.execute(
                "INSERT INTO runs (started_at, outcome) VALUES (?, 'running')",
                (timestamp,),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def finish_run(
        self, run_id: int, outcome: str, exit_code: int, message: str | None = None
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE runs
                SET finished_at = ?, outcome = ?, exit_code = ?, message = ?
                WHERE id = ? AND outcome = 'running'""",
                (utc_now(), outcome, exit_code, message, run_id),
            )
            if cursor.rowcount != 1:
                raise StateError("run is not active")

    def set_checkpoint(self, scope: str, name: str, value: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO checkpoints VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, name) DO UPDATE SET
                    value=excluded.value, updated_at=excluded.updated_at""",
                (scope, name, value, utc_now()),
            )

    def get_checkpoint(self, scope: str, name: str) -> str | None:
        with self._mutex:
            row = self._connection.execute(
                "SELECT value FROM checkpoints WHERE scope = ? AND name = ?",
                (scope, name),
            ).fetchone()
        return None if row is None else str(row["value"])

    def enqueue_retry(
        self,
        scope: str,
        item_key: str,
        error_category: str,
        *,
        details: str | None = None,
        next_attempt_at: str | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO retry_queue VALUES (?, ?, 1, ?, ?, ?)
                ON CONFLICT(scope, item_key) DO UPDATE SET
                    attempts=retry_queue.attempts+1,
                    next_attempt_at=excluded.next_attempt_at,
                    error_category=excluded.error_category,
                    details=excluded.details""",
                (scope, item_key, next_attempt_at, error_category, details),
            )

    def complete_retry(self, scope: str, item_key: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM retry_queue WHERE scope = ? AND item_key = ?",
                (scope, item_key),
            )

    def retry_items(self, scope: str) -> tuple[str, ...]:
        with self._mutex:
            rows = self._connection.execute(
                "SELECT item_key FROM retry_queue WHERE scope = ? ORDER BY item_key",
                (scope,),
            ).fetchall()
        return tuple(str(row["item_key"]) for row in rows)

    def upsert_work_item(
        self,
        *,
        global_id: int,
        project_id: int,
        iid: int,
        item_type: str,
        web_url: str,
        content_path: str,
        raw_path: str,
        source_updated_at: str,
        content_hash: str,
        status: str,
        last_attempt_at: str,
        last_success_at: str | None,
        last_error: str | None = None,
        missing: bool = False,
    ) -> None:
        """Persist one successfully identified work item and publication state."""
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO work_items VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(global_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    iid=excluded.iid,
                    item_type=excluded.item_type,
                    web_url=excluded.web_url,
                    content_path=excluded.content_path,
                    raw_path=excluded.raw_path,
                    source_updated_at=excluded.source_updated_at,
                    content_hash=excluded.content_hash,
                    status=excluded.status,
                    last_attempt_at=excluded.last_attempt_at,
                    last_success_at=excluded.last_success_at,
                    last_error=excluded.last_error,
                    missing_from_scope=excluded.missing_from_scope""",
                (
                    global_id,
                    project_id,
                    iid,
                    item_type,
                    web_url,
                    content_path,
                    raw_path,
                    source_updated_at,
                    content_hash,
                    status,
                    last_attempt_at,
                    last_success_at,
                    last_error,
                    missing,
                ),
            )

    def work_item(self, project_id: int, iid: int) -> dict[str, Any] | None:
        with self._mutex:
            row = self._connection.execute(
                """SELECT * FROM work_items WHERE project_id = ? AND iid = ?
                ORDER BY missing_from_scope, global_id DESC LIMIT 1""",
                (project_id, iid),
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["missing_from_scope"] = bool(value["missing_from_scope"])
        return value

    def work_item_by_global_id(self, global_id: int) -> dict[str, Any] | None:
        with self._mutex:
            row = self._connection.execute(
                "SELECT * FROM work_items WHERE global_id = ?", (global_id,)
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["missing_from_scope"] = bool(value["missing_from_scope"])
        return value

    def work_items_for_project(self, project_id: int) -> tuple[dict[str, Any], ...]:
        with self._mutex:
            rows = self._connection.execute(
                "SELECT * FROM work_items WHERE project_id = ? ORDER BY iid",
                (project_id,),
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value["missing_from_scope"] = bool(value["missing_from_scope"])
            values.append(value)
        return tuple(values)

    def record_recovery(
        self,
        operation: str,
        object_kind: str,
        object_id: int,
        state: str,
        *,
        source_path: str | None = None,
        destination_path: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO recovery_records
                (operation, object_kind, object_id, source_path, destination_path,
                 state, details_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    operation,
                    object_kind,
                    object_id,
                    source_path,
                    destination_path,
                    state,
                    json.dumps(details or {}, sort_keys=True),
                    utc_now(),
                ),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def update_recovery(self, recovery_id: int, state: str) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE recovery_records SET state = ?, updated_at = ? WHERE id = ?",
                (state, utc_now(), recovery_id),
            )
            if cursor.rowcount != 1:
                raise StateError("recovery record does not exist")

    def pending_recoveries(
        self, operation: str, object_kind: str, object_id: int
    ) -> tuple[dict[str, Any], ...]:
        with self._mutex:
            rows = self._connection.execute(
                """SELECT * FROM recovery_records
                WHERE operation = ? AND object_kind = ? AND object_id = ?
                AND state IN ('prepared', 'publishing') ORDER BY id""",
                (operation, object_kind, object_id),
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value["details"] = json.loads(value.pop("details_json"))
            values.append(value)
        return tuple(values)

    def all_pending_recoveries(self, operation: str) -> tuple[dict[str, Any], ...]:
        """Return every unfinished operation of one kind for run-start recovery."""
        with self._mutex:
            rows = self._connection.execute(
                """SELECT * FROM recovery_records WHERE operation = ?
                AND state IN ('prepared', 'publishing') ORDER BY id""",
                (operation,),
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value["details"] = json.loads(value.pop("details_json"))
            values.append(value)
        return tuple(values)

    def record_drift(self, drift: InventoryDiff, *, run_id: int | None = None) -> int:
        value = {
            category: [asdict(item) for item in getattr(drift, category)]
            for category in ("added", "absent", "renamed", "path_reused")
        }
        with self.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO drift_snapshots
                (run_id, observed_at, drift_json) VALUES (?, ?, ?)""",
                (run_id, utc_now(), json.dumps(value, sort_keys=True)),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def status_snapshot(self, *, current_run: bool = False) -> dict[str, Any]:
        """Build the public local status projection from authoritative rows."""
        with self._mutex:
            identity_row = self._connection.execute(
                "SELECT instance_url, root_group_id FROM identity WHERE singleton = 1"
            ).fetchone()
            latest_row = self._connection.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            status_rows = self._connection.execute(
                """SELECT status, COUNT(*) AS count FROM resources
                GROUP BY status ORDER BY status"""
            ).fetchall()
            detail_rows = self._connection.execute(
                """SELECT r.object_kind, r.object_id, r.kind, r.status,
                r.last_attempt_at, r.last_success_at,
                CASE WHEN r.kind = 'work_items' THEN NULL ELSE r.revision END
                    AS revision,
                r.branch, r.last_error, r.retained_content, r.limitations_json,
                CASE WHEN r.object_kind = 'project' AND r.kind = 'work_items'
                    THEN (SELECT COUNT(*) FROM work_items AS wi
                          WHERE wi.project_id = r.object_id)
                    ELSE NULL END AS item_count
                FROM resources AS r
                ORDER BY r.object_kind, r.object_id, r.kind"""
            ).fetchall()
            freshness = self._connection.execute(
                """SELECT MAX(last_attempt_at) AS last_attempt_at,
                MAX(last_success_at) AS last_success_at,
                SUM(CASE WHEN retained_content != 0 THEN 1 ELSE 0 END) AS retained
                FROM resources"""
            ).fetchone()
            drift_row = self._connection.execute(
                """SELECT observed_at, drift_json FROM drift_snapshots
                ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        latest = dict(latest_row) if latest_row is not None else None
        if latest is not None:
            latest["interrupted"] = latest["outcome"] == "interrupted" or (
                latest["outcome"] == "running" and not current_run
            )
        by_status = {row["status"]: row["count"] for row in status_rows}
        resource_details = [
            {
                "object_kind": row["object_kind"],
                "object_id": row["object_id"],
                "kind": row["kind"],
                "status": row["status"],
                "last_attempt_at": row["last_attempt_at"],
                "last_success_at": row["last_success_at"],
                "revision": row["revision"],
                "item_count": row["item_count"],
                "branch": row["branch"],
                "last_error": row["last_error"],
                "retained_content": bool(row["retained_content"]),
                "limitations": json.loads(row["limitations_json"]),
            }
            for row in detail_rows
        ]
        drift = None
        if drift_row is not None:
            drift = {
                "observed_at": drift_row["observed_at"],
                **json.loads(drift_row["drift_json"]),
            }
        return {
            "initialized": True,
            "identity": dict(identity_row) if identity_row is not None else None,
            "current_run": current_run,
            "latest_run": latest,
            "resources": {
                "total": sum(by_status.values()),
                "by_status": by_status,
                "retained_content": int(freshness["retained"] or 0),
            },
            "resource_details": resource_details,
            "freshness": {
                "last_attempt_at": freshness["last_attempt_at"],
                "last_success_at": freshness["last_success_at"],
            },
            "drift": drift,
        }


def local_status(destination: str | Path) -> dict[str, Any]:
    """Read status without creating state, loading credentials, or using the network."""
    root = Path(destination)
    database = root / ".sync" / "state.sqlite3"
    current_run = destination_is_locked(root)
    if not database.is_file():
        return {
            "initialized": False,
            "identity": None,
            "current_run": current_run,
            "latest_run": None,
            "resources": {"total": 0, "by_status": {}, "retained_content": 0},
            "resource_details": [],
            "freshness": {"last_attempt_at": None, "last_success_at": None},
            "drift": None,
        }
    with StateStore(database, read_only=True) as store:
        return store.status_snapshot(current_run=current_run)


def atomic_write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    """Flush and atomically replace one JSON metadata file."""
    target = Path(path)
    temporary: str | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = output.name
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        temporary = None
        directory_fd = os.open(
            target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except (OSError, TypeError, ValueError) as exc:
        raise AtomicWriteError("could not atomically publish JSON metadata") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def atomic_write_text(path: str | Path, content: str) -> bool:
    """Flush and atomically replace text, avoiding unchanged rewrites."""
    target = Path(path)
    encoded = content.encode("utf-8")
    try:
        if target.read_bytes() == encoded:
            return False
    except FileNotFoundError:
        pass
    temporary: str | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = output.name
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        temporary = None
        directory_fd = os.open(
            target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise AtomicWriteError("could not atomically publish text") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return True


def write_manifest(destination: str | Path, status: Mapping[str, Any]) -> None:
    """Publish the non-authoritative public status projection."""
    manifest = {
        "identity": status["identity"],
        "run_state": {
            "current": status["current_run"],
            "latest": status["latest_run"],
        },
        "drift": status["drift"],
        "freshness": status["freshness"],
        "coverage": {
            **status["resources"],
            "details": status.get("resource_details", []),
        },
    }
    atomic_write_json(Path(destination) / "manifest.json", manifest)


def write_resource_metadata(path: str | Path, value: Mapping[str, Any]) -> None:
    """Publish one resource sidecar using the same atomic durability contract."""
    atomic_write_json(path, value)
