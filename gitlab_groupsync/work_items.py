"""Current-state GitLab issue/task export, rendering, and reconciliation."""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from gitlab_groupsync.gitlab_api import DiscoveryError, GitLabClient
from gitlab_groupsync.path_safety import (
    UnsafePathError,
    contained_path,
    fsync_directories,
)
from gitlab_groupsync.state import StateError, StateStore, atomic_write_json, utc_now

_UPLOAD_LINK = re.compile(
    r"(?P<prefix>!?\[[^\]]*\]\()(?P<url><?/?uploads/[^\s)>]+>?)(?P<suffix>[^)]*\))"
)
_LIMITATIONS = (
    "Inventory is limited to accessible REST issue_type=issue and "
    "issue_type=task records; other modern work-item types are not covered.",
    "The export is current state and does not reconstruct description or comment "
    "revision history.",
    "System activity excludes resource-event endpoints that are not returned as "
    "discussion notes.",
)


@dataclass(frozen=True)
class WorkItemSyncResult:
    """One project's work-item synchronization outcome."""

    status: str
    exported: int
    failures: int
    full: bool
    limitations: tuple[str, ...]


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DiscoveryError(f"GitLab returned an invalid work-item {field}")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DiscoveryError(f"GitLab returned an invalid work-item {field}")
    return value


def _item_identity(item: Mapping[str, Any]) -> tuple[int, int, str, str, str]:
    global_id = _require_int(item.get("id"), "global ID")
    iid = _require_int(item.get("iid"), "IID")
    item_type = _require_text(item.get("issue_type"), "type").lower()
    if item_type not in {"issue", "task"}:
        raise DiscoveryError("GitLab returned an unexpected work-item type")
    web_url = _require_text(item.get("web_url"), "URL")
    updated_at = _require_text(item.get("updated_at"), "updated timestamp")
    return global_id, iid, item_type, web_url, updated_at


def _project_url(web_url: str) -> str:
    marker = "/-/"
    return (
        web_url.split(marker, 1)[0] if marker in web_url else web_url.rsplit("/", 2)[0]
    )


def resolve_upload_links(markdown: str, web_url: str) -> str:
    """Resolve GitLab upload links without otherwise rewriting source Markdown."""
    base = _project_url(web_url).rstrip("/")

    def replace(match: re.Match[str]) -> str:
        raw = match.group("url")
        wrapped = raw.startswith("<") and raw.endswith(">")
        value = raw[1:-1] if wrapped else raw
        value = value.lstrip("/")
        resolved = f"{base}/-/{value}"
        if wrapped:
            resolved = f"<{resolved}>"
        return f"{match.group('prefix')}{resolved}{match.group('suffix')}"

    return _UPLOAD_LINK.sub(replace, markdown)


def _person(value: Any) -> str:
    if not isinstance(value, dict):
        return "Unknown"
    name = value.get("name")
    username = value.get("username")
    if isinstance(name, str) and isinstance(username, str):
        return f"{name} (@{username})"
    if isinstance(name, str):
        return name
    if isinstance(username, str):
        return f"@{username}"
    return "Unknown"


def _frontmatter_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _note_key(note: Mapping[str, Any]) -> tuple[str, int]:
    created = note.get("created_at")
    note_id = note.get("id")
    return (
        created if isinstance(created, str) else "",
        note_id if isinstance(note_id, int) else 0,
    )


def _notes(
    snapshot: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    human_threads: list[dict[str, Any]] = []
    system: dict[int, dict[str, Any]] = {}
    human_seen: set[int] = set()
    discussions = snapshot.get("discussions", [])
    if not isinstance(discussions, list):
        return human_threads, []
    for discussion in discussions:
        if not isinstance(discussion, dict):
            continue
        human: list[dict[str, Any]] = []
        raw_notes = discussion.get("notes", [])
        if not isinstance(raw_notes, list):
            continue
        for note in raw_notes:
            if not isinstance(note, dict):
                continue
            note_id = note.get("id")
            if not isinstance(note_id, int):
                continue
            if bool(note.get("system")):
                system[note_id] = note
            elif note_id not in human_seen:
                human_seen.add(note_id)
                human.append(note)
        if human:
            human.sort(key=_note_key)
            human_threads.append(
                {
                    "id": str(discussion.get("id", "")),
                    "individual_note": bool(discussion.get("individual_note")),
                    "notes": human,
                }
            )
    human_threads.sort(key=lambda thread: (_note_key(thread["notes"][0]), thread["id"]))
    return human_threads, sorted(system.values(), key=_note_key)


def _render_note(note: Mapping[str, Any], web_url: str, level: int = 4) -> list[str]:
    note_id = note.get("id")
    created = note.get("created_at")
    updated = note.get("updated_at")
    metadata = [f"ID `{note_id}`", f"created `{created}`", f"updated `{updated}`"]
    for key in ("resolvable", "resolved", "resolved_at", "confidential", "internal"):
        if key in note:
            metadata.append(f"{key} `{note.get(key)}`")
    source = f"{web_url}#note_{note_id}"
    raw_body = note.get("body")
    body = raw_body if isinstance(raw_body, str) else ""
    return [
        f"{'#' * level} {_person(note.get('author'))}",
        "",
        f"Source: [{source}]({source}) | " + " | ".join(metadata),
        "",
        resolve_upload_links(body, web_url),
        "",
    ]


def _relationship_lines(snapshot: Mapping[str, Any]) -> list[str]:
    relationships = snapshot.get("relationships", [])
    if not isinstance(relationships, list) or not relationships:
        return ["No supported relationships were returned."]
    lines = []
    for relation in relationships:
        if not isinstance(relation, dict):
            continue
        kind = relation.get("kind", "related")
        title = (
            relation.get("title") or relation.get("iid") or relation.get("global_id")
        )
        source_url = relation.get("web_url")
        local = relation.get("local_link")
        links = []
        if isinstance(source_url, str) and source_url:
            links.append(f"[source]({source_url})")
        if isinstance(local, str) and local:
            links.append(f"[local]({local})")
        suffix = f" ({', '.join(links)})" if links else ""
        lines.append(f"- **{kind}**: {title}{suffix}")
    return lines or ["No supported relationships were returned."]


def render_work_item(snapshot: Mapping[str, Any]) -> str:
    """Render deterministic UTF-8 Markdown from one complete raw snapshot."""
    item = snapshot["item"]
    assert isinstance(item, dict)
    project_path = str(snapshot["project_path"])
    title = str(item.get("title", ""))
    web_url = str(item["web_url"])
    raw_assignees = item.get("assignees")
    assignees = raw_assignees if isinstance(raw_assignees, list) else []
    raw_labels = item.get("labels")
    labels = raw_labels if isinstance(raw_labels, list) else []
    milestone = item.get("milestone")
    milestone_title = milestone.get("title") if isinstance(milestone, dict) else None
    raw_description = item.get("description")
    description = raw_description if isinstance(raw_description, str) else ""
    frontmatter = {
        "title": title,
        "type": item.get("issue_type"),
        "state": item.get("state"),
        "project_path": project_path,
        "global_id": item.get("id"),
        "iid": item.get("iid"),
        "canonical_url": web_url,
        "author": _person(item.get("author")),
        "assignees": [_person(value) for value in assignees],
        "labels": labels,
        "milestone": milestone_title,
        "confidential": bool(item.get("confidential")),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
    }
    lines = ["---"]
    lines.extend(
        f"{key}: {_frontmatter_value(value)}" for key, value in frontmatter.items()
    )
    lines.extend(
        [
            "---",
            "",
            f"# {title}",
            "",
            "## Provenance",
            "",
            f"- Project: `{project_path}`",
            f"- Identity: global `{item.get('id')}`, project IID `{item.get('iid')}`",
            f"- Canonical source: [{web_url}]({web_url})",
            "",
            "## Description",
            "",
            resolve_upload_links(description, web_url),
            "",
            "## Relationships",
            "",
            *_relationship_lines(snapshot),
            "",
            "## Human Conversations",
            "",
        ]
    )
    threads, system = _notes(snapshot)
    if not threads:
        lines.extend(["No human comments were returned.", ""])
    for index, thread in enumerate(threads, start=1):
        kind = "Standalone comment" if thread["individual_note"] else "Thread"
        lines.extend([f"### {kind} {index} (`{thread['id']}`)", ""])
        for note in thread["notes"]:
            lines.extend(_render_note(note, web_url))
    lines.extend(["## System Activity", ""])
    if not system:
        lines.extend(["No system discussion notes were returned.", ""])
    for note in system:
        lines.extend(_render_note(note, web_url, level=3))
    limitations = snapshot.get("limitations", [])
    lines.extend(["## Export Limitations", ""])
    lines.extend(f"- {value}" for value in limitations)
    lines.append("")
    return "\n".join(lines)


def _atomic_write_text(path: Path, content: str) -> bool:
    encoded = content.encode("utf-8")
    try:
        if path.read_bytes() == encoded:
            return False
    except FileNotFoundError:
        pass
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = output.name
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        fsync_directories((path.parent,))
    except OSError as exc:
        raise StateError("could not atomically publish work-item Markdown") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return True


class WorkItemExporter:
    """Synchronize one selected project's issue/task current state."""

    def __init__(
        self,
        client: GitLabClient,
        store: StateStore,
        destination: Path,
        *,
        overlap_seconds: int,
        full_reconcile_hours: int,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.store = store
        self.destination = destination
        self.overlap_seconds = overlap_seconds
        self.full_reconcile_hours = full_reconcile_hours
        self.now = now

    def sync_project(
        self,
        project_id: int,
        project_path: str,
        project_root: Path,
        *,
        force_full: bool,
        run_started_at: str,
    ) -> WorkItemSyncResult:
        scope = f"project:{project_id}:work-items"
        recovery_failures = self._recover_publications(project_id)
        checkpoint = self.store.get_checkpoint(scope, "incremental")
        last_full = self.store.get_checkpoint(scope, "full_success")
        full = force_full or checkpoint is None or self._full_due(last_full)
        updated_after = None
        if not full and checkpoint is not None:
            boundary = datetime.fromisoformat(checkpoint) - timedelta(
                seconds=self.overlap_seconds
            )
            updated_after = boundary.isoformat()
        try:
            listed = list(
                self.client.iter_project_work_items(
                    project_id, updated_after=updated_after
                )
            )
        except DiscoveryError as exc:
            self._resource_failure(project_id, str(exc))
            return WorkItemSyncResult(
                "error", 0, recovery_failures + 1, full, _LIMITATIONS
            )

        candidates: dict[int, Mapping[str, Any]] = {}
        retry_failures = 0
        try:
            for item in listed:
                _, iid, _, _, _ = _item_identity(item)
                candidates[iid] = item
        except DiscoveryError as exc:
            self._resource_failure(project_id, str(exc))
            return WorkItemSyncResult(
                "error", 0, recovery_failures + 1, full, _LIMITATIONS
            )
        for key in self.store.retry_items(scope):
            try:
                iid = int(key)
                if iid not in candidates:
                    candidates[iid] = self.client.project_issue(project_id, iid)
            except ValueError:
                retry_failures += 1
            except DiscoveryError as exc:
                self.store.enqueue_retry(
                    scope, key, "work_item_retry", details=str(exc)
                )
                retry_failures += 1

        known_iids = {
            int(value["iid"])
            for value in self.store.work_items_for_project(project_id)
            if not value["missing_from_scope"]
        } | set(candidates)
        failures = recovery_failures + retry_failures
        exported = 0
        for iid in sorted(candidates):
            item = candidates[iid]
            try:
                self._export_item(
                    project_id, project_path, project_root, item, known_iids
                )
            except (
                DiscoveryError,
                StateError,
                UnsafePathError,
                OSError,
                ValueError,
            ) as exc:
                self.store.enqueue_retry(scope, str(iid), "work_item", details=str(exc))
                failures += 1
            else:
                self.store.complete_retry(scope, str(iid))
                exported += 1

        self.store.set_checkpoint(scope, "incremental", run_started_at)
        quarantine_failures = 0
        if full:
            quarantine_failures = self._quarantine_missing(
                project_id,
                project_path,
                {int(item["iid"]) for item in listed},
            )
            failures += quarantine_failures
            if failures == 0:
                self.store.set_checkpoint(scope, "full_success", run_started_at)
        status = "ok" if failures == 0 else "error"
        previous = self.store.get_resource("project", project_id, "work_items") or {}
        if quarantine_failures:
            last_error = (
                f"{failures} work-item operation(s) failed, including "
                f"{quarantine_failures} quarantine operation(s); retained content "
                "will be retried on a later full reconciliation"
            )
        elif failures:
            last_error = f"{failures} work-item operation(s) failed"
        else:
            last_error = None
        self.store.upsert_resource(
            "project",
            project_id,
            "work_items",
            status,
            last_attempt_at=utc_now(),
            last_success_at=run_started_at
            if failures == 0
            else previous.get("last_success_at"),
            revision=str(len(self.store.work_items_for_project(project_id))),
            last_error=last_error,
            retained_content=failures > 0 and bool(previous.get("last_success_at")),
            limitations=_LIMITATIONS,
        )
        return WorkItemSyncResult(status, exported, failures, full, _LIMITATIONS)

    def _full_due(self, value: str | None) -> bool:
        if value is None:
            return True
        try:
            return self.now() - datetime.fromisoformat(value) >= timedelta(
                hours=self.full_reconcile_hours
            )
        except ValueError:
            return True

    def _export_item(
        self,
        project_id: int,
        project_path: str,
        project_root: Path,
        item: Mapping[str, Any],
        known_iids: set[int],
    ) -> None:
        global_id, iid, item_type, web_url, updated_at = _item_identity(item)
        discussions = self.client.issue_discussions(project_id, iid)
        links = self.client.issue_links(project_id, iid)
        hierarchy = self.client.work_item_hierarchy(project_path, iid)
        content_path = project_root / "work-items" / f"{iid}.md"
        raw_path = (
            self.destination
            / ".sync"
            / "raw"
            / "projects"
            / str(project_id)
            / "work-items"
            / f"{global_id}.json"
        )
        try:
            content_path = contained_path(
                self.destination,
                content_path.relative_to(self.destination),
                create_parents=True,
            )
            raw_path = contained_path(
                self.destination,
                raw_path.relative_to(self.destination),
                create_parents=True,
            )
        except (UnsafePathError, ValueError) as exc:
            raise StateError("unsafe work-item publication path") from exc
        relationships = self._relationships(
            project_id,
            content_path,
            links,
            hierarchy.parent,
            hierarchy.children,
            known_iids,
        )
        snapshot: dict[str, Any] = {
            "schema_version": 1,
            "project_id": project_id,
            "project_path": project_path,
            "item": dict(item),
            "discussions": [dict(value) for value in discussions],
            "issue_links": [dict(value) for value in links],
            "hierarchy": {
                "parent": dict(hierarchy.parent)
                if hierarchy.parent is not None
                else None,
                "children": [dict(value) for value in hierarchy.children],
            },
            "relationships": relationships,
            "limitations": [*_LIMITATIONS, *hierarchy.limitations],
        }
        markdown = render_work_item(snapshot)
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        raw_bytes = (
            json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode()
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        details = {
            "global_id": global_id,
            "iid": iid,
            "item_type": item_type,
            "web_url": web_url,
            "source_updated_at": updated_at,
            "content_path": str(content_path),
            "raw_path": str(raw_path),
            "content_hash": content_hash,
            "raw_hash": raw_hash,
        }
        existing = self.store.work_item(project_id, iid)
        if existing is not None and existing["global_id"] != global_id:
            self._quarantine_item(
                existing,
                reason="iid_reused_by_another_id",
                evidence=f"project IID now belongs to global ID {global_id}",
            )
        recovery_id = self.store.record_recovery(
            "work_item_publication",
            "project",
            project_id,
            "prepared",
            source_path=str(raw_path.relative_to(self.destination)),
            destination_path=str(content_path.relative_to(self.destination)),
            details=details,
        )
        self._write_raw_if_changed(raw_path, snapshot, raw_bytes)
        _atomic_write_text(content_path, markdown)
        self._commit_publication(project_id, details)
        self.store.update_recovery(recovery_id, "complete")

    @staticmethod
    def _write_raw_if_changed(
        path: Path, snapshot: Mapping[str, Any], encoded: bytes
    ) -> None:
        try:
            if path.read_bytes() == encoded:
                return
        except FileNotFoundError:
            pass
        atomic_write_json(path, snapshot)

    def _commit_publication(self, project_id: int, details: Mapping[str, Any]) -> None:
        timestamp = utc_now()
        self.store.upsert_work_item(
            global_id=int(details["global_id"]),
            project_id=project_id,
            iid=int(details["iid"]),
            item_type=str(details["item_type"]),
            web_url=str(details["web_url"]),
            content_path=str(details["content_path"]),
            raw_path=str(details["raw_path"]),
            source_updated_at=str(details["source_updated_at"]),
            content_hash=str(details["content_hash"]),
            status="ok",
            last_attempt_at=timestamp,
            last_success_at=timestamp,
        )

    def _recover_publications(self, project_id: int) -> int:
        failures = 0
        for record in self.store.pending_recoveries(
            "work_item_publication", "project", project_id
        ):
            details = record["details"]
            try:
                if not isinstance(record["source_path"], str) or not isinstance(
                    record["destination_path"], str
                ):
                    raise UnsafePathError("recovery paths are missing")
                raw_path = contained_path(self.destination, record["source_path"])
                content_path = contained_path(
                    self.destination, record["destination_path"], create_parents=True
                )
            except UnsafePathError:
                self.store.update_recovery(record["id"], "abandoned")
                failures += 1
                continue
            try:
                encoded = raw_path.read_bytes()
                if hashlib.sha256(encoded).hexdigest() != details["raw_hash"]:
                    self.store.update_recovery(record["id"], "abandoned")
                    continue
                snapshot = json.loads(encoded)
                markdown = render_work_item(snapshot)
                if (
                    hashlib.sha256(markdown.encode()).hexdigest()
                    != details["content_hash"]
                ):
                    raise StateError("recovered work-item content hash differs")
                _atomic_write_text(content_path, markdown)
                self._commit_publication(project_id, details)
                self.store.update_recovery(record["id"], "complete")
            except (OSError, ValueError, StateError, KeyError, TypeError):
                failures += 1
        return failures

    def _relationships(
        self,
        project_id: int,
        content_path: Path,
        links: tuple[Mapping[str, Any], ...],
        parent: Mapping[str, Any] | None,
        children: tuple[Mapping[str, Any], ...],
        known_iids: set[int],
    ) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for link in links:
            target_id = link.get("id")
            target_project = link.get("project_id")
            target_iid = link.get("iid")
            relation = {
                "kind": link.get("link_type", "related"),
                "global_id": target_id,
                "project_id": target_project,
                "iid": target_iid,
                "title": link.get("title"),
                "web_url": link.get("web_url"),
            }
            relation["local_link"] = self._local_link(
                project_id,
                content_path,
                target_id,
                target_project,
                target_iid,
                known_iids,
            )
            values.append(relation)
        for kind, nodes in (
            ("parent", (parent,) if parent is not None else ()),
            ("child", children),
        ):
            for node in nodes:
                target_iid = node.get("iid")
                relation = {
                    "kind": kind,
                    "global_id": node.get("id"),
                    "project_id": project_id,
                    "iid": target_iid,
                    "title": node.get("title"),
                    "web_url": node.get("webUrl"),
                    "local_link": f"{target_iid}.md"
                    if isinstance(target_iid, str)
                    and target_iid.isdigit()
                    and int(target_iid) in known_iids
                    else None,
                }
                values.append(relation)
        return sorted(
            values,
            key=lambda value: (
                str(value.get("kind", "")),
                str(value.get("project_id", "")),
                str(value.get("iid", "")),
                str(value.get("global_id", "")),
            ),
        )

    def _local_link(
        self,
        project_id: int,
        content_path: Path,
        global_id: Any,
        target_project: Any,
        target_iid: Any,
        known_iids: set[int],
    ) -> str | None:
        if (
            target_project == project_id
            and isinstance(target_iid, int)
            and target_iid in known_iids
        ):
            return f"{target_iid}.md"
        if isinstance(global_id, int):
            target = self.store.work_item_by_global_id(global_id)
            if target is not None and not target["missing_from_scope"]:
                project = self.store.get_object("project", int(target["project_id"]))
                if project is not None and not project["missing_from_scope"]:
                    try:
                        target_path = contained_path(
                            self.destination,
                            Path("content/projects")
                            / str(project["full_path"])
                            / "work-items"
                            / f"{target['iid']}.md",
                        )
                    except UnsafePathError:
                        return None
                else:
                    target_path = Path(target["content_path"])
                    if not target_path.is_absolute():
                        target_path = self.destination / target_path
                return os.path.relpath(target_path, content_path.parent).replace(
                    os.sep, "/"
                )
        return None

    def _quarantine_missing(
        self, project_id: int, project_path: str, listed_iids: set[int]
    ) -> int:
        del project_path
        failures = 0
        for item in self.store.work_items_for_project(project_id):
            if item["iid"] in listed_iids or item["missing_from_scope"]:
                continue
            try:
                self._quarantine_item(
                    item,
                    reason="absent_from_complete_full_listing",
                    evidence="complete issue/task listing omitted this stable ID",
                )
            except (OSError, StateError, UnsafePathError, ValueError):
                failures += 1
        return failures

    def _quarantine_item(
        self, item: Mapping[str, Any], *, reason: str, evidence: str
    ) -> None:
        persisted_source = Path(str(item["content_path"]))
        try:
            relative_source = (
                persisted_source.relative_to(self.destination)
                if persisted_source.is_absolute()
                else persisted_source
            )
            source = contained_path(self.destination, relative_source)
        except (UnsafePathError, ValueError) as exc:
            raise StateError("unsafe persisted work-item content path") from exc
        stale = contained_path(
            self.destination,
            Path("stale/work-items")
            / f"{item['global_id']}-{utc_now().replace(':', '')}"
            / source.name,
            create_parents=True,
            label="stale work item",
        )
        if source.exists():
            os.replace(source, stale)
            fsync_directories((source.parent, stale.parent))
        atomic_write_json(
            stale.parent / "stale.json",
            {
                "object_kind": "work_item",
                "object_id": item["global_id"],
                "project_id": item["project_id"],
                "prior_source_path": item["content_path"],
                "prior_raw_path": item["raw_path"],
                "quarantined_at": utc_now(),
                "reason": reason,
                "evidence": evidence,
            },
        )
        self.store.upsert_work_item(
            global_id=int(item["global_id"]),
            project_id=int(item["project_id"]),
            iid=int(item["iid"]),
            item_type=str(item["item_type"]),
            web_url=str(item["web_url"]),
            content_path=str(item["content_path"]),
            raw_path=str(item["raw_path"]),
            source_updated_at=str(item["source_updated_at"]),
            content_hash=str(item["content_hash"]),
            status="missing_from_scope",
            last_attempt_at=utc_now(),
            last_success_at=item["last_success_at"],
            last_error=evidence,
            missing=True,
        )

    def _resource_failure(self, project_id: int, error: str) -> None:
        previous = self.store.get_resource("project", project_id, "work_items") or {}
        self.store.upsert_resource(
            "project",
            project_id,
            "work_items",
            "error",
            last_attempt_at=utc_now(),
            last_success_at=previous.get("last_success_at"),
            revision=previous.get("revision"),
            last_error=error,
            retained_content=bool(previous.get("last_success_at")),
            limitations=_LIMITATIONS,
        )
