"""One-pass synchronization orchestration for selected Git resources."""

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from gitlab_groupsync.discovery import inventory_from_config
from gitlab_groupsync.git_sync import (
    GitResourceResult,
    GitResourceSynchronizer,
    GitRunner,
    GitSyncError,
    LocalConflictError,
    PathSafetyError,
    project_path,
    wiki_remote,
)
from gitlab_groupsync.gitlab_api import (
    DiscoveryError,
    GitLabClient,
    InventoryDiff,
    ProjectDetails,
    compare_inventories,
    discover_inventory,
)
from gitlab_groupsync.group_wikis import (
    GroupWikiExporter,
    group_path,
    group_wiki_limitations,
)
from gitlab_groupsync.reconcile import LifecycleReconciler, ReconcileError
from gitlab_groupsync.search_guide import write_search_guide
from gitlab_groupsync.state import (
    DestinationLock,
    StateError,
    StateStore,
    utc_now,
    write_manifest,
    write_resource_metadata,
)
from gitlab_groupsync.work_items import WorkItemExporter


class SyncSetupError(Exception):
    """A fatal setup or authoritative discovery error."""


def _has_drift(drift: InventoryDiff) -> bool:
    return any((drift.added, drift.absent, drift.renamed, drift.path_reused))


def _remote(details: ProjectDetails, transport: str) -> str:
    return details.ssh_url if transport == "ssh" else details.http_url


class SyncOrchestrator:
    """Coordinate live inventory, durable state, and independent exporters."""

    def __init__(
        self,
        config: Mapping[str, Any],
        token: str,
        *,
        client_factory: Callable[..., GitLabClient] = GitLabClient,
        git: GitResourceSynchronizer | None = None,
        report: Callable[[str], None] = lambda message: None,
        full: bool = False,
    ) -> None:
        self.config = config
        self.token = token
        self.client_factory = client_factory
        self.destination = Path(config["storage"]["destination"])
        timeout = config["sync"]["git_timeout_seconds"]
        self.git = git or GitResourceSynchronizer(
            GitRunner(timeout, ca_bundle=config["gitlab"]["ca_bundle"]),
            self.destination / ".sync" / "staging",
        )
        self.report = report
        self.full = full

    def run(self) -> int:
        """Execute one locked pass and return the specified process exit code."""
        catalog = inventory_from_config(self.config)
        if catalog is None:
            raise SyncSetupError(
                "configuration has no discovered inventory; run discover"
            )
        gitlab = self.config["gitlab"]
        sync = self.config["sync"]
        try:
            with self.client_factory(
                gitlab["url"],
                self.token,
                timeout=sync["api_timeout_seconds"],
                max_attempts=sync["max_attempts"],
                ca_bundle=gitlab["ca_bundle"],
            ) as client:
                live = discover_inventory(
                    client,
                    gitlab["group"],
                    include_shared=sync["include_shared_projects"],
                    include_archived=sync["include_archived_projects"],
                )
                if live.root_group.id != catalog.root_group.id:
                    raise SyncSetupError(
                        "live root group ID differs from the configured inventory"
                    )
                with StateStore.initialize_destination(
                    self.destination, gitlab["url"], live.root_group.id
                ) as store:
                    run_started_at = utc_now()
                    run_id = store.begin_run(started_at=run_started_at)
                    try:
                        exit_code = self._run_resources(
                            client, store, run_id, run_started_at, catalog, live
                        )
                        outcome = "success" if exit_code == 0 else "partial"
                        store.finish_run(run_id, outcome, exit_code)
                    except Exception:
                        store.finish_run(
                            run_id, "failed", 2, "fatal synchronization failure"
                        )
                        raise
                    write_manifest(
                        self.destination, store.status_snapshot(current_run=True)
                    )
                    write_search_guide(self.destination)
                    return exit_code
        except SyncSetupError:
            raise
        except DiscoveryError as exc:
            self._record_failed_discovery()
            raise SyncSetupError(str(exc)) from exc
        except StateError as exc:
            raise SyncSetupError(str(exc)) from exc

    def _record_failed_discovery(self) -> None:
        """Record fatal discovery when this destination already has durable state."""
        database = self.destination / ".sync" / "state.sqlite3"
        if not database.is_file():
            return
        try:
            with StateStore(database) as store:
                run_id = store.begin_run()
                store.finish_run(run_id, "failed", 2, "live inventory discovery failed")
                write_manifest(
                    self.destination, store.status_snapshot(current_run=True)
                )
        except StateError:
            return

    def _run_resources(
        self,
        client: GitLabClient,
        store: StateStore,
        run_id: int,
        run_started_at: str,
        catalog: Any,
        live: Any,
    ) -> int:
        drift = compare_inventories(catalog, live)
        store.record_drift(drift, run_id=run_id)
        if _has_drift(drift):
            self.report(
                "Inventory drift detected; run gl-groupsync discover --config <path> "
                "and review selection flags."
            )
        renamed_projects = {
            project.id
            for project in live.projects
            if (previous := store.get_object("project", project.id)) is not None
            and previous["full_path"] != project.full_path
        }
        lifecycle = LifecycleReconciler(self.destination, store)
        failures = lifecycle.reconcile_inventory(live)

        live_projects = {project.id: project for project in live.projects}
        work_items = WorkItemExporter(
            client,
            store,
            self.destination,
            overlap_seconds=self.config["sync"].get("incremental_overlap_seconds", 300),
            full_reconcile_hours=self.config["sync"].get("full_reconcile_hours", 168),
        )
        group_wikis = GroupWikiExporter(
            client,
            store,
            self.destination,
            self.config["gitlab"]["url"],
            lifecycle=lifecycle,
        )
        failures += sum(
            work_items.recover(int(value["global_id"]))
            for value in store.objects("project")
        )
        failures += sum(
            group_wikis.recover(int(value["global_id"]))
            for value in store.objects("group")
        )
        failures += self._run_group_wikis(store, live, lifecycle, group_wikis)
        jobs = [
            (
                selection,
                live_projects[selection["id"]],
                selection["id"] in renamed_projects,
            )
            for selection in self.config["inventory"]["projects"]
            if selection["id"] in live_projects
            and (
                any(selection[kind] for kind in ("repository", "wiki", "work_items"))
                or store.resources_for_object("project", selection["id"])
            )
        ]
        worker = partial(
            self._run_project,
            client,
            store,
            work_items,
            lifecycle,
            run_started_at,
        )
        with ThreadPoolExecutor(
            max_workers=self.config["sync"].get("workers", 1)
        ) as executor:
            failures += sum(executor.map(lambda job: worker(*job), jobs))
        return 1 if failures else 0

    def _run_project(
        self,
        client: GitLabClient,
        store: StateStore,
        work_items: WorkItemExporter,
        lifecycle: LifecycleReconciler,
        run_started_at: str,
        selection: Mapping[str, Any],
        live_project: Any,
        force_work_items_full: bool = False,
    ) -> int:
        failures = 0
        try:
            base = project_path(
                self.destination, live_project.full_path, live_project.id
            )
        except PathSafetyError as exc:
            for kind in ("repository", "wiki", "work_items"):
                if selection[kind]:
                    self._record_failure(
                        store, live_project.id, kind, "error", str(exc)
                    )
                    failures += 1
            return failures
        for kind, component in (
            ("repository", "repository"),
            ("wiki", "wiki"),
            ("work_items", "work-items"),
        ):
            try:
                if selection[kind]:
                    previous = (
                        store.get_resource("project", live_project.id, kind) or {}
                    )
                    if previous.get("status") in {
                        "disabled",
                        "missing_from_scope",
                    }:
                        lifecycle.restore_component(
                            "project",
                            live_project.id,
                            live_project.full_path,
                            component,
                        )
                else:
                    lifecycle.retire_component(
                        "project",
                        live_project.id,
                        live_project.full_path,
                        component,
                        "configured_exclusion",
                    )
            except (OSError, ReconcileError) as exc:
                self._record_failure(store, live_project.id, kind, "error", str(exc))
                failures += 1
        if selection["work_items"]:
            result = work_items.sync_project(
                live_project.id,
                live_project.full_path,
                base,
                force_full=self.full or force_work_items_full,
                run_started_at=run_started_at,
            )
            failures += result.failures
        else:
            self._record_disabled(store, live_project.id, "work_items")

        if not (selection["repository"] or selection["wiki"]):
            self._record_disabled(store, live_project.id, "repository")
            self._record_disabled(store, live_project.id, "wiki")
            self._write_project(store, base, live_project.id, live_project.full_path)
            return failures
        try:
            details = client.project_details(live_project.id)
        except DiscoveryError as exc:
            for kind in ("repository", "wiki"):
                if selection[kind]:
                    self._record_failure(
                        store, live_project.id, kind, "error", str(exc)
                    )
                    failures += 1
            self._write_project(store, base, live_project.id, live_project.full_path)
            return failures
        if details.full_path != live_project.full_path:
            error = "project path changed during synchronization; retry discovery"
            for kind in ("repository", "wiki"):
                if selection[kind]:
                    self._record_failure(store, details.id, kind, "error", error)
                    failures += 1
            self._write_project(store, base, details.id, live_project.full_path)
            return failures

        if selection["repository"]:
            failures += self._sync_repository(store, base, details)
        else:
            self._record_disabled(store, details.id, "repository")
        if selection["wiki"]:
            failures += self._sync_wiki(client, store, base, details)
        else:
            self._record_disabled(store, details.id, "wiki")
        self._write_project(store, base, details.id, details.full_path)
        return failures

    def _run_group_wikis(
        self,
        store: StateStore,
        live: Any,
        lifecycle: LifecycleReconciler,
        exporter: GroupWikiExporter,
    ) -> int:
        """Run configured group wikis independently, including projectless groups."""
        live_groups = {group.id: group for group in live.groups}
        jobs = []
        for selection in self.config["inventory"]["groups"]:
            group = live_groups.get(selection["id"])
            if group is None:
                continue
            jobs.append((selection, group))
        worker = partial(self._run_group_wiki, store, exporter, lifecycle)
        with ThreadPoolExecutor(
            max_workers=self.config["sync"].get("workers", 1)
        ) as executor:
            return sum(executor.map(lambda job: worker(*job), jobs))

    def _run_group_wiki(
        self,
        store: StateStore,
        exporter: GroupWikiExporter,
        lifecycle: LifecycleReconciler,
        selection: Mapping[str, Any],
        group: Any,
    ) -> int:
        failures = 0
        evidence = "Configured wiki:false; no Group Wikis API request issued."
        try:
            base = group_path(self.destination, group.full_path, group.id)
        except PathSafetyError as exc:
            if selection["wiki"]:
                self._record_group_failure(store, group.id, str(exc))
                return 1
            self._record_group_disabled(store, group.id)
            return 0
        if not selection["wiki"]:
            try:
                lifecycle.retire_component(
                    "group",
                    group.id,
                    group.full_path,
                    "wiki",
                    "configured_exclusion",
                )
            except (OSError, ReconcileError) as exc:
                self._record_group_failure(store, group.id, str(exc))
                failures += 1
            self._record_group_disabled(store, group.id, evidence)
        else:
            try:
                previous = store.get_resource("group", group.id, "wiki") or {}
                if previous.get("status") in {"disabled", "missing_from_scope"}:
                    lifecycle.restore_component(
                        "group", group.id, group.full_path, "wiki"
                    )
            except (OSError, ReconcileError) as exc:
                self._record_group_failure(store, group.id, str(exc))
                failures += 1
            result = exporter.sync_group(group.id, group.full_path, base)
            evidence = result.evidence
            failures += int(result.failure)
        self._write_group(store, base, group.id, group.full_path, evidence)
        return failures

    def _sync_repository(
        self, store: StateStore, base: Path, details: ProjectDetails
    ) -> int:
        attempted = utc_now()
        if details.empty_repository or details.default_branch is None:
            try:
                LifecycleReconciler(self.destination, store).retire_component(
                    "project",
                    details.id,
                    details.full_path,
                    "repository",
                    "conclusively_empty_upstream",
                )
            except (OSError, ReconcileError) as exc:
                self._record_failure(store, details.id, "repository", "error", str(exc))
                return 1
            store.upsert_resource(
                "project",
                details.id,
                "repository",
                "empty",
                last_attempt_at=attempted,
                last_success_at=attempted,
            )
            return 0
        try:
            result = self.git.sync(
                base / "repository",
                _remote(details, self.config["gitlab"]["git_transport"]),
                details.default_branch,
                f"project:{details.id}:repository",
                token=self.token
                if self.config["gitlab"]["git_transport"] == "https"
                else None,
            )
        except LocalConflictError as exc:
            self._record_failure(
                store, details.id, "repository", "local_conflict", str(exc)
            )
            return 1
        except GitSyncError as exc:
            status = "inconsistent" if "inconsistent" in str(exc) else "error"
            self._record_failure(store, details.id, "repository", status, str(exc))
            return 1
        self._record_success(store, details.id, "repository", result, attempted)
        return 0

    def _sync_wiki(
        self,
        client: GitLabClient,
        store: StateStore,
        base: Path,
        details: ProjectDetails,
    ) -> int:
        attempted = utc_now()
        if not details.wiki_enabled:
            try:
                LifecycleReconciler(self.destination, store).retire_component(
                    "project",
                    details.id,
                    details.full_path,
                    "wiki",
                    "conclusively_disabled_upstream",
                )
            except (OSError, ReconcileError) as exc:
                self._record_failure(store, details.id, "wiki", "error", str(exc))
                return 1
            store.upsert_resource(
                "project", details.id, "wiki", "disabled", last_attempt_at=attempted
            )
            return 0
        try:
            evidence = client.probe_project_wiki(details.id)
        except DiscoveryError as exc:
            self._record_failure(store, details.id, "wiki", "error", str(exc))
            return 1
        if evidence.status_code in {401, 403, 404}:
            self._record_failure(
                store,
                details.id,
                "wiki",
                "unavailable",
                f"project wiki API returned HTTP {evidence.status_code}",
                limitations=("cause is ambiguous from observed HTTP evidence",),
            )
            return 1
        if evidence.page_count == 0:
            try:
                LifecycleReconciler(self.destination, store).retire_component(
                    "project",
                    details.id,
                    details.full_path,
                    "wiki",
                    "conclusively_empty_upstream",
                )
            except (OSError, ReconcileError) as exc:
                self._record_failure(store, details.id, "wiki", "error", str(exc))
                return 1
            store.upsert_resource(
                "project",
                details.id,
                "wiki",
                "empty",
                last_attempt_at=attempted,
                last_success_at=attempted,
            )
            return 0
        remote = wiki_remote(_remote(details, self.config["gitlab"]["git_transport"]))
        git_token = (
            self.token if self.config["gitlab"]["git_transport"] == "https" else None
        )
        try:
            head = self.git.remote_head(
                remote, token=git_token, resource_key=f"project:{details.id}:wiki"
            )
            if head is None:
                raise GitSyncError("wiki API reported pages but Git remote is empty")
            branch, _ = head
            result = self.git.sync(
                base / "wiki",
                remote,
                branch,
                f"project:{details.id}:wiki",
                token=git_token,
            )
        except LocalConflictError as exc:
            self._record_failure(store, details.id, "wiki", "local_conflict", str(exc))
            return 1
        except GitSyncError as exc:
            status = "inconsistent" if "inconsistent" in str(exc) else "error"
            self._record_failure(store, details.id, "wiki", status, str(exc))
            return 1
        self._record_success(store, details.id, "wiki", result, attempted)
        return 0

    @staticmethod
    def _record_success(
        store: StateStore,
        project_id: int,
        kind: str,
        result: GitResourceResult,
        attempted: str,
    ) -> None:
        store.upsert_resource(
            "project",
            project_id,
            kind,
            result.status,
            last_attempt_at=attempted,
            last_success_at=attempted,
            revision=result.revision,
            branch=result.branch,
            limitations=("detached default branch only",),
        )

    @staticmethod
    def _record_disabled(store: StateStore, project_id: int, kind: str) -> None:
        previous = store.get_resource("project", project_id, kind) or {}
        store.upsert_resource(
            "project",
            project_id,
            kind,
            "disabled",
            last_attempt_at=utc_now(),
            last_success_at=previous.get("last_success_at"),
            revision=previous.get("revision"),
            branch=previous.get("branch"),
            retained_content=bool(previous.get("last_success_at")),
        )

    @staticmethod
    def _record_failure(
        store: StateStore,
        project_id: int,
        kind: str,
        status: str,
        error: str,
        *,
        limitations: tuple[str, ...] = (),
    ) -> None:
        previous = store.get_resource("project", project_id, kind) or {}
        store.upsert_resource(
            "project",
            project_id,
            kind,
            status,
            last_attempt_at=utc_now(),
            last_success_at=previous.get("last_success_at"),
            revision=previous.get("revision"),
            branch=previous.get("branch"),
            last_error=error,
            retained_content=bool(previous.get("last_success_at")),
            limitations=limitations,
        )

    @staticmethod
    def _record_group_disabled(
        store: StateStore,
        group_id: int,
        evidence: str = "Configured wiki:false; metadata path was unavailable.",
    ) -> None:
        previous = store.get_resource("group", group_id, "wiki") or {}
        store.upsert_resource(
            "group",
            group_id,
            "wiki",
            "disabled",
            last_attempt_at=utc_now(),
            last_success_at=previous.get("last_success_at"),
            revision=previous.get("revision"),
            retained_content=bool(previous.get("last_success_at")),
            limitations=(*group_wiki_limitations(), evidence),
        )

    @staticmethod
    def _record_group_failure(store: StateStore, group_id: int, error: str) -> None:
        previous = store.get_resource("group", group_id, "wiki") or {}
        store.upsert_resource(
            "group",
            group_id,
            "wiki",
            "error",
            last_attempt_at=utc_now(),
            last_success_at=previous.get("last_success_at"),
            revision=previous.get("revision"),
            last_error=error,
            retained_content=bool(previous.get("last_success_at")),
            limitations=group_wiki_limitations(),
        )

    @staticmethod
    def _write_group(
        store: StateStore,
        base: Path,
        group_id: int,
        full_path: str,
        evidence: str,
    ) -> None:
        write_resource_metadata(
            base / "group.json",
            {
                "id": group_id,
                "full_path": full_path,
                "resources": store.resources_for_object("group", group_id),
                "wiki_evidence": evidence,
            },
        )

    @staticmethod
    def _write_project(
        store: StateStore, base: Path, project_id: int, full_path: str
    ) -> None:
        write_resource_metadata(
            base / "project.json",
            {
                "id": project_id,
                "full_path": full_path,
                "resources": store.resources_for_object("project", project_id),
            },
        )


def run_sync(
    config: Mapping[str, Any],
    token: str,
    *,
    report: Callable[[str], None],
    full: bool = False,
) -> int:
    """Construct and execute the default synchronization adapters."""
    destination = config["storage"]["destination"]
    with DestinationLock(destination):
        return SyncOrchestrator(config, token, report=report, full=full).run()
