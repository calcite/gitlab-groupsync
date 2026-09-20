"""Minimal authenticated GitLab REST client and inventory discovery."""

import ssl
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Self
from urllib.parse import quote, urlsplit, urlunsplit

import httpx


class DiscoveryError(Exception):
    """A redacted failure that makes a discovery result non-authoritative."""


@dataclass(frozen=True, order=True)
class InventoryObject:
    """Immutable stable identity and mutable display path from GitLab."""

    id: int
    full_path: str


@dataclass(frozen=True)
class Inventory:
    """A GitLab group hierarchy inventory and its traversal completeness."""

    root_group: InventoryObject
    groups: tuple[InventoryObject, ...]
    projects: tuple[InventoryObject, ...]
    complete: bool


@dataclass(frozen=True)
class DriftObject:
    """One catalog/live discrepancy."""

    kind: str
    id: int
    catalog_path: str | None
    live_path: str | None


@dataclass(frozen=True)
class InventoryDiff:
    """Read-only inventory drift grouped by downstream reporting category."""

    added: tuple[DriftObject, ...]
    absent: tuple[DriftObject, ...]
    renamed: tuple[DriftObject, ...]
    path_reused: tuple[DriftObject, ...]


@dataclass(frozen=True)
class ProjectDetails:
    """Validated project fields needed by Git resource synchronization."""

    id: int
    full_path: str
    default_branch: str | None
    empty_repository: bool
    ssh_url: str
    http_url: str
    wiki_enabled: bool


@dataclass(frozen=True)
class WikiProbe:
    """Observed project-wiki API evidence without inferred server capability."""

    status_code: int
    page_count: int | None


@dataclass(frozen=True)
class GroupWikiPages:
    """Complete group-wiki REST result or exact expected HTTP evidence."""

    status_code: int
    pages: tuple[Mapping[str, Any], ...] | None


@dataclass(frozen=True)
class WorkItemHierarchy:
    """Optional parent/child relationships exposed by the GraphQL work-item API."""

    parent: Mapping[str, Any] | None
    children: tuple[Mapping[str, Any], ...]
    limitations: tuple[str, ...] = ()


class GitLabClient:
    """A testable, redirect-resistant client for GitLab discovery endpoints."""

    _TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float,
        max_attempts: int,
        ca_bundle: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        parsed = urlsplit(base_url)
        api_path = f"{parsed.path.rstrip('/')}/api/v4/"
        self._api_url = httpx.URL(
            urlunsplit((parsed.scheme, parsed.netloc, api_path, "", ""))
        )
        self._graphql_url = httpx.URL(
            urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    f"{parsed.path.rstrip('/')}/api/graphql",
                    "",
                    "",
                )
            )
        )
        self._origin = (
            self._api_url.scheme,
            self._api_url.host,
            self._api_url.port,
        )
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._owns_client = client is None
        if client is None:
            verify: ssl.SSLContext | bool = True
            if ca_bundle:
                try:
                    verify = ssl.create_default_context(cafile=ca_bundle)
                except OSError as exc:
                    raise DiscoveryError("custom CA bundle cannot be loaded") from exc
            client = httpx.Client(
                headers={"PRIVATE-TOKEN": token},
                timeout=timeout,
                verify=verify,
                follow_redirects=False,
                trust_env=False,
            )
        self._client = client

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        if self._owns_client:
            self._client.close()

    def get_object(self, endpoint: str) -> Mapping[str, Any]:
        """Retrieve and validate one JSON object."""
        response = self._request(endpoint, {})
        try:
            value = response.json()
        except ValueError as exc:
            raise DiscoveryError(
                f"GitLab returned invalid JSON for {endpoint}"
            ) from exc
        if not isinstance(value, dict):
            raise DiscoveryError(f"GitLab returned an invalid object for {endpoint}")
        return value

    def get_optional_object(self, endpoint: str) -> Mapping[str, Any] | None:
        """Retrieve an object from an endpoint that may not exist on this server."""
        response = self._request(endpoint, {}, allowed_statuses=frozenset({404}))
        if response.status_code == 404:
            return None
        try:
            value = response.json()
        except ValueError as exc:
            raise DiscoveryError(
                f"GitLab returned invalid JSON for {endpoint}"
            ) from exc
        if not isinstance(value, dict):
            raise DiscoveryError(f"GitLab returned an invalid object for {endpoint}")
        return value

    def probe(self, endpoint: str) -> int:
        """Return an expected capability status without traversing its content."""
        response = self._request(
            endpoint,
            {"per_page": 1},
            allowed_statuses=frozenset({401, 403, 404}),
        )
        return response.status_code

    def project_details(self, project_id: int) -> ProjectDetails:
        """Retrieve and validate current clone/default-branch project metadata."""
        value = self.get_object(f"projects/{project_id}")
        identity = _parse_object(value, "project")
        default_branch = value.get("default_branch")
        empty_repository = value.get("empty_repo", default_branch is None)
        ssh_url = value.get("ssh_url_to_repo")
        http_url = value.get("http_url_to_repo")
        wiki_access = value.get("wiki_access_level")
        wiki_enabled = value.get("wiki_enabled", wiki_access != "disabled")
        if (
            identity.id != project_id
            or (default_branch is not None and not isinstance(default_branch, str))
            or not isinstance(empty_repository, bool)
            or not isinstance(ssh_url, str)
            or not ssh_url
            or not isinstance(http_url, str)
            or not http_url
            or not isinstance(wiki_enabled, bool)
        ):
            raise DiscoveryError("GitLab returned invalid project sync details")
        return ProjectDetails(
            identity.id,
            identity.full_path,
            default_branch,
            empty_repository,
            ssh_url,
            http_url,
            wiki_enabled,
        )

    def probe_project_wiki(self, project_id: int) -> WikiProbe:
        """List all wiki pages or retain the exact expected HTTP failure evidence."""
        endpoint = f"projects/{project_id}/wikis"
        response = self._request(
            endpoint,
            {"per_page": 100, "page": 1},
            allowed_statuses=frozenset({401, 403, 404}),
        )
        if not response.is_success:
            return WikiProbe(response.status_code, None)
        try:
            values = response.json()
        except ValueError as exc:
            raise DiscoveryError(
                f"GitLab returned invalid JSON for {endpoint} page 1"
            ) from exc
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise DiscoveryError(
                f"GitLab returned an invalid list for {endpoint} page 1"
            )
        count = len(values)
        next_page = response.headers.get("x-next-page")
        if not next_page and len(values) == 100:
            next_page = "2"
        page = 1
        while next_page:
            if (
                not next_page.isascii()
                or not next_page.isdigit()
                or int(next_page) <= page
            ):
                raise DiscoveryError(
                    f"GitLab returned invalid pagination for {endpoint}"
                )
            page = int(next_page)
            response = self._request(endpoint, {"per_page": 100, "page": page})
            try:
                values = response.json()
            except ValueError as exc:
                raise DiscoveryError(
                    f"GitLab returned invalid JSON for {endpoint} page {page}"
                ) from exc
            if not isinstance(values, list) or any(
                not isinstance(value, dict) for value in values
            ):
                raise DiscoveryError(
                    f"GitLab returned an invalid list for {endpoint} page {page}"
                )
            count += len(values)
            next_page = response.headers.get("x-next-page")
            if not next_page and len(values) == 100:
                next_page = str(page + 1)
        return WikiProbe(200, count)

    def group_wiki_pages(self, group_id: int) -> GroupWikiPages:
        """List every page and retrieve each page's complete unrendered source."""
        endpoint = f"groups/{group_id}/wikis"
        response = self._request(
            endpoint,
            {"per_page": 100, "page": 1},
            allowed_statuses=frozenset({401, 403, 404}),
        )
        if not response.is_success:
            return GroupWikiPages(response.status_code, None)

        listed: list[Mapping[str, Any]] = []
        page = 1
        while True:
            try:
                values = response.json()
            except ValueError as exc:
                raise DiscoveryError(
                    f"GitLab returned invalid JSON for {endpoint} page {page}"
                ) from exc
            if not isinstance(values, list) or any(
                not isinstance(value, dict) for value in values
            ):
                raise DiscoveryError(
                    f"GitLab returned an invalid list for {endpoint} page {page}"
                )
            listed.extend(values)
            next_page = response.headers.get("x-next-page")
            if not next_page and len(values) == 100:
                next_page = str(page + 1)
            if not next_page:
                break
            if (
                not next_page.isascii()
                or not next_page.isdigit()
                or int(next_page) <= page
            ):
                raise DiscoveryError(
                    f"GitLab returned invalid pagination for {endpoint}"
                )
            page = int(next_page)
            response = self._request(endpoint, {"per_page": 100, "page": page})

        complete = []
        for value in listed:
            slug = value.get("slug")
            if not isinstance(slug, str) or not slug:
                raise DiscoveryError("GitLab returned an invalid group-wiki slug")
            complete.append(
                self.get_object(f"groups/{group_id}/wikis/{quote(slug, safe='')}")
            )
        return GroupWikiPages(200, tuple(complete))

    def iter_project_work_items(
        self, project_id: int, *, updated_after: str | None = None
    ) -> Iterator[Mapping[str, Any]]:
        """List every accessible issue and task explicitly, including closed items."""
        seen: set[int] = set()
        for item_type in ("issue", "task"):
            params: dict[str, str | int | bool] = {
                "scope": "all",
                "state": "all",
                "issue_type": item_type,
                "order_by": "updated_at",
                "sort": "asc",
            }
            if updated_after is not None:
                params["updated_after"] = updated_after
            for value in self.iter_list(f"projects/{project_id}/issues", params):
                item_id = value.get("id")
                if isinstance(item_id, bool) or not isinstance(item_id, int):
                    raise DiscoveryError(
                        "GitLab returned an invalid work-item identity"
                    )
                if item_id not in seen:
                    seen.add(item_id)
                    yield value

    def issue_discussions(
        self, project_id: int, issue_iid: int
    ) -> tuple[Mapping[str, Any], ...]:
        """Retrieve every issue discussion page, including individual notes."""
        return tuple(
            self.iter_list(f"projects/{project_id}/issues/{issue_iid}/discussions", {})
        )

    def project_issue(self, project_id: int, issue_iid: int) -> Mapping[str, Any]:
        """Retrieve one retry candidate by project-local identity."""
        return self.get_object(f"projects/{project_id}/issues/{issue_iid}")

    def issue_links(
        self, project_id: int, issue_iid: int
    ) -> tuple[Mapping[str, Any], ...]:
        """Retrieve every REST issue-link page."""
        return tuple(
            self.iter_list(f"projects/{project_id}/issues/{issue_iid}/links", {})
        )

    def work_item_hierarchy(
        self, project_path: str, issue_iid: int
    ) -> WorkItemHierarchy:
        """Query only hierarchy missing from REST, paginating the child connection."""
        query = """query WorkItemHierarchy($path: ID!, $iid: String!, $after: String) {
          namespace(fullPath: $path) {
            workItem(iid: $iid) {
              widgets {
                ... on WorkItemWidgetHierarchy {
                  parent { id iid title webUrl }
                  children(first: 100, after: $after) {
                    nodes { id iid title webUrl }
                    pageInfo { hasNextPage endCursor }
                  }
                }
              }
            }
          }
        }"""
        after: str | None = None
        parent: Mapping[str, Any] | None = None
        children: list[Mapping[str, Any]] = []
        while True:
            value = self._graphql(
                query, {"path": project_path, "iid": str(issue_iid), "after": after}
            )
            errors = value.get("errors")
            if errors:
                return WorkItemHierarchy(
                    None,
                    (),
                    (
                        "parent/child hierarchy unavailable because GitLab GraphQL "
                        "returned errors; hierarchy completeness is not claimed",
                    ),
                )
            data = value.get("data")
            namespace = data.get("namespace") if isinstance(data, dict) else None
            item = namespace.get("workItem") if isinstance(namespace, dict) else None
            widgets = item.get("widgets") if isinstance(item, dict) else None
            if not isinstance(widgets, list):
                return WorkItemHierarchy(
                    None,
                    (),
                    ("parent/child hierarchy was not exposed for this work item",),
                )
            hierarchy = next(
                (
                    widget
                    for widget in widgets
                    if isinstance(widget, dict) and "children" in widget
                ),
                None,
            )
            if hierarchy is None:
                return WorkItemHierarchy(None, ())
            candidate_parent = hierarchy.get("parent")
            if candidate_parent is not None and not isinstance(candidate_parent, dict):
                raise DiscoveryError("GitLab returned invalid work-item hierarchy")
            parent = candidate_parent
            connection = hierarchy.get("children")
            if not isinstance(connection, dict):
                raise DiscoveryError("GitLab returned invalid work-item hierarchy")
            nodes = connection.get("nodes")
            page_info = connection.get("pageInfo")
            if (
                not isinstance(nodes, list)
                or any(not isinstance(node, dict) for node in nodes)
                or not isinstance(page_info, dict)
            ):
                raise DiscoveryError("GitLab returned invalid work-item hierarchy")
            children.extend(nodes)
            if not page_info.get("hasNextPage"):
                return WorkItemHierarchy(parent, tuple(children))
            cursor = page_info.get("endCursor")
            if not isinstance(cursor, str) or not cursor or cursor == after:
                raise DiscoveryError("GitLab returned invalid GraphQL pagination")
            after = cursor

    def iter_list(
        self, endpoint: str, params: Mapping[str, str | int | bool]
    ) -> Iterator[Mapping[str, Any]]:
        """Retrieve every offset-paginated JSON list page."""
        page = 1
        while True:
            query = dict(params)
            query.update(per_page=100, page=page)
            response = self._request(endpoint, query)
            try:
                values = response.json()
            except ValueError as exc:
                raise DiscoveryError(
                    f"GitLab returned invalid JSON for {endpoint} page {page}"
                ) from exc
            if not isinstance(values, list) or any(
                not isinstance(value, dict) for value in values
            ):
                raise DiscoveryError(
                    f"GitLab returned an invalid list for {endpoint} page {page}"
                )
            yield from values
            next_page = response.headers.get("x-next-page")
            if next_page:
                if (
                    not next_page.isascii()
                    or not next_page.isdigit()
                    or int(next_page) <= page
                ):
                    raise DiscoveryError(
                        f"GitLab returned invalid pagination for {endpoint}"
                    )
                page = int(next_page)
                continue
            if len(values) == 100:
                page += 1
                continue
            return

    def _request(
        self,
        endpoint: str,
        params: Mapping[str, str | int | bool],
        *,
        allowed_statuses: frozenset[int] = frozenset(),
    ) -> httpx.Response:
        if endpoint.startswith("/") or "?" in endpoint or "#" in endpoint:
            raise DiscoveryError("unsafe GitLab API endpoint")
        url = self._api_url.join(endpoint)
        if (url.scheme, url.host, url.port) != self._origin:
            raise DiscoveryError("refusing a cross-host GitLab API request")

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                if attempt == self._max_attempts:
                    raise DiscoveryError(
                        f"GitLab request failed for {endpoint} after {attempt} attempts"
                    ) from exc
                self._sleep(min(float(2 ** (attempt - 1)), 5.0))
                continue
            if response.is_success or response.status_code in allowed_statuses:
                return response
            if (
                response.status_code in self._TRANSIENT_STATUSES
                and attempt < self._max_attempts
            ):
                self._sleep(self._retry_delay(response, attempt))
                continue
            raise DiscoveryError(
                f"GitLab returned HTTP {response.status_code} for {endpoint}"
            )
        raise AssertionError("retry loop must return or raise")  # pragma: no cover

    def _graphql(
        self, query: str, variables: Mapping[str, str | None]
    ) -> Mapping[str, Any]:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.post(
                    self._graphql_url, json={"query": query, "variables": variables}
                )
            except httpx.HTTPError as exc:
                if attempt == self._max_attempts:
                    raise DiscoveryError(
                        f"GitLab GraphQL request failed after {attempt} attempts"
                    ) from exc
                self._sleep(min(float(2 ** (attempt - 1)), 5.0))
                continue
            if (
                response.status_code in self._TRANSIENT_STATUSES
                and attempt < self._max_attempts
            ):
                self._sleep(self._retry_delay(response, attempt))
                continue
            if not response.is_success:
                raise DiscoveryError(
                    f"GitLab returned HTTP {response.status_code} for GraphQL hierarchy"
                )
            try:
                value = response.json()
            except ValueError as exc:
                raise DiscoveryError("GitLab returned invalid GraphQL JSON") from exc
            if not isinstance(value, dict):
                raise DiscoveryError("GitLab returned an invalid GraphQL response")
            return value
        raise AssertionError("retry loop must return or raise")  # pragma: no cover

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        """Interpret Retry-After seconds or HTTP dates with a bounded wait."""
        value = response.headers.get("retry-after")
        delay = float(2 ** (attempt - 1))
        if value is not None:
            try:
                delay = float(value)
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(value)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    delay = (parsed - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    pass
        return max(0.0, min(delay, 5.0))


def discover_inventory(
    client: GitLabClient,
    root: str | int,
    *,
    include_shared: bool,
    include_archived: bool,
) -> Inventory:
    """Resolve a root and completely enumerate its groups and projects."""
    root_ref = quote(str(root), safe="")
    root_group = _parse_object(client.get_object(f"groups/{root_ref}"), "group")
    groups = _deduplicate(
        "group",
        (
            root_group,
            *(
                _parse_object(value, "group")
                for value in client.iter_list(
                    f"groups/{root_group.id}/descendant_groups", {}
                )
            ),
        ),
    )
    project_params: dict[str, str | int | bool] = {
        "include_subgroups": True,
        "with_shared": include_shared,
    }
    if not include_archived:
        project_params["archived"] = False
    projects = _deduplicate(
        "project",
        (
            _parse_object(value, "project")
            for value in client.iter_list(
                f"groups/{root_group.id}/projects", project_params
            )
        ),
    )
    return Inventory(root_group, groups, projects, complete=True)


def compare_inventories(catalog: Inventory, live: Inventory) -> InventoryDiff:
    """Classify stable-ID and path drift without mutating either inventory."""
    if not live.complete:
        raise DiscoveryError("cannot compare an incomplete live inventory")

    added: list[DriftObject] = []
    absent: list[DriftObject] = []
    renamed: list[DriftObject] = []
    path_reused: list[DriftObject] = []
    for kind, old_values, new_values in (
        ("group", catalog.groups, live.groups),
        ("project", catalog.projects, live.projects),
    ):
        old_by_id = {value.id: value for value in old_values}
        new_by_id = {value.id: value for value in new_values}
        old_by_path = {value.full_path: value for value in old_values}
        new_by_path = {value.full_path: value for value in new_values}
        for object_id in sorted(new_by_id.keys() - old_by_id.keys()):
            value = new_by_id[object_id]
            added.append(DriftObject(kind, object_id, None, value.full_path))
        for object_id in sorted(old_by_id.keys() - new_by_id.keys()):
            value = old_by_id[object_id]
            absent.append(DriftObject(kind, object_id, value.full_path, None))
        for object_id in sorted(old_by_id.keys() & new_by_id.keys()):
            old = old_by_id[object_id]
            new = new_by_id[object_id]
            if old.full_path != new.full_path:
                renamed.append(
                    DriftObject(kind, object_id, old.full_path, new.full_path)
                )
        for path in sorted(old_by_path.keys() & new_by_path.keys()):
            old = old_by_path[path]
            new = new_by_path[path]
            if old.id != new.id:
                path_reused.append(DriftObject(kind, new.id, path, path))
    return InventoryDiff(
        tuple(added), tuple(absent), tuple(renamed), tuple(path_reused)
    )


def _parse_object(value: Mapping[str, Any], kind: str) -> InventoryObject:
    object_id = value.get("id")
    path_key = "path_with_namespace" if kind == "project" else "full_path"
    full_path = value.get(path_key)
    if (
        isinstance(object_id, bool)
        or not isinstance(object_id, int)
        or object_id < 1
        or not isinstance(full_path, str)
        or not full_path
    ):
        raise DiscoveryError(f"GitLab returned an invalid {kind} identity")
    return InventoryObject(object_id, full_path)


def _deduplicate(
    kind: str, values: Iterator[InventoryObject] | tuple[InventoryObject, ...]
) -> tuple[InventoryObject, ...]:
    by_id: dict[int, InventoryObject] = {}
    for value in values:
        previous = by_id.get(value.id)
        if previous is not None and previous != value:
            raise DiscoveryError(
                f"GitLab returned conflicting {kind} identity for ID {value.id}"
            )
        by_id[value.id] = value
    return tuple(sorted(by_id.values()))
