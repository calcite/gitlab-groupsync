"""Safe current-state export of selected GitLab group wikis through REST."""

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from gitlab_groupsync.git_sync import PathSafetyError
from gitlab_groupsync.gitlab_api import DiscoveryError, GitLabClient
from gitlab_groupsync.path_safety import (
    UnsafePathError,
    assert_no_symlinks,
    contained_path,
    fsync_directories,
)
from gitlab_groupsync.reconcile import ReconcileError, ensure_object_directory
from gitlab_groupsync.state import StateError, StateStore, atomic_write_json, utc_now

if TYPE_CHECKING:
    from gitlab_groupsync.reconcile import LifecycleReconciler

_FORMAT_EXTENSIONS = {
    "markdown": ".md",
    "rdoc": ".rdoc",
    "asciidoc": ".adoc",
    "org": ".org",
}
_LIMITATIONS = (
    "Export uses the documented Group Wikis REST API because no clone URL is "
    "provided by that API or verified on a licensed instance.",
    "Attachment links and source references are preserved verbatim; attachment "
    "payloads are not downloaded.",
    "Group-wiki export capability is covered by fixtures only; no live licensed "
    "GitLab instance or version was tested.",
)


@dataclass(frozen=True)
class GroupWikiSyncResult:
    """One selected group's independently observed outcome."""

    status: str
    failure: bool
    evidence: str


def group_path(destination: Path, full_path: str, group_id: int) -> Path:
    """Create or validate a contained managed group metadata directory."""
    try:
        target = ensure_object_directory(destination, "group", full_path, group_id)
    except (ReconcileError, UnsafePathError) as exc:
        raise PathSafetyError(str(exc)) from exc
    wiki = target / "wiki"
    if wiki.is_symlink():
        raise PathSafetyError("group wiki destination must not be a symlink")
    return target


class GroupWikiExporter:
    """Materialize complete deterministic source snapshots for selected groups."""

    def __init__(
        self,
        client: GitLabClient,
        store: StateStore,
        destination: Path,
        base_url: str,
        lifecycle: "LifecycleReconciler | None" = None,
    ) -> None:
        self.client = client
        self.store = store
        self.destination = destination
        self.base_url = base_url.rstrip("/")
        self.lifecycle = lifecycle

    def sync_group(
        self, group_id: int, full_path: str, base: Path
    ) -> GroupWikiSyncResult:
        """Fetch and publish one selected group without affecting any sibling."""
        attempted = utc_now()
        recovery_failures = self._recover(group_id)
        try:
            result = self.client.group_wiki_pages(group_id)
        except DiscoveryError as exc:
            self._failure(group_id, "error", str(exc), attempted)
            return GroupWikiSyncResult("error", True, str(exc))
        if result.status_code in {401, 403, 404}:
            evidence = f"Group Wikis API returned HTTP {result.status_code}"
            self._failure(
                group_id,
                "unavailable",
                evidence,
                attempted,
                extra=(
                    "The observed response cannot distinguish missing, hidden, "
                    "forbidden, disabled, or unsupported capability.",
                ),
            )
            return GroupWikiSyncResult("unavailable", True, evidence)

        assert result.pages is not None
        if not result.pages:
            try:
                if self.lifecycle is None:
                    self._remove_active(base / "wiki", group_id)
                else:
                    self.lifecycle.retire_component(
                        "group",
                        group_id,
                        full_path,
                        "wiki",
                        "conclusively_empty_upstream",
                    )
                snapshot, _ = self._snapshot(group_id, full_path, ())
                raw_path = (
                    self.destination / ".sync/raw/groups" / str(group_id) / "wiki.json"
                )
                self._write_json_if_changed(raw_path, snapshot)
            except (OSError, StateError, PathSafetyError, ReconcileError) as exc:
                self._failure(group_id, "error", str(exc), attempted)
                return GroupWikiSyncResult("error", True, str(exc))
            evidence = "Observed Group Wikis API HTTP 200 with an empty complete list."
            self.store.upsert_resource(
                "group",
                group_id,
                "wiki",
                "empty",
                last_attempt_at=attempted,
                last_success_at=attempted,
                limitations=(*_LIMITATIONS, evidence),
            )
            return GroupWikiSyncResult("empty", bool(recovery_failures), evidence)

        try:
            snapshot, files = self._snapshot(group_id, full_path, result.pages)
            revision = hashlib.sha256(
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            active = base / "wiki"
            if active.exists() and not self._valid_tree(active, group_id):
                raise PathSafetyError("destination collides with unmanaged group wiki")
            raw_path = (
                self.destination / ".sync/raw/groups" / str(group_id) / "wiki.json"
            )
            self._write_json_if_changed(raw_path, snapshot)
            previous = self.store.get_resource("group", group_id, "wiki") or {}
            if previous.get("revision") != revision or not self._valid_tree(
                active, group_id
            ):
                self._publish(group_id, active, files)
        except (DiscoveryError, OSError, StateError, PathSafetyError) as exc:
            self._failure(group_id, "error", str(exc), attempted)
            return GroupWikiSyncResult("error", True, str(exc))

        evidence = (
            f"Observed Group Wikis API HTTP 200 and retrieved {len(result.pages)} "
            "complete source page(s)."
        )
        self.store.upsert_resource(
            "group",
            group_id,
            "wiki",
            "ok",
            last_attempt_at=attempted,
            last_success_at=attempted,
            revision=revision,
            limitations=(*_LIMITATIONS, evidence),
        )
        return GroupWikiSyncResult("ok", bool(recovery_failures), evidence)

    def _snapshot(
        self,
        group_id: int,
        full_path: str,
        pages: tuple[Mapping[str, Any], ...],
    ) -> tuple[dict[str, Any], dict[Path, str]]:
        files: dict[Path, str] = {}
        normalized: list[dict[str, Any]] = []
        paths: set[Path] = set()
        for page in pages:
            slug = page.get("slug")
            source_format = page.get("format")
            content = page.get("content")
            title = page.get("title")
            encoding = page.get("encoding")
            if (
                not isinstance(slug, str)
                or not slug
                or not isinstance(source_format, str)
                or source_format.lower() not in _FORMAT_EXTENSIONS
                or not isinstance(content, str)
                or not isinstance(title, str)
                or (encoding is not None and not isinstance(encoding, str))
            ):
                raise DiscoveryError("GitLab returned an invalid group-wiki page")
            relative = self._page_path(slug, source_format.lower())
            sidecar = relative.with_name(relative.name + ".json")
            for candidate in (relative, sidecar):
                if candidate in paths or any(
                    parent in paths for parent in candidate.parents
                ):
                    raise PathSafetyError("group-wiki slugs collide on the filesystem")
                if any(candidate in existing.parents for existing in paths):
                    raise PathSafetyError("group-wiki slugs collide on the filesystem")
                paths.add(candidate)
            source_url = (
                f"{self.base_url}/{quote(full_path, safe='/')}/-/wikis/"
                f"{quote(slug, safe='/')}"
            )
            metadata = {
                "slug": slug,
                "title": title,
                "format": source_format.lower(),
                "encoding": encoding,
                "source_url": source_url,
            }
            files[relative] = content
            files[sidecar] = (
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            )
            normalized.append({**metadata, "content": content})
        normalized.sort(key=lambda value: str(value["slug"]))
        snapshot = {
            "group": {"id": group_id, "full_path": full_path},
            "mechanism": "GitLab Group Wikis REST API",
            "pages": normalized,
            "limitations": list(_LIMITATIONS),
        }
        return snapshot, files

    @staticmethod
    def _page_path(slug: str, source_format: str) -> Path:
        if slug.startswith("/") or "\\" in slug:
            raise PathSafetyError("unsafe group-wiki slug")
        parts = slug.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise PathSafetyError("unsafe group-wiki slug")
        extension = _FORMAT_EXTENSIONS[source_format]
        if not parts[-1].lower().endswith(extension):
            parts[-1] += extension
        return Path(*parts)

    def _publish(self, group_id: int, active: Path, files: Mapping[Path, str]) -> None:
        staging_root = self.destination / ".sync/staging"
        assert_no_symlinks(staging_root)
        staging_root.mkdir(parents=True, exist_ok=True)
        parent = Path(
            tempfile.mkdtemp(prefix=f"group-wiki-{group_id}-", dir=staging_root)
        )
        staged = parent / "wiki"
        staged.mkdir()
        marker = {"object_kind": "group", "object_id": group_id, "resource": "wiki"}
        self._write_staged(
            staged / ".gitlab-groupsync.json",
            json.dumps(marker, sort_keys=True) + "\n",
        )
        for relative, content in files.items():
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            self._write_staged(target, content)
        directories = {staged, *(path.parent for path in staged.rglob("*"))}
        fsync_directories(tuple(sorted(directories)))
        backup = parent / "previous"
        recovery_id = self.store.record_recovery(
            "group_wiki_publication",
            "group",
            group_id,
            "prepared",
            source_path=str(staged.relative_to(self.destination)),
            destination_path=str(active.relative_to(self.destination)),
            details={"backup_path": str(backup.relative_to(self.destination))},
        )
        self._swap(recovery_id, group_id, staged, active, backup)

    @staticmethod
    def _write_staged(path: Path, content: str) -> None:
        with path.open("w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())

    def _swap(
        self,
        recovery_id: int,
        group_id: int,
        staged: Path,
        active: Path,
        backup: Path,
    ) -> None:
        if active.exists():
            if not self._valid_tree(active, group_id):
                raise PathSafetyError("destination collides with unmanaged group wiki")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(active, backup)
        self.store.update_recovery(recovery_id, "publishing")
        active.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, active)
        fsync_directories((staged.parent, active.parent))
        if backup.exists():
            shutil.rmtree(backup)
        self.store.update_recovery(recovery_id, "complete")
        shutil.rmtree(staged.parent, ignore_errors=True)

    def _recover(self, group_id: int) -> int:
        failures = 0
        for record in self.store.pending_recoveries(
            "group_wiki_publication", "group", group_id
        ):
            try:
                staged = contained_path(self.destination, record["source_path"])
                active = contained_path(
                    self.destination, record["destination_path"], create_parents=True
                )
                backup = contained_path(
                    self.destination, record["details"]["backup_path"]
                )
            except UnsafePathError:
                try:
                    self.store.update_recovery(record["id"], "abandoned")
                except StateError:
                    pass
                failures += 1
                continue
            try:
                if staged.exists():
                    self._swap(record["id"], group_id, staged, active, backup)
                elif self._valid_tree(active, group_id):
                    if backup.exists():
                        shutil.rmtree(backup)
                    self.store.update_recovery(record["id"], "complete")
                    shutil.rmtree(staged.parent, ignore_errors=True)
                elif backup.exists():
                    os.replace(backup, active)
                    self.store.update_recovery(record["id"], "abandoned")
                    failures += 1
                else:
                    self.store.update_recovery(record["id"], "abandoned")
                    failures += 1
            except (OSError, StateError, PathSafetyError):
                failures += 1
        return failures

    @staticmethod
    def _valid_tree(path: Path, group_id: int) -> bool:
        marker = path / ".gitlab-groupsync.json"
        if path.is_symlink() or marker.is_symlink() or not marker.is_file():
            return False
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return value == {
            "object_kind": "group",
            "object_id": group_id,
            "resource": "wiki",
        }

    def _remove_active(self, active: Path, group_id: int) -> None:
        if not active.exists():
            return
        if not self._valid_tree(active, group_id):
            raise PathSafetyError("destination collides with unmanaged group wiki")
        retired = self.destination / ".sync/staging" / f"empty-group-wiki-{group_id}"
        if retired.exists():
            shutil.rmtree(retired)
        os.replace(active, retired)
        shutil.rmtree(retired)

    @staticmethod
    def _write_json_if_changed(path: Path, value: Mapping[str, Any]) -> None:
        encoded = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        try:
            if path.read_bytes() == encoded:
                return
        except FileNotFoundError:
            pass
        atomic_write_json(path, value)

    def _failure(
        self,
        group_id: int,
        status: str,
        error: str,
        attempted: str,
        *,
        extra: tuple[str, ...] = (),
    ) -> None:
        previous = self.store.get_resource("group", group_id, "wiki") or {}
        self.store.upsert_resource(
            "group",
            group_id,
            "wiki",
            status,
            last_attempt_at=attempted,
            last_success_at=previous.get("last_success_at"),
            revision=previous.get("revision"),
            last_error=error,
            retained_content=bool(previous.get("last_success_at")),
            limitations=(*_LIMITATIONS, *extra),
        )


def group_wiki_limitations() -> tuple[str, ...]:
    """Return stable public coverage limitations for disabled group metadata."""
    return _LIMITATIONS
