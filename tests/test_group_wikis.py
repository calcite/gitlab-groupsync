"""Group-wiki source materialization, safety, retention, and recovery tests."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from gitlab_groupsync import group_wikis
from gitlab_groupsync.git_sync import PathSafetyError
from gitlab_groupsync.gitlab_api import DiscoveryError, GroupWikiPages
from gitlab_groupsync.group_wikis import GroupWikiExporter, group_path
from gitlab_groupsync.reconcile import LifecycleReconciler
from gitlab_groupsync.state import StateStore


def _page(slug: str, source_format: str, content: str) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": f"Title {slug}",
        "format": source_format,
        "encoding": "UTF-8",
        "content": content,
    }


class FakeGroupWikiClient:
    def __init__(self, result: GroupWikiPages | Exception) -> None:
        self.result = result
        self.calls: list[int] = []

    def group_wiki_pages(self, group_id: int) -> GroupWikiPages:
        self.calls.append(group_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _exporter(client: Any, store: StateStore, destination: Path) -> GroupWikiExporter:
    return GroupWikiExporter(client, store, destination, "https://git.example/base")


def test_complete_formats_nested_slugs_raw_sidecars_and_deterministic_noop(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    pages = (
        _page("home", "markdown", "# Home\n[asset](uploads/a.png)\n"),
        _page("guide/start", "asciidoc", "= Start\n"),
        _page("reference", "rdoc", "= Reference\n"),
        _page("notes.org", "org", "* Notes\n"),
    )
    client = FakeGroupWikiClient(GroupWikiPages(200, pages))
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root/empty-team", 2)
        exporter = _exporter(client, store, destination)
        result = exporter.sync_group(2, "root/empty-team", base)
        assert result.status == "ok" and result.failure is False
        wiki = base / "wiki"
        expected = [
            wiki / "home.md",
            wiki / "guide/start.adoc",
            wiki / "reference.rdoc",
            wiki / "notes.org",
        ]
        assert [path.read_text() for path in expected] == [
            "# Home\n[asset](uploads/a.png)\n",
            "= Start\n",
            "= Reference\n",
            "* Notes\n",
        ]
        sidecar = json.loads((wiki / "guide/start.adoc.json").read_text())
        assert sidecar["source_url"].endswith("/root/empty-team/-/wikis/guide/start")
        raw = destination / ".sync/raw/groups/2/wiki.json"
        assert json.loads(raw.read_text())["pages"][0]["slug"] == "guide/start"
        assert not (destination / "content/.sync").exists()
        assert "payloads are not downloaded" in " ".join(
            store.get_resource("group", 2, "wiki")["limitations"]
        )
        before = {path: path.stat().st_mtime_ns for path in (*expected, raw)}
        assert exporter.sync_group(2, "root/empty-team", base).status == "ok"
        assert {path: path.stat().st_mtime_ns for path in (*expected, raw)} == before


@pytest.mark.parametrize("status", [401, 403, 404])
def test_http_evidence_is_unavailable_ambiguous_and_creates_no_wiki(
    tmp_path: Path, status: int
) -> None:
    destination = tmp_path / str(status)
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root/team", 2)
        result = _exporter(
            FakeGroupWikiClient(GroupWikiPages(status, None)), store, destination
        ).sync_group(2, "root/team", base)
        resource = store.get_resource("group", 2, "wiki")
        assert result.failure is True
        assert resource["status"] == "unavailable"
        assert f"HTTP {status}" in resource["last_error"]
        assert "cannot distinguish" in " ".join(resource["limitations"])
        assert not (base / "wiki").exists()


def test_confirmed_empty_has_success_without_empty_active_directory(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root", 1)
        result = _exporter(
            FakeGroupWikiClient(GroupWikiPages(200, ())), store, destination
        ).sync_group(1, "root", base)
        resource = store.get_resource("group", 1, "wiki")
        assert result.failure is False and resource["status"] == "empty"
        assert resource["last_success_at"] is not None
        assert not (base / "wiki").exists()
        raw = destination / ".sync/raw/groups/1/wiki.json"
        assert json.loads(raw.read_text())["pages"] == []

        populated = FakeGroupWikiClient(
            GroupWikiPages(200, (_page("home", "markdown", "old"),))
        )
        _exporter(populated, store, destination).sync_group(1, "root", base)
        retired = destination / ".sync/staging/empty-group-wiki-1"
        retired.mkdir()
        result = _exporter(
            FakeGroupWikiClient(GroupWikiPages(200, ())), store, destination
        ).sync_group(1, "root", base)
        assert result.failure is False
        assert not (base / "wiki").exists() and not retired.exists()

        (base / "wiki").mkdir()
        failed = _exporter(
            FakeGroupWikiClient(GroupWikiPages(200, ())), store, destination
        ).sync_group(1, "root", base)
        assert failed.failure is True


def test_transient_and_incomplete_refresh_retain_last_complete_tree(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    good = FakeGroupWikiClient(
        GroupWikiPages(200, (_page("home", "markdown", "old complete"),))
    )
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root", 1)
        _exporter(good, store, destination).sync_group(1, "root", base)
        source = base / "wiki/home.md"
        raw = destination / ".sync/raw/groups/1/wiki.json"
        old = (source.read_bytes(), raw.read_bytes())
        failed = _exporter(
            FakeGroupWikiClient(DiscoveryError("later list/page request failed")),
            store,
            destination,
        ).sync_group(1, "root", base)
        resource = store.get_resource("group", 1, "wiki")
        assert failed.failure is True and resource["status"] == "error"
        assert resource["retained_content"] is True
        assert resource["last_success_at"] is not None
        assert (source.read_bytes(), raw.read_bytes()) == old


@pytest.mark.parametrize(
    "page",
    [
        _page("../escape", "markdown", "bad"),
        _page("/absolute", "markdown", "bad"),
        _page("windows\\escape", "markdown", "bad"),
        _page("unknown", "textile", "bad"),
        {"slug": "bad", "title": "bad", "format": "markdown", "content": 1},
    ],
)
def test_unsafe_or_invalid_pages_publish_nothing(
    tmp_path: Path, page: dict[str, Any]
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root", 1)
        result = _exporter(
            FakeGroupWikiClient(GroupWikiPages(200, (page,))), store, destination
        ).sync_group(1, "root", base)
        assert result.failure is True
        assert not (base / "wiki").exists()
        assert not (destination / ".sync/raw/groups/1/wiki.json").exists()


def test_group_path_and_wiki_collision_reject_traversal_symlink_and_unmanaged(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    with pytest.raises(PathSafetyError, match="unsafe group path"):
        group_path(destination, "root/../escape", 1)
    base = group_path(destination, "root/team", 2)
    (base / "wiki").symlink_to(tmp_path)
    with pytest.raises(PathSafetyError, match="symlink"):
        group_path(destination, "root/team", 2)
    (base / "wiki").unlink()
    unmanaged = base / "wiki"
    unmanaged.mkdir()
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        result = _exporter(
            FakeGroupWikiClient(
                GroupWikiPages(200, (_page("home", "markdown", "safe"),))
            ),
            store,
            destination,
        ).sync_group(2, "root/team", base)
        assert result.failure is True
        assert list(unmanaged.iterdir()) == []
        assert not (destination / ".sync/raw/groups/2/wiki.json").exists()


def test_group_path_rejects_file_ancestors_bad_markers_and_wrong_identity(
    tmp_path: Path,
) -> None:
    file_destination = tmp_path / "file"
    file_destination.write_text("x")
    with pytest.raises(PathSafetyError, match="must be a directory"):
        group_path(file_destination, "root", 1)

    destination = tmp_path / "corpus"
    ancestor = destination / "content/groups/root"
    ancestor.parent.mkdir(parents=True)
    ancestor.write_text("x")
    with pytest.raises(PathSafetyError, match="ancestor"):
        group_path(destination, "root/team", 2)
    ancestor.unlink()
    unmanaged = destination / "content/groups/root"
    unmanaged.mkdir()
    with pytest.raises(PathSafetyError, match="unmanaged"):
        group_path(destination, "root", 1)
    (unmanaged / "group.json").write_text("bad-json")
    with pytest.raises(PathSafetyError, match="marker is invalid"):
        group_path(destination, "root", 1)
    (unmanaged / "group.json").write_text('{"id": 9}')
    with pytest.raises(PathSafetyError, match="identity does not match"):
        group_path(destination, "root", 1)


@pytest.mark.parametrize(
    "pages",
    [
        (
            _page("same", "markdown", "one"),
            _page("same", "markdown", "two"),
        ),
        (
            _page("foo", "markdown", "one"),
            _page("foo.md/bar", "markdown", "two"),
        ),
        (
            _page("foo.md/bar", "markdown", "one"),
            _page("foo", "markdown", "two"),
        ),
    ],
)
def test_slug_filesystem_collisions_reject_complete_snapshot(
    tmp_path: Path, pages: tuple[dict[str, Any], ...]
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root", 1)
        result = _exporter(
            FakeGroupWikiClient(GroupWikiPages(200, pages)), store, destination
        ).sync_group(1, "root", base)
        assert result.failure is True and not (base / "wiki").exists()


def test_interrupted_tree_swap_recovers_complete_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    client = FakeGroupWikiClient(
        GroupWikiPages(200, (_page("home", "markdown", "complete"),))
    )
    real_replace = os.replace
    interrupted = False

    def fail_once(source: str | Path, target: str | Path) -> None:
        nonlocal interrupted
        if not interrupted and Path(target).name == "wiki":
            interrupted = True
            raise OSError("interrupted publication")
        real_replace(source, target)

    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root", 1)
        exporter = _exporter(client, store, destination)
        monkeypatch.setattr(group_wikis.os, "replace", fail_once)
        assert exporter.sync_group(1, "root", base).failure is True
        assert not (base / "wiki").exists()
        assert store.pending_recoveries("group_wiki_publication", "group", 1)
        assert exporter.sync_group(1, "root", base).failure is False
        assert (base / "wiki/home.md").read_text() == "complete"
        assert store.pending_recoveries("group_wiki_publication", "group", 1) == ()


def test_publication_and_all_recovery_fallback_branches(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root", 1)
        exporter = _exporter(
            FakeGroupWikiClient(GroupWikiPages(200, ())), store, destination
        )
        active = base / "wiki"

        def tree(path: Path, content: str = "x") -> None:
            path.mkdir(parents=True)
            (path / ".gitlab-groupsync.json").write_text(
                json.dumps({"object_kind": "group", "object_id": 1, "resource": "wiki"})
            )
            (path / "home.md").write_text(content)

        # A direct swap still refuses an unmanaged active tree defensively.
        active.mkdir()
        invalid_parent = destination / ".sync/staging/invalid"
        invalid_staged = invalid_parent / "wiki"
        tree(invalid_staged)
        invalid_id = store.record_recovery(
            "group_wiki_publication",
            "group",
            1,
            "prepared",
            source_path=str(invalid_staged),
            destination_path=str(active),
            details={"backup_path": str(invalid_parent / "previous")},
        )
        with pytest.raises(PathSafetyError, match="unmanaged group wiki"):
            exporter._swap(
                invalid_id,
                1,
                invalid_staged,
                active,
                invalid_parent / "previous",
            )
        store.update_recovery(invalid_id, "abandoned")
        shutil.rmtree(active)
        shutil.rmtree(invalid_parent)

        # Existing backup cleanup during a complete swap.
        tree(active, "old")
        parent = destination / ".sync/staging/manual"
        staged = parent / "wiki"
        backup = parent / "previous"
        tree(staged, "new")
        tree(backup, "older")
        recovery_id = store.record_recovery(
            "group_wiki_publication",
            "group",
            1,
            "prepared",
            source_path=str(staged),
            destination_path=str(active),
            details={"backup_path": str(backup)},
        )
        exporter._swap(recovery_id, 1, staged, active, backup)
        assert (active / "home.md").read_text() == "new"

        # Source already moved: accept valid active and remove leftover backup.
        parent = destination / ".sync/staging/already-moved"
        missing = parent / "wiki"
        backup = parent / "previous"
        tree(backup)
        store.record_recovery(
            "group_wiki_publication",
            "group",
            1,
            "publishing",
            source_path=str(missing.relative_to(destination)),
            destination_path=str(active.relative_to(destination)),
            details={"backup_path": str(backup.relative_to(destination))},
        )
        assert exporter._recover(1) == 0 and not backup.exists()

        # Invalid active with a backup restores the previous complete tree.
        shutil.rmtree(active)
        parent = destination / ".sync/staging/restore"
        missing = parent / "wiki"
        backup = parent / "previous"
        tree(backup, "restored")
        store.record_recovery(
            "group_wiki_publication",
            "group",
            1,
            "publishing",
            source_path=str(missing.relative_to(destination)),
            destination_path=str(active.relative_to(destination)),
            details={"backup_path": str(backup.relative_to(destination))},
        )
        assert exporter._recover(1) == 1
        assert (active / "home.md").read_text() == "restored"

        # Missing source, destination, and backup is abandoned.
        for child in active.iterdir():
            child.unlink()
        active.rmdir()
        store.record_recovery(
            "group_wiki_publication",
            "group",
            1,
            "prepared",
            source_path=str(destination / ".sync/staging/gone/wiki"),
            destination_path=str(active.relative_to(destination)),
            details={"backup_path": ".sync/staging/gone/previous"},
        )
        assert exporter._recover(1) == 1

        # A malformed marker exercises defensive validation.
        active.mkdir()
        (active / ".gitlab-groupsync.json").write_text("not-json")
        assert exporter._valid_tree(active, 1) is False

        # Recovery state write failure is retained for another attempt.
        pending = store.record_recovery(
            "group_wiki_publication",
            "group",
            1,
            "prepared",
            source_path=str(destination / ".sync/staging/also-gone/wiki"),
            destination_path=str(destination / "missing"),
            details={
                "backup_path": str(destination / ".sync/staging/also-gone/previous")
            },
        )
        original = store.update_recovery

        def fail_update(record_id: int, state: str) -> None:
            if record_id == pending:
                raise group_wikis.StateError("state failed")
            original(record_id, state)

        store.update_recovery = fail_update  # type: ignore[method-assign]
        assert exporter._recover(1) == 1


def test_empty_with_lifecycle_retires_content_and_recovery_swap_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = group_path(destination, "root", 1)
        lifecycle = LifecycleReconciler(destination, store)
        populated = GroupWikiExporter(
            FakeGroupWikiClient(
                GroupWikiPages(200, (_page("home", "markdown", "old"),))
            ),
            store,
            destination,
            "https://git.example",
            lifecycle=lifecycle,
        )
        assert populated.sync_group(1, "root", base).status == "ok"
        empty = GroupWikiExporter(
            FakeGroupWikiClient(GroupWikiPages(200, ())),
            store,
            destination,
            "https://git.example",
            lifecycle=lifecycle,
        )
        assert empty.sync_group(1, "root", base).status == "empty"
        assert not (base / "wiki").exists()

        staged = destination / ".sync/staging/recovery/wiki"
        staged.mkdir(parents=True)
        (staged / ".gitlab-groupsync.json").write_text(
            json.dumps({"object_kind": "group", "object_id": 1, "resource": "wiki"})
        )
        record_id = store.record_recovery(
            "group_wiki_publication",
            "group",
            1,
            "prepared",
            source_path=str(staged.relative_to(destination)),
            destination_path=str((base / "wiki").relative_to(destination)),
            details={"backup_path": ".sync/staging/recovery/previous"},
        )

        def fail_swap(*args: Any) -> None:
            raise PathSafetyError("collision")

        monkeypatch.setattr(empty, "_swap", fail_swap)
        assert empty._recover(1) == 1
        assert (
            store.pending_recoveries("group_wiki_publication", "group", 1)[0]["id"]
            == record_id
        )
        missing_id = store.record_recovery(
            "group_wiki_publication",
            "group",
            1,
            "prepared",
            source_path=".sync/staging/missing/wiki",
            destination_path="content/groups/root/missing-wiki",
            details={"backup_path": ".sync/staging/missing/previous"},
        )
        assert empty._recover(1) == 2
        assert all(
            record["id"] != missing_id
            for record in store.pending_recoveries("group_wiki_publication", "group", 1)
        )
