"""Integration tests for stable-ID relocation, quarantine, and restoration."""

import errno
import json
import os
from pathlib import Path

import pytest

from gitlab_groupsync import reconcile
from gitlab_groupsync.gitlab_api import Inventory, InventoryObject
from gitlab_groupsync.path_safety import (
    UnsafePathError,
    assert_no_symlinks,
    contained_path,
    validate_relative,
)
from gitlab_groupsync.reconcile import (
    LifecycleReconciler,
    ReconcileError,
    ensure_object_directory,
)
from gitlab_groupsync.state import StateStore


def _inventory(
    *,
    groups: tuple[tuple[int, str], ...] = ((1, "root"),),
    projects: tuple[tuple[int, str], ...] = (),
) -> Inventory:
    root = InventoryObject(1, "root")
    return Inventory(
        root,
        tuple(InventoryObject(*value) for value in groups),
        tuple(InventoryObject(*value) for value in projects),
        True,
    )


def _git_component(base: Path, project_id: int, component: str) -> Path:
    path = base / component
    (path / ".git").mkdir(parents=True)
    (path / ".git/gitlab-groupsync").write_text(f"project:{project_id}:{component}\n")
    (path / "payload.txt").write_text(component)
    return path


def test_project_rename_disappearance_reappearance_and_path_reuse(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        lifecycle = LifecycleReconciler(destination, store)
        old = ensure_object_directory(destination, "project", "root/old", 10)
        _git_component(old, 10, "repository")
        store.upsert_object("project", 10, "root/old")

        assert (
            lifecycle.reconcile_inventory(_inventory(projects=((10, "root/new"),))) == 0
        )
        moved = destination / "content/projects/root/new"
        assert (moved / "repository/payload.txt").read_text() == "repository"
        assert not old.exists()
        assert store.get_object("project", 10)["full_path"] == "root/new"

        assert lifecycle.reconcile_inventory(_inventory()) == 0
        missing = store.get_object("project", 10)
        assert missing["missing_from_scope"] is True
        stale = destination / missing["stale_path"]
        metadata = json.loads(stale.with_name(f"{stale.name}.json").read_text())
        assert metadata["prior_source_path"] == "root/new"
        assert "unknown" in metadata["evidence"]["interpretation"]
        assert not moved.exists()

        assert (
            lifecycle.reconcile_inventory(_inventory(projects=((10, "root/restored"),)))
            == 0
        )
        restored = destination / "content/projects/root/restored"
        assert (restored / "repository/payload.txt").read_text() == "repository"
        assert store.get_object("project", 10)["missing_from_scope"] is False

        # A different stable ID can reuse the old path only after retained quarantine.
        assert (
            lifecycle.reconcile_inventory(_inventory(projects=((20, "root/restored"),)))
            == 0
        )
        old_state = store.get_object("project", 10)
        assert old_state["status_reason"] == "path_reused"
        assert not restored.exists()
        assert store.get_object("project", 20)["full_path"] == "root/restored"


def test_group_payload_rename_preserves_descendant_and_component_round_trip(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        lifecycle = LifecycleReconciler(destination, store)
        parent = ensure_object_directory(destination, "group", "root/team", 2)
        child = ensure_object_directory(destination, "group", "root/team/child", 3)
        wiki = parent / "wiki"
        wiki.mkdir()
        (wiki / ".gitlab-groupsync.json").write_text(
            json.dumps({"object_kind": "group", "object_id": 2, "resource": "wiki"})
        )
        (wiki / "home.md").write_text("retained")
        store.upsert_object("group", 2, "root/team")
        store.upsert_object("group", 3, "root/team/child")

        live = _inventory(
            groups=((1, "root"), (2, "root/renamed"), (3, "root/team/child"))
        )
        assert lifecycle.reconcile_inventory(live) == 0
        renamed = destination / "content/groups/root/renamed"
        assert (renamed / "wiki/home.md").read_text() == "retained"
        assert (child / "group.json").exists()

        assert lifecycle.retire_component(
            "group", 2, "root/renamed", "wiki", "configured_exclusion"
        )
        assert not (renamed / "wiki").exists()
        assert lifecycle.restore_component("group", 2, "root/renamed", "wiki")
        assert (renamed / "wiki/home.md").read_text() == "retained"


def test_interrupted_relocation_recovers_without_reclone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        lifecycle = LifecycleReconciler(destination, store)
        old = ensure_object_directory(destination, "project", "root/old", 10)
        _git_component(old, 10, "repository")
        store.upsert_object("project", 10, "root/old")
        real_replace = os.replace

        def interrupt(source: str | Path, target: str | Path) -> None:
            if Path(source) == old:
                raise OSError("power loss")
            real_replace(source, target)

        monkeypatch.setattr(reconcile.os, "replace", interrupt)
        with pytest.raises(OSError, match="power loss"):
            lifecycle.reconcile_live("project", 10, "root/new")
        assert store.all_pending_recoveries("relocation")

        monkeypatch.setattr(reconcile.os, "replace", real_replace)
        assert lifecycle.recover() == 0
        lifecycle.reconcile_live("project", 10, "root/new")
        assert (
            destination / "content/projects/root/new/repository/payload.txt"
        ).read_text() == "repository"
        assert store.all_pending_recoveries("relocation") == ()


def test_component_identity_unmanaged_collision_and_path_hazards(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        lifecycle = LifecycleReconciler(destination, store)
        project = ensure_object_directory(destination, "project", "root/app", 10)
        repository = _git_component(project, 10, "repository")
        work_items = project / "work-items"
        work_items.mkdir()
        (work_items / "1.md").write_text("item")
        assert lifecycle.retire_component(
            "project", 10, "root/app", "repository", "configured_exclusion"
        )
        assert lifecycle.restore_component("project", 10, "root/app", "repository")
        assert repository.exists()
        assert lifecycle.retire_component(
            "project", 10, "root/app", "work-items", "configured_exclusion"
        )
        assert lifecycle.restore_component("project", 10, "root/app", "work-items")
        (repository / ".git/gitlab-groupsync").write_text("project:99:repository\n")
        with pytest.raises(ReconcileError, match="identity"):
            lifecycle.retire_component(
                "project", 10, "root/app", "repository", "configured_exclusion"
            )

    for value in ("/absolute", "../escape", "a\\b", "a\x00b", ".git/config"):
        with pytest.raises(UnsafePathError):
            validate_relative(value)
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    with pytest.raises(UnsafePathError, match="symlink"):
        contained_path(root, "link/escape")


def test_lifecycle_defensive_collisions_and_recovery_failures(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        lifecycle = LifecycleReconciler(destination, store)
        with pytest.raises(ReconcileError, match="unsupported"):
            reconcile.object_relative("note", "root/a")

        ensure_object_directory(destination, "project", "root/app", 10)
        store.upsert_object("project", 10, "root/app")
        store.upsert_resource("project", 10, "repository", "ok")
        assert (
            lifecycle.retire_component(
                "project", 10, "root/app", "wiki", "configured_exclusion"
            )
            is False
        )
        assert (
            lifecycle.restore_component("project", 10, "root/app", "repository")
            is False
        )

        lifecycle.reconcile_live("project", 20, "root/app")
        assert store.get_object("project", 10)["status_reason"] == "path_reused"
        assert store.get_resource("project", 10, "repository")["status"] == (
            "missing_from_scope"
        )
        lifecycle.quarantine_object("project", 10, "root/app", "again", {})

        occupied = ensure_object_directory(destination, "project", "root/occupied", 31)
        source = ensure_object_directory(destination, "project", "root/source", 30)
        store.upsert_object("project", 30, "root/source")
        with pytest.raises(ReconcileError, match="occupied"):
            lifecycle._relocate_object("project", 30, "root/source", "root/occupied")
        assert source.exists() and occupied.exists()
        lifecycle._relocate_object("project", 30, "root/missing", "root/elsewhere")

        store.record_recovery(
            "relocation",
            "project",
            30,
            "prepared",
            source_path="/absolute",
            destination_path="content/projects/root/out",
            details={"mode": "project"},
        )
        assert lifecycle.recover() == 1

        both_source = destination / "content/projects/root/both-source"
        both_target = destination / "content/projects/root/both-target"
        both_source.mkdir()
        both_target.mkdir()
        record_id = store.record_recovery(
            "relocation",
            "project",
            40,
            "prepared",
            source_path=str(both_source.relative_to(destination)),
            destination_path=str(both_target.relative_to(destination)),
            details={"mode": "project"},
        )
        with pytest.raises(ReconcileError, match="both exist"):
            lifecycle._finish_move(
                {
                    "id": record_id,
                    "object_kind": "project",
                    "object_id": 40,
                    "source_path": str(both_source.relative_to(destination)),
                    "destination_path": str(both_target.relative_to(destination)),
                    "details": {"mode": "project"},
                }
            )
        gone_id = store.record_recovery(
            "relocation",
            "project",
            41,
            "prepared",
            source_path="content/projects/root/gone-source",
            destination_path="content/projects/root/gone-target",
            details={"mode": "project"},
        )
        with pytest.raises(ReconcileError, match="both absent"):
            lifecycle._finish_move(
                {
                    "id": gone_id,
                    "object_kind": "project",
                    "object_id": 41,
                    "source_path": "content/projects/root/gone-source",
                    "destination_path": "content/projects/root/gone-target",
                    "details": {"mode": "project"},
                }
            )

        same = ensure_object_directory(destination, "project", "root/same", 50)
        lifecycle._relocate_object("project", 50, "root/source", "root/same")
        assert same.exists()

        no_stale = {"kind": "project", "global_id": 60, "stale_path": None}
        lifecycle._restore_object(no_stale, "root/no-stale")
        stale = destination / "stale/objects/project/61.test"
        stale.mkdir(parents=True)
        atomic_target = ensure_object_directory(
            destination, "project", "root/restore-collision", 99
        )
        assert atomic_target.exists()
        with pytest.raises(ReconcileError, match="not safely restorable"):
            lifecycle._restore_object(
                {
                    "kind": "project",
                    "global_id": 61,
                    "stale_path": str(stale.relative_to(destination)),
                },
                "root/restore-collision",
            )


def test_component_marker_validation_branches(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        lifecycle = LifecycleReconciler(destination, store)
        project = ensure_object_directory(destination, "project", "root/app", 10)
        repository = project / "repository"
        repository.write_text("file")
        with pytest.raises(ReconcileError, match="not a directory"):
            lifecycle.retire_component(
                "project", 10, "root/app", "repository", "disabled"
            )
        repository.unlink()
        repository.mkdir()
        with pytest.raises(ReconcileError, match="marker is invalid"):
            lifecycle.retire_component(
                "project", 10, "root/app", "repository", "disabled"
            )

        group = ensure_object_directory(destination, "group", "root/team", 2)
        wiki = group / "wiki"
        wiki.mkdir()
        (wiki / ".gitlab-groupsync.json").write_text("{}")
        with pytest.raises(ReconcileError, match="group wiki identity"):
            lifecycle.retire_component("group", 2, "root/team", "wiki", "disabled")

        (project / "project.json").write_text('{"id": 99}')
        work_items = project / "work-items"
        work_items.mkdir()
        with pytest.raises(ReconcileError, match="work-items identity"):
            lifecycle.retire_component(
                "project", 10, "root/app", "work-items", "disabled"
            )


def test_group_move_collision_and_invalid_marker(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        lifecycle = LifecycleReconciler(destination, store)
        source = ensure_object_directory(destination, "group", "root/source", 2)
        target = ensure_object_directory(destination, "group", "root/target", 3)
        record = {
            "id": store.record_recovery(
                "relocation",
                "group",
                2,
                "prepared",
                source_path=str(source.relative_to(destination)),
                destination_path=str(target.relative_to(destination)),
                details={"mode": "group"},
            ),
            "object_kind": "group",
            "object_id": 2,
            "source_path": str(source.relative_to(destination)),
            "destination_path": str(target.relative_to(destination)),
            "details": {"mode": "group"},
        }
        with pytest.raises(ReconcileError, match="occupied"):
            lifecycle._finish_move(record)
        (target / "group.json").unlink()
        (source / "group.json").unlink()
        with pytest.raises(ReconcileError, match="marker is invalid"):
            lifecycle._finish_move(record)


def test_inventory_failures_are_isolated_and_restore_noop_branches(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        lifecycle = LifecycleReconciler(destination, store)
        store.upsert_object("project", 10, "../unsafe")
        unsafe_live = _inventory(projects=((20, "../also-unsafe"),))
        assert lifecycle.reconcile_inventory(unsafe_live) == 2

        project = ensure_object_directory(destination, "project", "root/app", 30)
        _git_component(project, 30, "repository")
        assert (
            lifecycle.restore_component("project", 30, "root/app", "repository")
            is False
        )
        stale_root = destination / "stale/components/project/30"
        stale_root.mkdir(parents=True)
        (stale_root / "record-repository.json").write_text("{}")
        (project / "repository").rename(project / "elsewhere")
        assert (
            lifecycle.restore_component("project", 30, "root/app", "repository")
            is False
        )

        file_target = destination / "content/projects/root/file-target"
        file_target.write_text("collision")
        with pytest.raises(ReconcileError, match="unmanaged"):
            ensure_object_directory(destination, "project", "root/file-target", 40)


def test_lstat_inspection_error_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "unreadable"
    real_lstat = Path.lstat

    def fail_lstat(path: Path) -> os.stat_result:
        if path == target:
            raise OSError(errno.EIO, "unsafe detail")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_lstat)
    with pytest.raises(UnsafePathError, match="inspect"):
        assert_no_symlinks(target)
