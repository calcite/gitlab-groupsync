"""Stable-ID object relocation, quarantine, restoration, and component retention."""

import json
import os
import time
from pathlib import Path
from typing import Any

from gitlab_groupsync.path_safety import (
    UnsafePathError,
    assert_no_symlinks,
    contained_path,
    fsync_directories,
    read_marker,
    validate_relative,
)
from gitlab_groupsync.state import StateStore, atomic_write_json, utc_now


class ReconcileError(Exception):
    """A lifecycle operation could not proceed without risking retained data."""


def object_relative(kind: str, full_path: str) -> Path:
    if kind not in {"project", "group"}:
        raise ReconcileError("unsupported managed object kind")
    try:
        path = validate_relative(full_path, label=f"{kind} path")
    except UnsafePathError as exc:
        raise ReconcileError(str(exc)) from exc
    return Path("content") / f"{kind}s" / path


def object_marker(kind: str) -> str:
    return f"{kind}.json"


def ensure_object_directory(
    destination: Path, kind: str, full_path: str, global_id: int
) -> Path:
    """Create structural ancestors and validate the leaf's stable-ID marker."""
    relative = object_relative(kind, full_path)
    try:
        target = contained_path(destination, relative, create_parents=True)
    except UnsafePathError as exc:
        raise ReconcileError(str(exc)) from exc
    marker = target / object_marker(kind)
    if target.exists():
        assert_no_symlinks(target)
        if not target.is_dir():
            raise ReconcileError(f"destination collides with unmanaged {kind} content")
        if not marker.exists():
            raise ReconcileError(f"destination collides with unmanaged {kind} content")
        marker_id = LifecycleReconciler._marker_id(marker)
        if marker_id is None:
            raise ReconcileError(f"managed {kind} marker is invalid")
        if marker_id != global_id:
            raise ReconcileError(f"destination {kind} identity does not match")
    else:
        target.mkdir()
        atomic_write_json(marker, {"id": global_id})
    return target


class LifecycleReconciler:
    """Reconcile mutable display paths around durable kind/global-ID identity."""

    def __init__(self, destination: Path, store: StateStore) -> None:
        self.destination = destination
        self.store = store

    def recover(self) -> int:
        failures = 0
        for record in self.store.all_pending_recoveries("relocation"):
            try:
                self._finish_move(record)
            except (OSError, ReconcileError, UnsafePathError):
                failures += 1
        return failures

    def reconcile_inventory(self, live: Any) -> int:
        """Apply complete-inventory disappearance and then live path reconciliation."""
        failures = self.recover()
        live_by_kind = {
            "group": {item.id: item for item in live.groups},
            "project": {item.id: item for item in live.projects},
        }
        for kind in ("project", "group"):
            for previous in self.store.objects(kind):
                if previous["global_id"] not in live_by_kind[kind]:
                    replacement = next(
                        (
                            item.id
                            for item in live_by_kind[kind].values()
                            if item.full_path == previous["full_path"]
                        ),
                        None,
                    )
                    reason = (
                        "path_reused"
                        if replacement is not None
                        else "missing_from_scope"
                    )
                    evidence = (
                        {
                            "replacement_id": replacement,
                            "evidence": (
                                "complete discovery found another ID at the prior path"
                            ),
                            "interpretation": (
                                "the prior object's disposition is unknown"
                            ),
                        }
                        if replacement is not None
                        else {
                            "evidence": "absent from complete authoritative discovery",
                            "interpretation": (
                                "deletion, move, or lost visibility is unknown"
                            ),
                        }
                    )
                    try:
                        self.quarantine_object(
                            kind,
                            int(previous["global_id"]),
                            str(previous["full_path"]),
                            reason,
                            evidence,
                        )
                    except (OSError, ReconcileError, UnsafePathError):
                        failures += 1
        groups = sorted(
            live.groups, key=lambda item: (-item.full_path.count("/"), item.id)
        )
        for kind, values in (("group", groups), ("project", live.projects)):
            for item in values:
                try:
                    self.reconcile_live(kind, item.id, item.full_path)
                except (OSError, ReconcileError, UnsafePathError):
                    failures += 1
        return failures

    def reconcile_live(self, kind: str, global_id: int, full_path: str) -> None:
        object_relative(kind, full_path)
        previous = self.store.get_object(kind, global_id)
        if previous is not None and previous["missing_from_scope"]:
            self._restore_object(previous, full_path)
        elif previous is not None and previous["full_path"] != full_path:
            self._relocate_object(kind, global_id, previous["full_path"], full_path)
        other = next(
            (
                value
                for value in self.store.objects(kind)
                if value["global_id"] != global_id
                and value["full_path"] == full_path
                and not value["missing_from_scope"]
            ),
            None,
        )
        if other is not None:
            self.quarantine_object(
                kind,
                other["global_id"],
                full_path,
                "path_reused",
                {
                    "replacement_id": global_id,
                    "evidence": "live path reused by another ID",
                },
            )
        self.store.upsert_object(kind, global_id, full_path)

    def quarantine_object(
        self,
        kind: str,
        global_id: int,
        full_path: str,
        reason: str,
        evidence: dict[str, Any],
    ) -> None:
        previous = self.store.get_object(kind, global_id)
        if previous is not None and previous["missing_from_scope"]:
            return
        source = contained_path(self.destination, object_relative(kind, full_path))
        stale_relative = self._new_stale_path(
            Path("stale") / "objects" / kind / str(global_id)
        )
        destination = contained_path(
            self.destination, stale_relative, create_parents=True, label="stale path"
        )
        if source.exists():
            self._move(kind, global_id, source, destination, mode=kind)
        metadata = destination.with_name(f"{destination.name}.json")
        destination.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            metadata,
            {
                "object_kind": kind,
                "object_id": global_id,
                "prior_source_path": full_path,
                "quarantined_at": utc_now(),
                "reason": reason,
                "evidence": evidence,
            },
        )
        self.store.upsert_object(
            kind,
            global_id,
            full_path,
            missing=True,
            stale_path=str(stale_relative),
            reason=reason,
            evidence=evidence,
        )
        for resource_kind, resource in self.store.resources_for_object(
            kind, global_id
        ).items():
            self.store.upsert_resource(
                kind,
                global_id,
                resource_kind,
                "missing_from_scope",
                last_attempt_at=resource["last_attempt_at"],
                last_success_at=resource["last_success_at"],
                revision=resource["revision"],
                branch=resource["branch"],
                last_error="absent from complete discovery; cause is not inferred",
                retained_content=True,
                limitations=tuple(resource["limitations"]),
            )

    def retire_component(
        self, kind: str, global_id: int, full_path: str, component: str, reason: str
    ) -> bool:
        base = contained_path(self.destination, object_relative(kind, full_path))
        active = contained_path(base, validate_relative(component, label="component"))
        if not active.exists():
            return False
        self._validate_component(kind, global_id, component, active, base)
        stale_relative = self._new_stale_path(
            Path("stale/components") / kind / str(global_id) / component
        )
        stale = contained_path(
            self.destination,
            stale_relative,
            create_parents=True,
            label="stale component",
        )
        self._move(kind, global_id, active, stale, mode="component")
        atomic_write_json(
            stale.parent / f"record-{stale.name}.json",
            {
                "object_kind": kind,
                "object_id": global_id,
                "component": component,
                "prior_source_path": str(object_relative(kind, full_path) / component),
                "quarantined_at": utc_now(),
                "reason": reason,
            },
        )
        return True

    def restore_component(
        self, kind: str, global_id: int, full_path: str, component: str
    ) -> bool:
        base = ensure_object_directory(self.destination, kind, full_path, global_id)
        active = contained_path(base, validate_relative(component, label="component"))
        if active.exists():
            self._validate_component(kind, global_id, component, active, base)
            return False
        root = contained_path(
            self.destination,
            Path("stale/components") / kind / str(global_id),
            label="stale component root",
        )
        if not root.is_dir():
            return False
        candidates = sorted(
            (path for path in root.iterdir() if path.name.startswith(f"{component}.")),
            key=lambda path: path.name,
            reverse=True,
        )
        for candidate in candidates:
            assert_no_symlinks(candidate)
            self._validate_component(kind, global_id, component, candidate, base)
            self._move(kind, global_id, candidate, active, mode="component")
            return True
        return False

    def _restore_object(self, previous: dict[str, Any], full_path: str) -> None:
        stale_path = previous.get("stale_path")
        if not stale_path:
            return
        source = contained_path(self.destination, stale_path, label="stale object")
        target = contained_path(
            self.destination,
            object_relative(previous["kind"], full_path),
            create_parents=True,
        )
        if source.exists() and (
            not target.exists()
            or (previous["kind"] == "group" and not (target / "group.json").exists())
        ):
            self._move(
                previous["kind"],
                previous["global_id"],
                source,
                target,
                mode=previous["kind"],
            )
        elif target.exists() and not read_marker(
            target / object_marker(previous["kind"]), {"id": previous["global_id"]}
        ):
            raise ReconcileError(
                "reappearing object destination is not safely restorable"
            )

    def _relocate_object(
        self, kind: str, global_id: int, old_path: str, new_path: str
    ) -> None:
        source = contained_path(self.destination, object_relative(kind, old_path))
        target = contained_path(
            self.destination, object_relative(kind, new_path), create_parents=True
        )
        if not source.exists():
            return
        if target.exists() and kind != "group":
            if read_marker(target / object_marker(kind), {"id": global_id}):
                return
            raise ReconcileError("relocation destination is occupied")
        self._move(kind, global_id, source, target, mode=kind)

    def _move(
        self, kind: str, global_id: int, source: Path, target: Path, *, mode: str
    ) -> None:
        source_relative = source.relative_to(self.destination)
        target_relative = target.relative_to(self.destination)
        recovery_id = self.store.record_recovery(
            "relocation",
            kind,
            global_id,
            "prepared",
            source_path=str(source_relative),
            destination_path=str(target_relative),
            details={"mode": mode},
        )
        record = {
            "id": recovery_id,
            "object_kind": kind,
            "object_id": global_id,
            "source_path": str(source_relative),
            "destination_path": str(target_relative),
            "details": {"mode": mode},
        }
        self._finish_move(record)

    def _finish_move(self, record: dict[str, Any]) -> None:
        source = contained_path(self.destination, record["source_path"])
        target = contained_path(
            self.destination, record["destination_path"], create_parents=True
        )
        if record["details"]["mode"] == "group":
            self._finish_group_move(record, source, target)
            return
        if source.exists() and target.exists():
            raise ReconcileError("relocation source and destination both exist")
        if source.exists():
            assert_no_symlinks(source)
            self.store.update_recovery(record["id"], "publishing")
            os.replace(source, target)
            fsync_directories((source.parent, target.parent))
        elif not target.exists():
            raise ReconcileError("relocation source and destination are both absent")
        assert_no_symlinks(target)
        self.store.update_recovery(record["id"], "complete")

    def _finish_group_move(
        self, record: dict[str, Any], source: Path, target: Path
    ) -> None:
        """Move only one group's payload, never descendant group directories."""
        target.mkdir(parents=True, exist_ok=True)
        moved = False
        for name in ("group.json", "wiki"):
            old = source / name
            new = target / name
            if old.exists() and new.exists():
                raise ReconcileError("group relocation payload destination is occupied")
            if old.exists():
                assert_no_symlinks(old)
                self.store.update_recovery(record["id"], "publishing")
                os.replace(old, new)
                moved = True
        marker = target / "group.json"
        if not read_marker(marker, {"id": record["object_id"]}):
            raise ReconcileError("relocated group marker is invalid")
        if moved:
            fsync_directories((source, target))
        self.store.update_recovery(record["id"], "complete")

    def _new_stale_path(self, base: Path) -> Path:
        suffix = f"{utc_now().replace(':', '').replace('+', '_')}-{time.time_ns()}"
        return base.with_name(f"{base.name}.{suffix}")

    @staticmethod
    def _marker_id(marker: Path) -> int | None:
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        identity = value.get("id") if isinstance(value, dict) else None
        return (
            identity
            if isinstance(identity, int) and not isinstance(identity, bool)
            else None
        )

    @staticmethod
    def _validate_component(
        kind: str, global_id: int, component: str, path: Path, base: Path
    ) -> None:
        assert_no_symlinks(path)
        if not path.is_dir():
            raise ReconcileError("managed component is not a directory")
        if component in {"repository", "wiki"} and kind == "project":
            marker = path / ".git/gitlab-groupsync"
            try:
                value = marker.read_text(encoding="utf-8")
            except OSError as exc:
                raise ReconcileError("managed Git component marker is invalid") from exc
            if value != f"project:{global_id}:{component}\n":
                raise ReconcileError("managed Git component identity does not match")
        elif component == "wiki" and kind == "group":
            if not read_marker(
                path / ".gitlab-groupsync.json",
                {"object_kind": "group", "object_id": global_id, "resource": "wiki"},
            ):
                raise ReconcileError("managed group wiki identity does not match")
        elif component == "work-items" and not read_marker(
            base / "project.json", {"id": global_id}
        ):
            raise ReconcileError("managed work-items identity does not match")
