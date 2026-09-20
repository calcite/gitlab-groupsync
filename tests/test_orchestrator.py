"""Synchronization orchestration, durable outcomes, and isolation tests."""

import json
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from gitlab_groupsync import orchestrator
from gitlab_groupsync.git_sync import (
    GitResourceResult,
    GitRunner,
    GitSyncError,
    LocalConflictError,
)
from gitlab_groupsync.gitlab_api import (
    DiscoveryError,
    GroupWikiPages,
    Inventory,
    InventoryObject,
    ProjectDetails,
    WikiProbe,
    WorkItemHierarchy,
)
from gitlab_groupsync.group_wikis import GroupWikiSyncResult
from gitlab_groupsync.orchestrator import SyncOrchestrator, SyncSetupError, run_sync
from gitlab_groupsync.reconcile import ReconcileError, ensure_object_directory
from gitlab_groupsync.state import (
    DestinationLock,
    LockContentionError,
    StateError,
    StateStore,
)
from gitlab_groupsync.work_items import WorkItemSyncResult


def _inventory(*projects: tuple[int, str], root_id: int = 1) -> Inventory:
    root = InventoryObject(root_id, "root")
    return Inventory(
        root,
        (root,),
        tuple(InventoryObject(project_id, path) for project_id, path in projects),
        True,
    )


def _config(destination: Path, projects: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "gitlab": {
            "url": "https://git.example",
            "group": "root",
            "token_env": "TOKEN",
            "token_file": None,
            "git_transport": "https",
            "ca_bundle": None,
        },
        "storage": {"destination": str(destination)},
        "sync": {
            "include_shared_projects": False,
            "include_archived_projects": True,
            "api_timeout_seconds": 3,
            "git_timeout_seconds": 4,
            "max_attempts": 1,
        },
        "inventory": {
            "root_group": {"id": 1, "full_path": "root"},
            "groups": [{"id": 1, "full_path": "root", "wiki": False}],
            "projects": projects,
        },
    }


def _selection(
    project_id: int,
    path: str,
    *,
    repository: bool = True,
    wiki: bool = True,
) -> dict[str, Any]:
    return {
        "id": project_id,
        "full_path": path,
        "repository": repository,
        "wiki": wiki,
        "work_items": False,
    }


class FakeClient:
    def __init__(
        self,
        details: dict[int, ProjectDetails],
        probes: dict[int, Any],
        group_wikis: dict[int, GroupWikiPages | Exception] | None = None,
    ):
        self.details = details
        self.probes = probes
        self.group_wikis = group_wikis or {}
        self.group_wiki_calls: list[int] = []

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def project_details(self, project_id: int) -> ProjectDetails:
        value = self.details[project_id]
        if isinstance(value, Exception):
            raise value
        return value

    def probe_project_wiki(self, project_id: int) -> WikiProbe:
        value = self.probes[project_id]
        if isinstance(value, Exception):
            raise value
        return value

    def group_wiki_pages(self, group_id: int) -> GroupWikiPages:
        self.group_wiki_calls.append(group_id)
        value = self.group_wikis[group_id]
        if isinstance(value, Exception):
            raise value
        return value


class FakeGit:
    def __init__(self, failures: dict[str, Exception] | None = None) -> None:
        self.failures = failures or {}
        self.calls: list[tuple[str, str | None]] = []

    def remote_head(
        self,
        remote: str,
        *,
        token: str | None = None,
        resource_key: str | None = None,
    ):
        del resource_key
        self.calls.append(("head", token))
        failure = self.failures.get("head")
        if failure:
            raise failure
        return ("wiki-main", "wiki-revision")

    def sync(
        self,
        destination: Path,
        remote: str,
        branch: str,
        resource_key: str,
        *,
        token: str | None = None,
    ) -> GitResourceResult:
        del remote, resource_key
        kind = destination.name
        self.calls.append((kind, token))
        failure = self.failures.get(kind)
        if failure:
            raise failure
        return GitResourceResult("ok", f"{kind}-revision", branch)


def _details(
    project_id: int,
    path: str,
    *,
    empty: bool = False,
    wiki_enabled: bool = True,
) -> ProjectDetails:
    return ProjectDetails(
        project_id,
        path,
        None if empty else "main",
        empty,
        f"git@git.example:{path}.git",
        f"https://git.example/{path}.git",
        wiki_enabled,
    )


def test_drift_success_manifest_metadata_and_independent_wiki_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    config = _config(destination, [_selection(10, "root/old")])
    live = _inventory((10, "root/new"), (20, "root/added"))
    monkeypatch.setattr(orchestrator, "discover_inventory", lambda *a, **k: live)
    client = FakeClient({10: _details(10, "root/new")}, {10: WikiProbe(200, 1)})
    git = FakeGit({"wiki": GitSyncError("wiki fetch failed")})
    messages: list[str] = []

    result = SyncOrchestrator(
        config,
        "secret",
        client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
        git=git,  # type: ignore[arg-type]
        report=messages.append,
    ).run()

    assert result == 1
    assert "run gl-groupsync discover" in messages[0]
    metadata = json.loads(
        (destination / "content/projects/root/new/project.json").read_text()
    )
    assert metadata["resources"]["repository"]["status"] == "ok"
    assert metadata["resources"]["wiki"]["status"] == "error"
    assert metadata["resources"]["repository"]["revision"] == "repository-revision"
    assert metadata["resources"]["repository"]["branch"] == "main"
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["run_state"]["latest"]["outcome"] == "partial"
    assert manifest["drift"]["renamed"][0]["id"] == 10
    assert (destination / "SEARCH_GUIDE.md").is_file()
    assert ("repository", "secret") in git.calls
    assert ("wiki", "secret") in git.calls


def test_git_failure_persists_actionable_redacted_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    config = _config(
        destination, [_selection(10, "root/app", repository=True, wiki=False)]
    )
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *a, **k: _inventory((10, "root/app"))
    )
    client = FakeClient({10: _details(10, "root/app")}, {})
    failed = tmp_path / "failed-git"
    failed.write_text(
        "#!/bin/sh\n"
        "printf 'remote rejected %s\\n' \"$GL_GROUPSYNC_GIT_TOKEN\" >&2\n"
        "exit 1\n"
    )
    failed.chmod(0o700)

    class FailedGit:
        def sync(
            self,
            checkout: Path,
            remote: str,
            branch: str,
            resource_key: str,
            *,
            token: str | None = None,
        ) -> GitResourceResult:
            del remote, branch
            GitRunner(2, executable=str(failed)).run(
                ["-C", str(checkout), "fetch"],
                token=token,
                resource_key=resource_key,
            )
            raise AssertionError("failed command returned")

    assert (
        SyncOrchestrator(
            config,
            "operator-secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FailedGit(),  # type: ignore[arg-type]
        ).run()
        == 1
    )
    with StateStore(destination / ".sync/state.sqlite3", read_only=True) as store:
        last_error = store.get_resource("project", 10, "repository")["last_error"]
    assert "operator-secret" not in last_error
    assert "project:10:repository: Git operation failed (fetch)" in last_error
    assert "stderr: remote rejected [REDACTED]" in last_error
    manifest = (destination / "manifest.json").read_text()
    assert "operator-secret" not in manifest
    assert "remote rejected [REDACTED]" in manifest


def test_empty_disabled_inaccessible_transient_and_local_conflict_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selections = [
        _selection(1, "root/empty"),
        _selection(2, "root/forbidden", repository=False),
        _selection(3, "root/transient", repository=False),
        _selection(4, "root/conflict", wiki=False),
    ]
    config = _config(tmp_path / "corpus", selections)
    live = _inventory(*((item["id"], item["full_path"]) for item in selections))
    monkeypatch.setattr(orchestrator, "discover_inventory", lambda *a, **k: live)
    client = FakeClient(
        {
            1: _details(1, "root/empty", empty=True, wiki_enabled=False),
            2: _details(2, "root/forbidden"),
            3: _details(3, "root/transient"),
            4: _details(4, "root/conflict"),
        },
        {
            1: WikiProbe(200, 0),
            2: WikiProbe(403, None),
            3: DiscoveryError("temporary wiki failure"),
            4: WikiProbe(200, 0),
        },
    )
    git = FakeGit({"repository": LocalConflictError("local changes")})
    result = SyncOrchestrator(
        config,
        "secret",
        client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
        git=git,  # type: ignore[arg-type]
    ).run()
    assert result == 1
    with StateStore(config["storage"]["destination"] + "/.sync/state.sqlite3") as store:
        assert store.get_resource("project", 1, "repository")["status"] == "empty"
        assert store.get_resource("project", 1, "wiki")["status"] == "disabled"
        assert store.get_resource("project", 2, "wiki")["status"] == "unavailable"
        assert store.get_resource("project", 3, "wiki")["status"] == "error"
        assert (
            store.get_resource("project", 4, "repository")["status"] == "local_conflict"
        )
        assert store.get_resource("project", 2, "repository")["status"] == "disabled"


def test_no_selected_components_no_project_requests_and_no_drift_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = _selection(1, "root/app", repository=False, wiki=False)
    config = _config(tmp_path / "corpus", [selection])
    live = _inventory((1, "root/app"))
    monkeypatch.setattr(orchestrator, "discover_inventory", lambda *a, **k: live)
    client = FakeClient({}, {})
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit(),  # type: ignore[arg-type]
        ).run()
        == 0
    )
    assert not (tmp_path / "corpus/content/projects/root/app").exists()
    assert (tmp_path / "corpus/SEARCH_GUIDE.md").is_file()
    assert client.group_wiki_calls == []
    group_metadata = json.loads(
        (tmp_path / "corpus/content/groups/root/group.json").read_text()
    )
    assert group_metadata["resources"]["wiki"]["status"] == "disabled"
    assert "no Group Wikis API request" in group_metadata["wiki_evidence"]


def test_root_nested_projectless_group_wikis_and_project_continue_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    config = _config(destination, [_selection(10, "root/app", wiki=False)])
    config["inventory"]["groups"] = [
        {"id": 1, "full_path": "root", "wiki": True},
        {"id": 2, "full_path": "root/projectless", "wiki": True},
    ]
    root = InventoryObject(1, "root")
    live = Inventory(
        root,
        (root, InventoryObject(2, "root/projectless")),
        (InventoryObject(10, "root/app"),),
        True,
    )
    monkeypatch.setattr(orchestrator, "discover_inventory", lambda *a, **k: live)
    page = {
        "slug": "home",
        "title": "Home",
        "format": "markdown",
        "encoding": "UTF-8",
        "content": "projectless docs",
    }
    client = FakeClient(
        {10: _details(10, "root/app")},
        {},
        {
            1: GroupWikiPages(404, None),
            2: GroupWikiPages(200, (page,)),
        },
    )
    git = FakeGit()
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=git,  # type: ignore[arg-type]
        ).run()
        == 1
    )
    assert client.group_wiki_calls == [1, 2]
    assert (
        destination / "content/groups/root/projectless/wiki/home.md"
    ).read_text() == "projectless docs"
    assert ("repository", "secret") in git.calls
    root_metadata = json.loads(
        (destination / "content/groups/root/group.json").read_text()
    )
    assert root_metadata["resources"]["wiki"]["status"] == "unavailable"
    manifest = json.loads((destination / "manifest.json").read_text())
    details = manifest["coverage"]["details"]
    group_details = [item for item in details if item["object_kind"] == "group"]
    assert [item["status"] for item in group_details] == ["unavailable", "ok"]
    assert all(
        "fixtures only" in " ".join(item["limitations"]) for item in group_details
    )


@pytest.mark.parametrize("selected", [False, True])
def test_group_path_collision_makes_only_selected_group_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selected: bool
) -> None:
    destination = tmp_path / str(selected)
    collision = destination / "content/groups/root"
    collision.mkdir(parents=True)
    config = _config(destination, [])
    config["inventory"]["groups"] = [{"id": 1, "full_path": "root", "wiki": selected}]
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *a, **k: _inventory()
    )
    client = FakeClient({}, {})
    result = SyncOrchestrator(
        config,
        "secret",
        client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
        git=FakeGit(),  # type: ignore[arg-type]
    ).run()
    assert result == int(selected)
    assert client.group_wiki_calls == []
    with StateStore(destination / ".sync/state.sqlite3") as store:
        resource = store.get_resource("group", 1, "wiki")
        assert resource["status"] == ("error" if selected else "disabled")


def test_catalog_group_absent_from_live_makes_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "corpus", [])
    config["inventory"]["groups"].append(
        {"id": 99, "full_path": "root/absent", "wiki": True}
    )
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *a, **k: _inventory()
    )
    client = FakeClient({}, {})
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit(),  # type: ignore[arg-type]
        ).run()
        == 0
    )
    assert client.group_wiki_calls == []


def test_setup_discovery_identity_project_details_and_path_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "corpus", [_selection(1, "root/app")])
    client = FakeClient({1: DiscoveryError("details failed")}, {})  # type: ignore[dict-item]
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *a, **k: _inventory((1, "root/app"))
    )
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit(),  # type: ignore[arg-type]
        ).run()
        == 1
    )

    wrong = deepcopy(config)
    wrong["storage"]["destination"] = str(tmp_path / "wrong")
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *a, **k: _inventory(root_id=2)
    )
    with pytest.raises(SyncSetupError, match="root group ID"):
        SyncOrchestrator(
            wrong,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
        ).run()

    missing = deepcopy(config)
    missing["inventory"] = {"root_group": None, "groups": [], "projects": []}
    with pytest.raises(SyncSetupError, match="run discover"):
        SyncOrchestrator(missing, "secret").run()

    monkeypatch.setattr(
        orchestrator,
        "discover_inventory",
        lambda *a, **k: (_ for _ in ()).throw(DiscoveryError("live failed")),
    )
    with pytest.raises(SyncSetupError, match="live failed"):
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
        ).run()


def test_additional_resource_outcomes_retention_and_path_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = _selection(1, "root/app")
    live = _inventory((1, "root/app"))
    monkeypatch.setattr(orchestrator, "discover_inventory", lambda *a, **k: live)
    client = FakeClient({1: _details(1, "root/app")}, {1: WikiProbe(200, 1)})
    destination = tmp_path / "success"
    config = _config(destination, [selection])
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit(),  # type: ignore[arg-type]
        ).run()
        == 0
    )

    # A later repository failure retains its last successful revision independently.
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit({"repository": GitSyncError("fetch failed")}),  # type: ignore[arg-type]
        ).run()
        == 1
    )
    with StateStore(destination / ".sync/state.sqlite3") as store:
        repository = store.get_resource("project", 1, "repository")
        assert repository["status"] == "error"
        assert repository["revision"] == "repository-revision"
        assert repository["retained_content"] is True
        assert store.get_resource("project", 1, "wiki")["status"] == "ok"

    empty_config = _config(tmp_path / "empty-wiki", [selection])
    empty_client = FakeClient({1: _details(1, "root/app")}, {1: WikiProbe(200, 0)})
    assert (
        SyncOrchestrator(
            empty_config,
            "secret",
            client_factory=lambda *a, **k: empty_client,  # type: ignore[arg-type]
            git=FakeGit(),  # type: ignore[arg-type]
        ).run()
        == 0
    )

    class EmptyHeadGit(FakeGit):
        def remote_head(
            self,
            remote: str,
            *,
            token: str | None = None,
            resource_key: str | None = None,
        ):
            del remote, token, resource_key
            return None

    no_head_config = _config(tmp_path / "no-head", [selection])
    assert (
        SyncOrchestrator(
            no_head_config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=EmptyHeadGit(),  # type: ignore[arg-type]
        ).run()
        == 1
    )

    conflict_config = _config(tmp_path / "wiki-conflict", [selection])
    assert (
        SyncOrchestrator(
            conflict_config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit({"wiki": LocalConflictError("wiki local")}),  # type: ignore[arg-type]
        ).run()
        == 1
    )

    collision = tmp_path / "collision/content/projects/root/app"
    collision.mkdir(parents=True)
    collision_config = _config(tmp_path / "collision", [selection])
    assert (
        SyncOrchestrator(
            collision_config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit(),  # type: ignore[arg-type]
        ).run()
        == 1
    )


def test_absent_selection_and_fatal_run_are_durably_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "corpus", [_selection(99, "root/absent")])
    live = _inventory()
    monkeypatch.setattr(orchestrator, "discover_inventory", lambda *a, **k: live)
    client = FakeClient({}, {})
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit(),  # type: ignore[arg-type]
        ).run()
        == 0
    )

    broken = _config(tmp_path / "broken", [])
    instance = SyncOrchestrator(
        broken,
        "secret",
        client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        instance,
        "_run_resources",
        lambda *args: (_ for _ in ()).throw(RuntimeError("fatal")),
    )
    with pytest.raises(RuntimeError, match="fatal"):
        instance.run()
    with StateStore(tmp_path / "broken/.sync/state.sqlite3") as store:
        assert store.status_snapshot()["latest_run"]["outcome"] == "failed"


def test_discovery_without_state_state_mismatch_and_failed_record_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "absent", [])
    client = FakeClient({}, {})
    monkeypatch.setattr(
        orchestrator,
        "discover_inventory",
        lambda *a, **k: (_ for _ in ()).throw(DiscoveryError("offline")),
    )
    instance = SyncOrchestrator(
        config,
        "secret",
        client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
    )
    with pytest.raises(SyncSetupError, match="offline"):
        instance.run()

    mismatch = tmp_path / "mismatch"
    with StateStore.initialize_destination(mismatch, "https://other.example", 1):
        pass
    mismatch_config = _config(mismatch, [])
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *a, **k: _inventory()
    )
    with pytest.raises(SyncSetupError, match="different GitLab"):
        SyncOrchestrator(
            mismatch_config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
        ).run()

    database = tmp_path / "broken/.sync/state.sqlite3"
    database.parent.mkdir(parents=True)
    database.touch()
    broken = SyncOrchestrator(_config(tmp_path / "broken", []), "secret")

    def fail_store(path: Path) -> None:
        del path
        raise StateError("broken")

    monkeypatch.setattr(orchestrator, "StateStore", fail_store)
    broken._record_failed_discovery()


def test_run_sync_acquires_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path / "corpus", [])
    monkeypatch.setattr(SyncOrchestrator, "run", lambda self: 0)
    assert run_sync(config, "secret", report=lambda message: None) == 0
    with DestinationLock(config["storage"]["destination"]):
        with pytest.raises(LockContentionError):
            run_sync(config, "secret", report=lambda message: None)


def test_work_items_are_selected_independently_and_receive_full_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = _selection(1, "root/app", repository=False, wiki=False)
    selection["work_items"] = True
    config = _config(tmp_path / "corpus", [selection])
    config["sync"].update(incremental_overlap_seconds=42, full_reconcile_hours=24)
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *a, **k: _inventory((1, "root/app"))
    )
    calls: list[tuple[Any, ...]] = []

    class FakeExporter:
        def __init__(self, client: Any, store: Any, destination: Any, **kwargs: Any):
            calls.append((client, store, destination, kwargs))

        def sync_project(self, *args: Any, **kwargs: Any) -> WorkItemSyncResult:
            calls.append((*args, kwargs))
            return WorkItemSyncResult("ok", 2, 0, True, ("limited",))

        def recover(self, project_id: int) -> int:
            calls.append(("recover", project_id))
            return 0

    monkeypatch.setattr(orchestrator, "WorkItemExporter", FakeExporter)
    client = FakeClient({}, {})
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=FakeGit(),  # type: ignore[arg-type]
            full=True,
        ).run()
        == 0
    )
    assert calls[0][3] == {"overlap_seconds": 42, "full_reconcile_hours": 24}
    assert calls[2][0:3] == (
        1,
        "root/app",
        tmp_path / "corpus/content/projects/root/app",
    )
    assert calls[2][3]["force_full"] is True
    metadata = json.loads(
        (tmp_path / "corpus/content/projects/root/app/project.json").read_text()
    )
    assert metadata["resources"]["repository"]["status"] == "disabled"
    assert metadata["resources"]["wiki"]["status"] == "disabled"


def test_project_rename_forces_complete_work_item_refresh_and_updates_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    selection = _selection(10, "root/old", repository=False, wiki=False)
    selection["work_items"] = True
    config = _config(destination, [selection])
    inventories = iter(
        (
            _inventory((10, "root/old")),
            Inventory(
                InventoryObject(1, "renamed-root"),
                (InventoryObject(1, "renamed-root"),),
                (InventoryObject(10, "renamed-root/app"),),
                True,
            ),
        )
    )
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *args, **kwargs: next(inventories)
    )

    class RenameClient(FakeClient):
        project_full_path = "root/old"

        def __init__(self) -> None:
            super().__init__({}, {})
            self.updated_after: list[str | None] = []

        def iter_project_work_items(
            self, project_id: int, *, updated_after: str | None = None
        ):
            assert project_id == 10
            self.updated_after.append(updated_after)
            for iid in (1, 2):
                yield {
                    "id": 100 + iid,
                    "iid": iid,
                    "project_id": 10,
                    "issue_type": "issue",
                    "title": f"Item {iid}",
                    "state": "opened",
                    "description": "[attachment](/uploads/file.txt)",
                    "web_url": (
                        f"https://git.example/{self.project_full_path}/-/issues/{iid}"
                    ),
                    "author": None,
                    "assignees": [],
                    "labels": [],
                    "milestone": None,
                    "confidential": False,
                    "created_at": "2026-09-19T08:00:00+00:00",
                    "updated_at": "2026-09-20T08:00:00+00:00",
                    "closed_at": None,
                }

        def issue_discussions(self, project_id: int, iid: int):
            return ()

        def issue_links(self, project_id: int, iid: int):
            if iid == 1:
                return (
                    {
                        "id": 102,
                        "iid": 2,
                        "project_id": 10,
                        "title": "Item 2",
                        "web_url": (
                            f"https://git.example/{self.project_full_path}/-/issues/2"
                        ),
                        "link_type": "related",
                    },
                )
            return ()

        def work_item_hierarchy(self, project_path: str, iid: int):
            assert project_path == self.project_full_path
            return WorkItemHierarchy(None, ())

    client = RenameClient()
    first = SyncOrchestrator(
        config,
        "secret",
        client_factory=lambda *args, **kwargs: client,  # type: ignore[arg-type]
        git=FakeGit(),  # type: ignore[arg-type]
    ).run()
    assert first == 0
    with StateStore(destination / ".sync/state.sqlite3") as store:
        assert store.get_checkpoint("project:10:work-items", "full_success") is not None

    client.project_full_path = "renamed-root/app"
    second = SyncOrchestrator(
        config,
        "secret",
        client_factory=lambda *args, **kwargs: client,  # type: ignore[arg-type]
        git=FakeGit(),  # type: ignore[arg-type]
    ).run()

    assert second == 0
    assert client.updated_after == [None, None]
    assert not (destination / "content/projects/root/old").exists()
    assert not (destination / "content/groups/root/group.json").exists()
    item_path = destination / "content/projects/renamed-root/app/work-items/1.md"
    markdown = item_path.read_text()
    assert 'project_path: "renamed-root/app"' in markdown
    assert "Project: `renamed-root/app`" in markdown
    assert "https://git.example/renamed-root/app/-/issues/1" in markdown
    assert "https://git.example/renamed-root/app/-/uploads/file.txt" in markdown
    assert "[local](2.md)" in markdown
    assert "root/old" not in markdown
    raw = json.loads(
        (destination / ".sync/raw/projects/10/work-items/101.json").read_text()
    )
    assert raw["project_path"] == "renamed-root/app"
    assert "root/old" not in json.dumps(raw)
    project_metadata = json.loads(
        (destination / "content/projects/renamed-root/app/project.json").read_text()
    )
    group_metadata = json.loads(
        (destination / "content/groups/renamed-root/group.json").read_text()
    )
    assert project_metadata["full_path"] == "renamed-root/app"
    assert project_metadata["resources"]["work_items"]["revision"] is None
    assert project_metadata["resources"]["work_items"]["item_count"] == 2
    assert group_metadata["full_path"] == "renamed-root"
    manifest = json.loads((destination / "manifest.json").read_text())
    work_items = next(
        detail
        for detail in manifest["coverage"]["details"]
        if detail["kind"] == "work_items"
    )
    assert work_items["revision"] is None and work_items["item_count"] == 2
    with StateStore(destination / ".sync/state.sqlite3") as store:
        item = store.work_item(10, 1)
        assert item["content_path"] == str(item_path)
        latest = store.status_snapshot()["latest_run"]["started_at"]
        assert store.get_checkpoint("project:10:work-items", "incremental") == latest
        assert store.get_checkpoint("project:10:work-items", "full_success") == latest


def test_work_item_failure_and_path_failure_are_partial_but_do_not_block_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection = _selection(1, "root/app", wiki=False)
    selection["work_items"] = True
    config = _config(tmp_path / "corpus", [selection])
    monkeypatch.setattr(
        orchestrator, "discover_inventory", lambda *a, **k: _inventory((1, "root/app"))
    )

    class FailedExporter:
        def __init__(self, *args: Any, **kwargs: Any):
            pass

        def sync_project(self, *args: Any, **kwargs: Any) -> WorkItemSyncResult:
            return WorkItemSyncResult("error", 0, 1, True, ())

        def recover(self, project_id: int) -> int:
            return 0

    monkeypatch.setattr(orchestrator, "WorkItemExporter", FailedExporter)
    client = FakeClient({1: _details(1, "root/app")}, {})
    git = FakeGit()
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=git,  # type: ignore[arg-type]
        ).run()
        == 1
    )
    assert ("repository", "secret") in git.calls

    collision = tmp_path / "collision/content/projects/root/app"
    collision.mkdir(parents=True)
    collision_config = _config(tmp_path / "collision", [selection])
    assert (
        SyncOrchestrator(
            collision_config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=git,  # type: ignore[arg-type]
        ).run()
        == 1
    )
    with StateStore(tmp_path / "collision/.sync/state.sqlite3") as store:
        assert store.get_resource("project", 1, "work_items")["status"] == "error"


def test_quarantine_failure_is_partial_and_other_project_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "corpus"
    selections = [
        _selection(1, "root/one", repository=False, wiki=False),
        _selection(2, "root/two", repository=False, wiki=False),
    ]
    for selection in selections:
        selection["work_items"] = True
    config = _config(destination, selections)
    live = _inventory((1, "root/one"), (2, "root/two"))
    monkeypatch.setattr(orchestrator, "discover_inventory", lambda *a, **k: live)

    def item(project_id: int, project_path: str) -> dict[str, Any]:
        return {
            "id": project_id * 100 + 1,
            "iid": 1,
            "project_id": project_id,
            "issue_type": "issue",
            "title": f"Project {project_id} item",
            "state": "opened",
            "description": "retained",
            "web_url": f"https://git.example/{project_path}/-/issues/1",
            "author": None,
            "assignees": [],
            "labels": [],
            "milestone": None,
            "confidential": False,
            "created_at": "2026-09-19T08:00:00+00:00",
            "updated_at": "2026-09-20T08:00:00+00:00",
            "closed_at": None,
        }

    class WorkItemClient(FakeClient):
        def __init__(self) -> None:
            super().__init__({}, {})
            self.items = {
                1: [item(1, "root/one")],
                2: [item(2, "root/two")],
            }
            self.listing_calls: list[int] = []

        def iter_project_work_items(
            self, project_id: int, *, updated_after: str | None = None
        ):
            del updated_after
            self.listing_calls.append(project_id)
            yield from self.items[project_id]

        def project_issue(self, project_id: int, iid: int):
            return next(
                value for value in self.items[project_id] if value["iid"] == iid
            )

        def issue_discussions(self, project_id: int, iid: int):
            del project_id, iid
            return ()

        def issue_links(self, project_id: int, iid: int):
            del project_id, iid
            return ()

        def work_item_hierarchy(self, project_path: str, iid: int):
            del project_path, iid
            return WorkItemHierarchy(None, ())

    client = WorkItemClient()
    first = SyncOrchestrator(
        config,
        "secret",
        client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
        git=FakeGit(),  # type: ignore[arg-type]
    ).run()
    assert first == 0

    client.items[1] = []
    destination.joinpath("stale/work-items").write_text("blocks quarantine directories")
    calls_before = len(client.listing_calls)
    second = SyncOrchestrator(
        config,
        "secret",
        client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
        git=FakeGit(),  # type: ignore[arg-type]
        full=True,
    ).run()

    assert second == 1
    assert client.listing_calls[calls_before:] == [1, 2]
    assert (destination / "content/projects/root/one/work-items/1.md").is_file()
    assert (destination / "content/projects/root/two/work-items/1.md").is_file()
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["run_state"]["latest"]["outcome"] == "partial"
    assert manifest["run_state"]["latest"]["exit_code"] == 1
    with StateStore(destination / ".sync/state.sqlite3") as store:
        failed = store.get_resource("project", 1, "work_items")
        assert failed is not None
        assert failed["status"] == "error"
        assert failed["retained_content"] is True
        assert "quarantine operation(s)" in failed["last_error"]
        assert str(destination) not in failed["last_error"]
        successful = store.get_resource("project", 2, "work_items")
        assert successful is not None
        assert successful["status"] == "ok"


def test_project_workers_are_bounded_and_state_writes_remain_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = [
        _selection(number, f"root/p{number}", wiki=False) for number in range(1, 7)
    ]
    config = _config(tmp_path / "corpus", projects)
    config["sync"]["workers"] = 2
    monkeypatch.setattr(
        orchestrator,
        "discover_inventory",
        lambda *a, **k: _inventory(
            *((item["id"], item["full_path"]) for item in projects)
        ),
    )
    lock = threading.Lock()
    active = 0
    maximum = 0

    class ConcurrentGit(FakeGit):
        def sync(self, *args: Any, **kwargs: Any) -> GitResourceResult:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            try:
                return super().sync(*args, **kwargs)
            finally:
                with lock:
                    active -= 1

    client = FakeClient(
        {item["id"]: _details(item["id"], item["full_path"]) for item in projects},
        {},
    )
    assert (
        SyncOrchestrator(
            config,
            "secret",
            client_factory=lambda *a, **k: client,  # type: ignore[arg-type]
            git=ConcurrentGit(),  # type: ignore[arg-type]
        ).run()
        == 0
    )
    assert maximum == 2
    with StateStore(tmp_path / "corpus/.sync/state.sqlite3") as store:
        assert len(store.objects("project")) == 6


@pytest.mark.parametrize("case", ["repository", "wiki-disabled", "wiki-empty"])
def test_conclusive_transition_collision_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    destination = tmp_path / case
    config = _config(destination, [])
    instance = SyncOrchestrator(config, "secret", git=FakeGit())  # type: ignore[arg-type]
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        base = ensure_object_directory(destination, "project", "root/app", 1)

        def fail_retire(*args: Any, **kwargs: Any) -> bool:
            raise ReconcileError("unsafe retained collision")

        monkeypatch.setattr(
            orchestrator.LifecycleReconciler, "retire_component", fail_retire
        )
        details = _details(
            1,
            "root/app",
            empty=case == "repository",
            wiki_enabled=case != "wiki-disabled",
        )
        if case == "repository":
            result = instance._sync_repository(store, base, details)
            kind = "repository"
        else:
            client = FakeClient({1: details}, {1: WikiProbe(200, 0)})
            result = instance._sync_wiki(client, store, base, details)  # type: ignore[arg-type]
            kind = "wiki"
        assert result == 1
        assert store.get_resource("project", 1, kind)["status"] == "error"


def test_project_detail_path_change_is_isolated_partial(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    selection = _selection(1, "root/app")
    config = _config(destination, [selection])
    instance = SyncOrchestrator(config, "secret", git=FakeGit())  # type: ignore[arg-type]
    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        failures = instance._run_project(
            FakeClient({1: _details(1, "root/renamed")}, {1: WikiProbe(200, 1)}),  # type: ignore[arg-type]
            store,
            object(),  # type: ignore[arg-type]
            orchestrator.LifecycleReconciler(destination, store),
            "now",
            selection,
            InventoryObject(1, "root/app"),
        )
        assert failures == 2
        assert store.get_resource("project", 1, "repository")["status"] == "error"
        assert store.get_resource("project", 1, "wiki")["status"] == "error"


def test_reenable_restore_failures_do_not_block_exporters(tmp_path: Path) -> None:
    destination = tmp_path / "corpus"
    config = _config(destination, [_selection(1, "root/app", wiki=False)])
    instance = SyncOrchestrator(config, "secret", git=FakeGit())  # type: ignore[arg-type]

    class FailedLifecycle:
        def restore_component(self, *args: Any) -> bool:
            raise ReconcileError("restore collision")

        def retire_component(self, *args: Any) -> bool:
            raise ReconcileError("retire collision")

    class NoWorkItems:
        def sync_project(self, *args: Any, **kwargs: Any) -> WorkItemSyncResult:
            return WorkItemSyncResult("ok", 0, 0, False, ())

    with StateStore.initialize_destination(
        destination, "https://git.example", 1
    ) as store:
        store.upsert_resource("project", 1, "repository", "disabled")
        failures = instance._run_project(
            FakeClient({1: _details(1, "root/app")}, {}),  # type: ignore[arg-type]
            store,
            NoWorkItems(),  # type: ignore[arg-type]
            FailedLifecycle(),  # type: ignore[arg-type]
            "now",
            config["inventory"]["projects"][0],
            InventoryObject(1, "root/app"),
        )
        assert failures >= 1

        group = ensure_object_directory(destination, "group", "root", 1)
        assert group.exists()
        store.upsert_resource("group", 1, "wiki", "disabled")

        class SuccessfulGroupExporter:
            def sync_group(self, *args: Any) -> GroupWikiSyncResult:
                return GroupWikiSyncResult("ok", False, "complete")

        assert (
            instance._run_group_wiki(
                store,
                SuccessfulGroupExporter(),  # type: ignore[arg-type]
                FailedLifecycle(),  # type: ignore[arg-type]
                {"id": 1, "full_path": "root", "wiki": True},
                InventoryObject(1, "root"),
            )
            == 1
        )
        assert (
            instance._run_group_wiki(
                store,
                SuccessfulGroupExporter(),  # type: ignore[arg-type]
                FailedLifecycle(),  # type: ignore[arg-type]
                {"id": 1, "full_path": "root", "wiki": False},
                InventoryObject(1, "root"),
            )
            == 1
        )
