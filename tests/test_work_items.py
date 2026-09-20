"""Work-item rendering, incremental reconciliation, and publication tests."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from gitlab_groupsync import work_items
from gitlab_groupsync.gitlab_api import DiscoveryError, WorkItemHierarchy
from gitlab_groupsync.state import StateError, StateStore
from gitlab_groupsync.work_items import WorkItemExporter


def _item(
    iid: int,
    *,
    item_type: str = "issue",
    state: str = "opened",
    updated: str = "2026-09-20T08:00:00+00:00",
) -> dict[str, Any]:
    route = "work_items" if item_type == "task" else "issues"
    return {
        "id": 100 + iid,
        "iid": iid,
        "project_id": 10,
        "issue_type": item_type,
        "title": f"Title {iid} ---\nmetadata: safe",
        "state": state,
        "description": "Description [upload](/uploads/a/file.txt)",
        "web_url": f"https://git.example/root/app/-/{route}/{iid}",
        "author": {"id": 1, "name": "Author", "username": "author"},
        "assignees": [{"id": 2, "name": "Assigned", "username": "assigned"}],
        "labels": ["one", "two"],
        "milestone": {"id": 3, "title": "M1"},
        "confidential": iid == 2,
        "created_at": "2026-09-19T08:00:00+00:00",
        "updated_at": updated,
        "closed_at": "2026-09-20T07:00:00+00:00" if state == "closed" else None,
    }


def _note(note_id: int, body: str, *, system: bool = False, created: str | None = None):
    return {
        "id": note_id,
        "body": body,
        "author": {"id": note_id, "name": f"User {note_id}", "username": f"u{note_id}"},
        "created_at": created or f"2026-09-20T08:00:0{note_id}+00:00",
        "updated_at": f"2026-09-20T09:00:0{note_id}+00:00",
        "system": system,
        "resolvable": True,
        "resolved": note_id % 2 == 0,
        "resolved_at": None,
    }


class FakeWorkItemClient:
    def __init__(self, listed: list[dict[str, Any]]) -> None:
        self.listed = listed
        self.updated_after: list[str | None] = []
        self.discussion_failures: set[int] = set()
        self.discussions: dict[int, tuple[dict[str, Any], ...]] = {
            1: (
                {"id": "later", "individual_note": True, "notes": [_note(3, "later")]},
                {
                    "id": "thread",
                    "individual_note": False,
                    "notes": [
                        _note(2, "reply [file](uploads/b.txt)"),
                        _note(1, "first"),
                        _note(9, "changed state", system=True),
                    ],
                },
                {
                    "id": "duplicate-system",
                    "individual_note": True,
                    "notes": [_note(9, "changed state", system=True)],
                },
            ),
            2: (
                {
                    "id": "task-note",
                    "individual_note": True,
                    "notes": [_note(4, "task [file](uploads/task-comment.txt)")],
                },
            ),
        }

    def iter_project_work_items(
        self, project_id: int, *, updated_after: str | None = None
    ):
        assert project_id == 10
        self.updated_after.append(updated_after)
        yield from self.listed

    def project_issue(self, project_id: int, iid: int):
        assert project_id == 10
        return next(
            (item for item in self.listed if item["iid"] == iid),
            _item(iid, item_type="task" if iid == 2 else "issue"),
        )

    def issue_discussions(self, project_id: int, iid: int):
        assert project_id == 10
        if iid in self.discussion_failures:
            raise DiscoveryError("discussion page 2 failed")
        return self.discussions[iid]

    def issue_links(self, project_id: int, iid: int):
        assert project_id == 10
        if iid == 1:
            return (
                {
                    "id": 102,
                    "iid": 2,
                    "project_id": 10,
                    "title": "Child",
                    "web_url": "https://git.example/root/app/-/work_items/2",
                    "link_type": "blocks",
                },
            )
        return ()

    def work_item_hierarchy(self, project_path: str, iid: int):
        assert project_path == "root/app"
        if iid == 1:
            return WorkItemHierarchy(
                None,
                (
                    {
                        "id": "gid://gitlab/WorkItem/102",
                        "iid": "2",
                        "title": "Child task",
                        "webUrl": "https://git.example/root/app/-/work_items/2",
                    },
                ),
            )
        return WorkItemHierarchy(
            {
                "id": "gid://gitlab/WorkItem/101",
                "iid": "1",
                "title": "Parent issue",
                "webUrl": "https://git.example/root/app/-/issues/1",
            },
            (),
            ("fixture hierarchy coverage only",),
        )


def _exporter(client: Any, store: StateStore, destination: Path) -> WorkItemExporter:
    return WorkItemExporter(
        client,
        store,
        destination,
        overlap_seconds=300,
        full_reconcile_hours=168,
        now=lambda: datetime(2026, 9, 20, 10, tzinfo=UTC),
    )


def test_issue_task_metadata_threads_relationships_and_deterministic_no_rewrite(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    client = FakeWorkItemClient([_item(1), _item(2, item_type="task", state="closed")])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        result = exporter.sync_project(
            10,
            "root/app",
            destination / "content/projects/root/app",
            force_full=False,
            run_started_at="2026-09-20T09:00:00+00:00",
        )
        assert result.status == "ok"
        assert result.exported == 2
        markdown_path = destination / "content/projects/root/app/work-items/1.md"
        raw_path = destination / ".sync/raw/projects/10/work-items/101.json"
        markdown = markdown_path.read_text()
        assert 'title: "Title 1 ---\\nmetadata: safe"' in markdown
        assert 'type: "issue"' in markdown
        assert "global_id: 101" in markdown
        assert "[local](2.md)" in markdown
        assert "https://git.example/root/app/-/uploads/a/file.txt" in markdown
        assert "https://git.example/root/app/-/uploads/b.txt" in markdown
        assert (
            markdown.index("first") < markdown.index("reply") < markdown.index("later")
        )
        assert markdown.count("changed state") == 1
        assert "## System Activity" in markdown
        assert "#note_1" in markdown and "resolved `False`" in markdown
        task = (destination / "content/projects/root/app/work-items/2.md").read_text()
        assert "confidential: true" in task
        assert 'state: "closed"' in task
        assert "fixture hierarchy coverage only" in task
        assert "https://git.example/root/app/-/work_items/2" in task
        assert "https://git.example/root/app/-/uploads/a/file.txt" in task
        assert "https://git.example/root/app/-/uploads/task-comment.txt" in task
        assert "/-/-/uploads/" not in task
        raw = json.loads(raw_path.read_text())
        assert raw["item"]["id"] == 101
        assert "fetched_at" not in raw
        before = (markdown_path.stat().st_mtime_ns, raw_path.stat().st_mtime_ns)

        result = exporter.sync_project(
            10,
            "root/app",
            destination / "content/projects/root/app",
            force_full=False,
            run_started_at="2026-09-20T09:30:00+00:00",
        )
        assert result.full is False
        assert client.updated_after[-1] == "2026-09-20T08:55:00+00:00"
        assert (markdown_path.stat().st_mtime_ns, raw_path.stat().st_mtime_ns) == before


def test_later_discussion_failure_retains_content_queues_retry_and_advances_safely(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    client = FakeWorkItemClient([_item(1)])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        root = destination / "content/projects/root/app"
        exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=False,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        markdown = root / "work-items/1.md"
        raw = destination / ".sync/raw/projects/10/work-items/101.json"
        old = (markdown.read_bytes(), raw.read_bytes())
        client.discussion_failures.add(1)
        result = exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=False,
            run_started_at="2026-09-20T08:30:00+00:00",
        )
        assert result.failures == 1
        assert (markdown.read_bytes(), raw.read_bytes()) == old
        assert store.retry_items("project:10:work-items") == ("1",)
        assert (
            store.get_checkpoint("project:10:work-items", "incremental")
            == "2026-09-20T08:30:00+00:00"
        )


def test_full_refresh_repairs_deleted_note_partial_stays_due_and_full_only_quarantine(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    client = FakeWorkItemClient([_item(1), _item(2, item_type="task")])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        root = destination / "content/projects/root/app"
        exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=False,
            run_started_at="2026-09-20T07:00:00+00:00",
        )
        full_success = store.get_checkpoint("project:10:work-items", "full_success")
        client.discussions[1] = (
            {"id": "thread", "individual_note": False, "notes": [_note(1, "edited")]},
        )
        client.discussion_failures.add(2)
        result = exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=True,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        assert result.full is True and result.failures == 1
        assert (
            store.get_checkpoint("project:10:work-items", "full_success")
            == full_success
        )
        repaired = (root / "work-items/1.md").read_text()
        assert (
            "edited" in repaired and "reply" not in repaired and "later" not in repaired
        )

        client.discussion_failures.clear()
        client.listed = [_item(1)]
        exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=False,
            run_started_at="2026-09-20T08:30:00+00:00",
        )
        assert (root / "work-items/2.md").exists()
        exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=True,
            run_started_at="2026-09-20T09:00:00+00:00",
        )
        assert not (root / "work-items/2.md").exists()
        quarantined = list(destination.glob("stale/work-items/102-*/2.md"))
        assert len(quarantined) == 1
        stale_metadata = json.loads((quarantined[0].parent / "stale.json").read_text())
        assert stale_metadata["object_id"] == 102
        assert store.work_item(10, 2)["missing_from_scope"] is True


def test_interrupted_publication_recovers_from_complete_raw_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    client = FakeWorkItemClient([_item(1)])
    real_write = work_items._atomic_write_text
    calls = 0

    def interrupt(path: Path, content: str) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StateError("interrupted")
        return real_write(path, content)

    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        root = destination / "content/projects/root/app"
        monkeypatch.setattr(work_items, "_atomic_write_text", interrupt)
        first = exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=False,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        assert first.failures == 1
        assert not (root / "work-items/1.md").exists()
        assert (destination / ".sync/raw/projects/10/work-items/101.json").exists()
        second = exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=False,
            run_started_at="2026-09-20T08:30:00+00:00",
        )
        assert second.failures == 0
        assert (root / "work-items/1.md").exists()
        assert store.pending_recoveries("work_item_publication", "project", 10) == ()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": True}, "global ID"),
        ({"iid": 0}, "IID"),
        ({"issue_type": ""}, "type"),
        ({"issue_type": "incident"}, "unexpected"),
        ({"web_url": None}, "URL"),
        ({"updated_at": None}, "timestamp"),
    ],
)
def test_work_item_identity_validation(changes: dict[str, Any], message: str) -> None:
    value = _item(1)
    value.update(changes)
    with pytest.raises(DiscoveryError, match=message):
        work_items._item_identity(value)


def test_renderer_defensive_shapes_people_and_wrapped_uploads() -> None:
    assert (
        work_items.resolve_upload_links(
            "[x](<uploads/a.txt>)", "https://git.example/root/app/issues/1"
        )
        == "[x](<https://git.example/root/app/-/uploads/a.txt>)"
    )
    assert work_items._person(None) == "Unknown"
    assert work_items._person({"name": "Name"}) == "Name"
    assert work_items._person({"username": "user"}) == "@user"
    assert work_items._person({}) == "Unknown"
    assert work_items._notes({"discussions": {}}) == ([], [])
    threads, system = work_items._notes(
        {
            "discussions": [
                "bad",
                {"notes": "bad"},
                {"notes": ["bad", {"id": "bad"}]},
            ]
        }
    )
    assert threads == [] and system == []
    assert work_items._relationship_lines({"relationships": {}})[0].startswith("No")
    assert work_items._relationship_lines({"relationships": ["bad"]})[0].startswith(
        "No"
    )


def test_atomic_markdown_failure_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "item.md"

    def fail_replace(source: str, destination: Path) -> None:
        del destination
        os.unlink(source)
        raise OSError("failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(StateError, match="Markdown"):
        work_items._atomic_write_text(target, "content")
    assert list(tmp_path.glob("*.tmp")) == []


def test_listing_failure_bad_retry_full_due_and_recovery_failure_paths(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"

    class FailedListing(FakeWorkItemClient):
        def iter_project_work_items(self, project_id: int, *, updated_after=None):
            raise DiscoveryError("listing page failed")
            yield  # pragma: no cover

        def project_issue(self, project_id: int, iid: int):
            raise DiscoveryError("retry inaccessible")

    client = FailedListing([])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        assert exporter._full_due("invalid") is True
        store.enqueue_retry("project:10:work-items", "bad", "bad")
        store.enqueue_retry("project:10:work-items", "99", "bad")
        result = exporter.sync_project(
            10,
            "root/app",
            destination / "content/projects/root/app",
            force_full=False,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        assert result.failures == 1
        assert store.get_resource("project", 10, "work_items")["status"] == "error"

        class EmptyWithFailedRetry(FakeWorkItemClient):
            def project_issue(self, project_id: int, iid: int):
                raise DiscoveryError("retry inaccessible")

        exporter.client = EmptyWithFailedRetry([])  # type: ignore[assignment]
        retried = exporter.sync_project(
            10,
            "root/app",
            destination / "content/projects/root/app",
            force_full=True,
            run_started_at="2026-09-20T08:30:00+00:00",
        )
        assert retried.failures == 2

        raw = destination / ".sync/raw/bad.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("not-json")
        encoded = raw.read_bytes()
        common = {
            "global_id": 1,
            "iid": 1,
            "item_type": "issue",
            "web_url": "https://git.example/root/app/-/issues/1",
            "source_updated_at": "now",
            "content_path": str(destination / "content/bad.md"),
            "raw_path": str(raw),
            "content_hash": "wrong",
        }
        store.record_recovery(
            "work_item_publication",
            "project",
            10,
            "prepared",
            details={**common, "raw_hash": "wrong"},
        )
        store.record_recovery(
            "work_item_publication",
            "project",
            10,
            "prepared",
            details={
                **common,
                "raw_hash": hashlib.sha256(encoded).hexdigest(),
            },
        )
        assert exporter._recover_publications(10) == 2
        assert store.pending_recoveries("work_item_publication", "project", 10) == ()


def test_malformed_list_item_is_a_partial_project_failure_without_checkpoint(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    malformed = _item(1)
    malformed["iid"] = 0
    client = FakeWorkItemClient([malformed])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        result = _exporter(client, store, destination).sync_project(
            10,
            "root/app",
            destination / "content/projects/root/app",
            force_full=False,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        assert result.failures == 1
        assert store.get_checkpoint("project:10:work-items", "incremental") is None
        assert store.get_resource("project", 10, "work_items")["status"] == "error"


def test_recovery_content_hash_and_cross_project_local_link(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    client = FakeWorkItemClient([_item(1)])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        root = destination / "content/projects/root/app"
        exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=False,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        raw = destination / ".sync/raw/projects/10/work-items/101.json"
        encoded = raw.read_bytes()
        state_item = store.work_item(10, 1)
        details = {
            "global_id": 101,
            "iid": 1,
            "item_type": "issue",
            "web_url": state_item["web_url"],
            "source_updated_at": state_item["source_updated_at"],
            "content_path": state_item["content_path"],
            "raw_path": str(raw),
            "content_hash": "wrong",
            "raw_hash": hashlib.sha256(encoded).hexdigest(),
        }
        store.record_recovery(
            "work_item_publication",
            "project",
            10,
            "prepared",
            details=details,
        )
        assert exporter._recover_publications(10) == 1

        target = destination / "content/projects/root/other/work-items/2.md"
        store.upsert_work_item(
            global_id=202,
            project_id=20,
            iid=2,
            item_type="task",
            web_url="https://git.example/root/other/-/issues/2",
            content_path=str(target),
            raw_path="raw",
            source_updated_at="now",
            content_hash="hash",
            status="ok",
            last_attempt_at="now",
            last_success_at="now",
        )
        store.upsert_object("project", 20, "root/renamed-other")
        local = exporter._local_link(10, root / "work-items/1.md", 202, 20, 2, {1})
        assert local == "../../renamed-other/work-items/2.md"
        store.upsert_object("project", 20, "../unsafe")
        assert (
            exporter._local_link(10, root / "work-items/1.md", 202, 20, 2, {1}) is None
        )


def test_contained_recovery_hash_json_and_relative_link_branches(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    client = FakeWorkItemClient([_item(1)])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        with pytest.raises(StateError, match="unsafe work-item"):
            exporter._export_item(10, "root/app", tmp_path / "outside", _item(1), {1})

        root = destination / "content/projects/root/app"
        exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=False,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        item = store.work_item(10, 1)
        raw = Path(item["raw_path"])
        content = Path(item["content_path"])
        encoded = raw.read_bytes()
        details = {
            "global_id": item["global_id"],
            "iid": item["iid"],
            "item_type": item["item_type"],
            "web_url": item["web_url"],
            "source_updated_at": item["source_updated_at"],
            "content_path": str(content),
            "raw_path": str(raw),
            "content_hash": item["content_hash"],
            "raw_hash": hashlib.sha256(encoded).hexdigest(),
        }
        store.record_recovery(
            "work_item_publication",
            "project",
            10,
            "prepared",
            source_path=str(raw.relative_to(destination)),
            destination_path=str(content.relative_to(destination)),
            details={**details, "raw_hash": "wrong"},
        )
        store.record_recovery(
            "work_item_publication",
            "project",
            10,
            "prepared",
            source_path=str(raw.relative_to(destination)),
            destination_path=str(content.relative_to(destination)),
            details={**details, "content_hash": "wrong"},
        )
        malformed = destination / ".sync/raw/malformed.json"
        malformed.write_text("not-json")
        store.record_recovery(
            "work_item_publication",
            "project",
            10,
            "prepared",
            source_path=str(malformed.relative_to(destination)),
            destination_path=str(content.relative_to(destination)),
            details={
                **details,
                "raw_hash": hashlib.sha256(malformed.read_bytes()).hexdigest(),
            },
        )
        assert exporter._recover_publications(10) == 2

        relative_target = "content/projects/root/other/work-items/2.md"
        store.upsert_work_item(
            global_id=303,
            project_id=30,
            iid=2,
            item_type="issue",
            web_url="https://git.example/root/other/-/issues/2",
            content_path=relative_target,
            raw_path=".sync/raw/303.json",
            source_updated_at="now",
            content_hash="hash",
            status="ok",
            last_attempt_at="now",
            last_success_at="now",
        )
        assert exporter._local_link(10, content, 303, 30, 2, {1}).endswith(
            "../../other/work-items/2.md"
        )


def test_iid_reuse_by_different_global_id_quarantines_old_item(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    client = FakeWorkItemClient([_item(1)])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        root = destination / "content/projects/root/app"
        exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=True,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        replacement = _item(1)
        replacement["id"] = 999
        replacement["title"] = "Replacement identity"
        client.listed = [replacement]
        exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=True,
            run_started_at="2026-09-20T09:00:00+00:00",
        )

        assert "Replacement identity" in (root / "work-items/1.md").read_text()
        assert store.work_item(10, 1)["global_id"] == 999
        assert store.work_item_by_global_id(101)["missing_from_scope"] is True
        quarantined = list(destination.glob("stale/work-items/101-*/1.md"))
        assert len(quarantined) == 1
        metadata = json.loads((quarantined[0].parent / "stale.json").read_text())
        assert metadata["reason"] == "iid_reused_by_another_id"
        assert metadata["prior_raw_path"].endswith("/101.json")
        assert (destination / ".sync/raw/projects/10/work-items/101.json").exists()
        assert (destination / ".sync/raw/projects/10/work-items/999.json").exists()


def test_failed_missing_item_quarantine_is_counted_and_retains_content(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "corpus"
    client = FakeWorkItemClient([_item(1)])
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(client, store, destination)
        root = destination / "content/projects/root/app"
        first = exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=True,
            run_started_at="2026-09-20T08:00:00+00:00",
        )
        assert first.failures == 0
        full_success = store.get_checkpoint("project:10:work-items", "full_success")
        active = root / "work-items/1.md"
        destination.joinpath("stale/work-items").write_text(
            "blocks quarantine directories"
        )
        client.listed = []

        result = exporter.sync_project(
            10,
            "root/app",
            root,
            force_full=True,
            run_started_at="2026-09-20T09:00:00+00:00",
        )

        assert result.status == "error"
        assert result.failures == 1
        assert active.is_file()
        state_item = store.work_item(10, 1)
        assert state_item is not None
        assert state_item["missing_from_scope"] is False
        assert (
            store.get_checkpoint("project:10:work-items", "full_success")
            == full_success
        )
        resource = store.get_resource("project", 10, "work_items")
        assert resource is not None
        assert resource["retained_content"] is True
        assert "1 quarantine operation(s)" in resource["last_error"]
        assert "later full reconciliation" in resource["last_error"]
        assert str(destination) not in resource["last_error"]


def test_quarantine_rejects_persisted_path_outside_destination(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        exporter = _exporter(FakeWorkItemClient([]), store, destination)
        item = {
            "global_id": 1,
            "project_id": 10,
            "iid": 1,
            "item_type": "issue",
            "web_url": "https://git.example/root/app/-/issues/1",
            "content_path": str(tmp_path / "outside.md"),
            "raw_path": ".sync/raw/1.json",
            "source_updated_at": "now",
            "content_hash": "hash",
            "last_success_at": "now",
        }
        with pytest.raises(StateError, match="unsafe persisted"):
            exporter._quarantine_item(item, reason="test", evidence="test")
