"""Discovery client, inventory, drift, and persistence tests."""

import json
import os
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from click.testing import CliRunner
from ruamel.yaml import YAML

from gitlab_groupsync import cli
from gitlab_groupsync.discovery import inventory_from_config, refresh_catalog
from gitlab_groupsync.gitlab_api import (
    DiscoveryError,
    GitLabClient,
    GroupWikiPages,
    Inventory,
    InventoryDiff,
    InventoryObject,
    ProjectDetails,
    WikiProbe,
    compare_inventories,
    discover_inventory,
)


def _inventory(
    *,
    root_id: int = 1,
    root_path: str = "root",
    groups: tuple[tuple[int, str], ...] = ((1, "root"),),
    projects: tuple[tuple[int, str], ...] = (),
    complete: bool = True,
) -> Inventory:
    return Inventory(
        InventoryObject(root_id, root_path),
        tuple(InventoryObject(*value) for value in groups),
        tuple(InventoryObject(*value) for value in projects),
        complete,
    )


class _GitLabHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict[str, list[str]], str | None]] = []
    fail_projects_page = False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        token = self.headers.get("PRIVATE-TOKEN")
        type(self).requests.append((parsed.path, query, token))
        status = 200
        headers: dict[str, str] = {}
        if parsed.path == "/gitlab/api/v4/groups/root%2Fteam":
            body: Any = {"id": 1, "full_path": "root/team"}
        elif parsed.path == "/gitlab/api/v4/groups/1/descendant_groups":
            if query["page"] == ["1"]:
                body = [{"id": 3, "full_path": "root/team/empty"}]
                headers["X-Next-Page"] = "2"
            else:
                body = [{"id": 2, "full_path": "root/team/nested"}]
        elif parsed.path == "/gitlab/api/v4/groups/1/projects":
            if self.fail_projects_page:
                status, body = 503, {"message": "secret should not be shown"}
            elif query["page"] == ["1"]:
                body = [
                    {
                        "id": 20,
                        "path_with_namespace": "root/team/nested/archived",
                        "archived": True,
                    },
                    {
                        "id": 10,
                        "path_with_namespace": "root/team/app",
                        "archived": False,
                    },
                ]
                headers["X-Next-Page"] = "2"
            else:
                body = [
                    {"id": 10, "path_with_namespace": "root/team/app"},
                ]
                if query["with_shared"] == ["true"]:
                    body.append({"id": 30, "path_with_namespace": "external/shared"})
        elif parsed.path in {
            "/gitlab/api/v4/projects/10",
            "/gitlab/api/v4/projects/20",
        }:
            project_id = int(parsed.path.rsplit("/", 1)[1])
            body = {
                "id": project_id,
                "path_with_namespace": "root/team/app",
                "statistics": {"lfs_objects_size": 128 if project_id == 10 else 0},
            }
        else:
            status, body = 404, {"message": "missing"}
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def _fake_gitlab() -> Iterator[str]:
    _GitLabHandler.requests = []
    _GitLabHandler.fail_projects_page = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GitLabHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/gitlab"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _config_text(url: str, *, shared: bool = False) -> str:
    return f"""gitlab:
  url: {url}
  group: root/team
  token_env: TEST_TOKEN
storage:
  destination: /tmp/reference
sync:
  include_shared_projects: {str(shared).lower()}
  max_attempts: 1
inventory:
  root_group:
    id: 1
    full_path: old-root
  groups:
    - id: 1
      full_path: old-root
      wiki: true
    - id: 99
      full_path: old-root/absent
      wiki: true
  projects:
    - id: 10
      full_path: old-root/app
      repository: true
      wiki: true
      work_items: false
    - id: 99
      full_path: old-root/absent
      repository: true
      wiki: true
      work_items: true
hand_managed:
  value: retained
"""


def test_cli_discovery_uses_real_http_pagination_and_refreshes(tmp_path: Path) -> None:
    with _fake_gitlab() as url:
        path = tmp_path / "config.yaml"
        # Unknown hand-maintained top-level keys are rejected by normal validation,
        # so preservation is exercised directly below. The CLI fixture stays valid.
        path.write_text(
            _config_text("http://persisted.invalid").replace(
                "hand_managed:\n  value: retained\n", ""
            )
        )
        result = CliRunner().invoke(
            cli.main,
            [
                "discover",
                "--config",
                str(path),
                "--gitlab--url",
                url,
            ],
            env={"TEST_TOKEN": "private-value"},
        )

    assert result.exit_code == 0, result.output
    assert "Discovered 3 groups and 2 projects" in result.output
    persisted = YAML(typ="safe").load(path.read_text())
    assert persisted["gitlab"]["url"] == "http://persisted.invalid"
    assert [item["id"] for item in persisted["inventory"]["groups"]] == [1, 2, 3]
    assert [item["id"] for item in persisted["inventory"]["projects"]] == [10, 20]
    assert persisted["inventory"]["groups"][0]["wiki"] is True
    assert persisted["inventory"]["projects"][0]["repository"] is True
    assert persisted["inventory"]["projects"][1]["repository"] is False
    assert persisted["inventory"]["projects"][0]["lfs"] is False
    assert "lfs" not in persisted["inventory"]["projects"][1]
    assert "private-value" not in path.read_text()
    assert all(request[2] == "private-value" for request in _GitLabHandler.requests)
    project_queries = [
        request[1]
        for request in _GitLabHandler.requests
        if request[0].endswith("projects")
    ]
    assert all(query["include_subgroups"] == ["true"] for query in project_queries)
    assert all(query["with_shared"] == ["false"] for query in project_queries)
    assert all("archived" not in query for query in project_queries)
    assert all(
        query["statistics"] == ["true"]
        for endpoint, query, _ in _GitLabHandler.requests
        if "/projects/" in endpoint
    )


def test_shared_inclusion_and_archived_exclusion_parameters() -> None:
    with _fake_gitlab() as url:
        with GitLabClient(url, "token", timeout=1, max_attempts=1) as client:
            inventory = discover_inventory(
                client,
                "root/team",
                include_shared=True,
                include_archived=False,
            )
    assert [item.id for item in inventory.projects] == [10, 20, 30]
    project_queries = [
        request[1]
        for request in _GitLabHandler.requests
        if request[0].endswith("projects")
    ]
    assert all(query["with_shared"] == ["true"] for query in project_queries)
    assert all(query["archived"] == ["false"] for query in project_queries)


def test_failed_page_leaves_configuration_byte_identical(tmp_path: Path) -> None:
    with _fake_gitlab() as url:
        path = tmp_path / "config.yaml"
        original = _config_text(url).replace("hand_managed:\n  value: retained\n", "")
        path.write_text(original)
        _GitLabHandler.fail_projects_page = True
        result = CliRunner().invoke(
            cli.main,
            ["discover", "--config", str(path)],
            env={"TEST_TOKEN": "private-value"},
        )
    assert result.exit_code == 2
    assert "HTTP 503" in result.output
    assert "secret should not be shown" not in result.output
    assert path.read_text() == original


def _mock_client(
    handler: Any, *, attempts: int = 1, sleep: Any = lambda _: None
) -> GitLabClient:
    return GitLabClient(
        "https://gitlab.example.test/base",
        "unused",
        timeout=1,
        max_attempts=attempts,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleep,
    )


def test_client_retries_transient_status_and_honors_bounded_retry_after() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "99"})
        if calls == 2:
            return httpx.Response(503, headers={"Retry-After": "invalid"})
        return httpx.Response(200, json={"id": 1})

    client = _mock_client(handler, attempts=3, sleep=sleeps.append)
    assert client.get_object("groups/1") == {"id": 1}
    assert sleeps == [5.0, 2.0]
    client.__exit__()


def test_client_retries_transport_errors_and_redacts_final_error() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("token-in-transport", request=request)

    client = _mock_client(handler, attempts=2, sleep=sleeps.append)
    with pytest.raises(DiscoveryError, match="after 2 attempts") as raised:
        client.get_object("groups/1")
    assert "token-in-transport" not in str(raised.value)
    assert sleeps == [1.0]
    client.__exit__()


@pytest.mark.parametrize(
    ("handler", "method", "message"),
    [
        (lambda r: httpx.Response(200, text="no-json"), "object", "invalid JSON"),
        (lambda r: httpx.Response(200, json=[]), "object", "invalid object"),
        (lambda r: httpx.Response(200, text="no-json"), "list", "invalid JSON"),
        (lambda r: httpx.Response(200, json={}), "list", "invalid list"),
        (
            lambda r: httpx.Response(200, json=[1]),
            "list",
            "invalid list",
        ),
    ],
)
def test_client_rejects_invalid_json_shapes(
    handler: Any, method: str, message: str
) -> None:
    client = _mock_client(handler)
    with pytest.raises(DiscoveryError, match=message):
        if method == "object":
            client.get_object("groups/1")
        else:
            list(client.iter_list("groups/1/projects", {}))
    client.__exit__()


def test_client_rejects_unsafe_cross_host_and_bad_pagination() -> None:
    client = _mock_client(
        lambda r: httpx.Response(200, json=[], headers={"X-Next-Page": "x"})
    )
    with pytest.raises(DiscoveryError, match="unsafe"):
        client.get_object("/groups/1")
    with pytest.raises(DiscoveryError, match="cross-host"):
        client.get_object("https://other.example/api/v4/groups/1")
    with pytest.raises(DiscoveryError, match="invalid pagination"):
        list(client.iter_list("groups/1/projects", {}))
    client.__exit__()


def test_full_page_without_headers_fetches_one_more_page() -> None:
    pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        pages.append(page)
        values = [{"id": value} for value in range(100)] if page == "1" else []
        return httpx.Response(200, json=values)

    client = _mock_client(handler)
    assert len(list(client.iter_list("groups", {}))) == 100
    assert pages == ["1", "2"]
    client.__exit__()


def test_client_nonretryable_and_exhausted_transient_statuses() -> None:
    for status in (401, 500):
        client = _mock_client(lambda r, status=status: httpx.Response(status))
        with pytest.raises(DiscoveryError, match=f"HTTP {status}"):
            client.get_object("groups/1")
        client.__exit__()


def test_auth_and_redirect_failures_are_not_retried_with_multiple_attempts() -> None:
    for status in (401, 403, 302):
        calls = 0

        def handler(request: httpx.Request, status: int = status) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(status, headers={"Location": "https://other.test/"})

        client = _mock_client(handler, attempts=4)
        with pytest.raises(DiscoveryError, match=f"HTTP {status}"):
            client.get_object("groups/1")
        assert calls == 1
        client.__exit__()


def test_retry_after_http_date_is_bounded() -> None:
    response = httpx.Response(
        429, headers={"Retry-After": "Sun, 20 Sep 2099 00:00:00 GMT"}
    )
    assert GitLabClient._retry_delay(response, 1) == 5.0
    malformed = httpx.Response(503, headers={"Retry-After": "not-a-date"})
    assert GitLabClient._retry_delay(malformed, 2) == 2.0
    naive = httpx.Response(
        429, headers={"Retry-After": "Sun, 20 Sep 2099 00:00:00 -0000"}
    )
    assert GitLabClient._retry_delay(naive, 1) == 5.0


def test_work_item_rest_endpoints_and_graphql_hierarchy_pagination() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        requests.append((request.url.path, params))
        if request.method == "POST":
            variables = json.loads(request.content)["variables"]
            after = variables["after"]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "namespace": {
                            "workItem": {
                                "widgets": [
                                    {
                                        "parent": {"id": "p", "iid": "1"},
                                        "children": {
                                            "nodes": [{"id": after or "first"}],
                                            "pageInfo": {
                                                "hasNextPage": after is None,
                                                "endCursor": "next"
                                                if after is None
                                                else None,
                                            },
                                        },
                                    }
                                ]
                            }
                        }
                    }
                },
            )
        path = request.url.path
        if path.endswith("/issues"):
            item_type = params["issue_type"]
            item_id = 1 if item_type == "issue" else 2
            route = "issues" if item_type == "issue" else "work_items"
            record = {
                "id": item_id,
                "iid": item_id,
                "issue_type": item_type,
                "title": f"{item_type.title()} {item_id}",
                "state": "opened",
                "description": "fixture",
                "web_url": f"https://git.example/root/app/-/{route}/{item_id}",
                "updated_at": "2026-09-20T00:00:00Z",
            }
            values = [record, dict(record)] if item_type == "task" else [record]
            return httpx.Response(200, json=values)
        if path.endswith("/discussions"):
            return httpx.Response(200, json=[{"id": "discussion"}])
        if path.endswith("/links"):
            return httpx.Response(200, json=[{"id": 2}])
        return httpx.Response(200, json={"id": 1})

    client = _mock_client(handler)
    items = list(client.iter_project_work_items(10, updated_after="then"))
    assert [
        (value["issue_type"], value["web_url"].split("/-/")[1]) for value in items
    ] == [
        ("issue", "issues/1"),
        ("task", "work_items/2"),
    ]
    assert client.issue_discussions(10, 1) == ({"id": "discussion"},)
    assert client.issue_links(10, 1) == ({"id": 2},)
    assert client.project_issue(10, 1) == {"id": 1}
    hierarchy = client.work_item_hierarchy("root/app", 1)
    assert hierarchy.parent == {"id": "p", "iid": "1"}
    assert [value["id"] for value in hierarchy.children] == ["first", "next"]
    issue_queries = [params for path, params in requests if path.endswith("/issues")]
    assert {query["issue_type"] for query in issue_queries} == {"issue", "task"}
    assert all(
        query["scope"] == "all" and query["state"] == "all" for query in issue_queries
    )
    assert all(query["updated_after"] == "then" for query in issue_queries)
    client.__exit__()


def test_gitlab_19_5_3_recorded_hierarchy_responses() -> None:
    """Replay human-captured live envelopes, including empty non-hierarchy widgets."""
    evidence = Path(__file__).parent.parent / "docs/live-evidence/gitlab-19.5.3"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        variables = json.loads(request.content)["variables"]
        assert variables["path"] == "zero-iot/lambda_api"
        assert variables["after"] is None
        iid = variables["iid"]
        calls.append(iid)
        return httpx.Response(
            200,
            content=(evidence / f"hierarchy-{iid}-response.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )

    client = _mock_client(handler)
    parent = client.work_item_hierarchy("zero-iot/lambda_api", 15)
    child = client.work_item_hierarchy("zero-iot/lambda_api", 16)
    assert parent.parent is None
    assert len(parent.children) == 1
    assert parent.children[0]["id"] == "gid://gitlab/WorkItem/4013"
    assert parent.children[0]["iid"] == "16"
    assert child.parent is not None
    assert child.parent["id"] == "gid://gitlab/WorkItem/3816"
    assert child.parent["iid"] == "15"
    assert child.children == ()
    assert parent.limitations == child.limitations == ()
    # A non-null endCursor with hasNextPage:false must not trigger another request.
    assert calls == ["15", "16"]
    client.__exit__()


def test_work_item_client_rejects_bad_identity_and_degrades_graphql_schema_errors() -> (
    None
):
    client = _mock_client(lambda request: httpx.Response(200, json=[{"id": True}]))
    with pytest.raises(DiscoveryError, match="work-item identity"):
        list(client.iter_project_work_items(1))
    client.__exit__()

    responses = iter(
        [
            {"errors": [{"message": "unknown widget"}]},
            {"data": {"namespace": {"workItem": None}}},
            {"data": {"namespace": {"workItem": {"widgets": []}}}},
        ]
    )
    client = _mock_client(lambda request: httpx.Response(200, json=next(responses)))
    assert (
        "completeness is not claimed"
        in client.work_item_hierarchy("root/app", 1).limitations[0]
    )
    assert "not exposed" in client.work_item_hierarchy("root/app", 1).limitations[0]
    assert client.work_item_hierarchy("root/app", 1).children == ()
    client.__exit__()


@pytest.mark.parametrize(
    ("hierarchy", "message"),
    [
        ({"parent": [], "children": {"nodes": [], "pageInfo": {}}}, "hierarchy"),
        ({"parent": None, "children": []}, "hierarchy"),
        ({"parent": None, "children": {"nodes": [1], "pageInfo": {}}}, "hierarchy"),
        (
            {
                "parent": None,
                "children": {
                    "nodes": [],
                    "pageInfo": {"hasNextPage": True, "endCursor": None},
                },
            },
            "pagination",
        ),
    ],
)
def test_graphql_hierarchy_shape_validation(
    hierarchy: dict[str, Any], message: str
) -> None:
    payload = {"data": {"namespace": {"workItem": {"widgets": [hierarchy]}}}}
    client = _mock_client(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(DiscoveryError, match=message):
        client.work_item_hierarchy("root/app", 1)
    client.__exit__()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401), "HTTP 401"),
        (httpx.Response(200, text="bad"), "invalid GraphQL JSON"),
        (httpx.Response(200, json=[]), "invalid GraphQL response"),
    ],
)
def test_graphql_response_failures(response: httpx.Response, message: str) -> None:
    client = _mock_client(lambda request: response)
    with pytest.raises(DiscoveryError, match=message):
        client._graphql("query", {})
    client.__exit__()


def test_graphql_retries_transport_and_transient_failures() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("secret", request=request)
        if calls == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": {}})

    client = _mock_client(handler, attempts=3, sleep=sleeps.append)
    assert client._graphql("query", {}) == {"data": {}}
    assert sleeps == [1.0, 2.0]
    client.__exit__()

    client = _mock_client(
        lambda request: (_ for _ in ()).throw(
            httpx.ConnectError("secret", request=request)
        )
    )
    with pytest.raises(DiscoveryError, match="after 1 attempts") as raised:
        client._graphql("query", {})
    assert "secret" not in str(raised.value)
    client.__exit__()


def test_optional_objects_and_capability_probes() -> None:
    responses = iter(
        (
            httpx.Response(404),
            httpx.Response(200, json={"version": "18.4"}),
            httpx.Response(404),
        )
    )
    client = _mock_client(lambda request: next(responses))
    assert client.get_optional_object("metadata") is None
    assert client.get_optional_object("version") == {"version": "18.4"}
    assert client.probe("groups/1/wikis") == 404
    client.__exit__()


def test_project_sync_details_and_wiki_probe_pagination() -> None:
    responses = iter(
        (
            httpx.Response(
                200,
                json={
                    "id": 7,
                    "path_with_namespace": "root/app",
                    "default_branch": "trunk",
                    "empty_repo": False,
                    "ssh_url_to_repo": "git@example:root/app.git",
                    "http_url_to_repo": "https://example/root/app.git",
                    "wiki_access_level": "enabled",
                },
            ),
            httpx.Response(200, json=[{"slug": "one"}], headers={"X-Next-Page": "2"}),
            httpx.Response(200, json=[{"slug": "two"}]),
            httpx.Response(404),
        )
    )
    client = _mock_client(lambda request: next(responses))
    assert client.project_details(7) == ProjectDetails(
        7,
        "root/app",
        "trunk",
        False,
        "git@example:root/app.git",
        "https://example/root/app.git",
        True,
    )
    assert client.probe_project_wiki(7) == WikiProbe(200, 2)
    assert client.probe_project_wiki(7) == WikiProbe(404, None)
    client.__exit__()


def test_group_wiki_api_paginates_and_retrieves_complete_unrendered_pages() -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        requests.append((str(request.url), params))
        if path.endswith("/groups/7/wikis"):
            if params["page"] == "1":
                return httpx.Response(
                    200,
                    json=[{"slug": "guide/start", "content": "incomplete"}],
                    headers={"X-Next-Page": "2"},
                )
            return httpx.Response(200, json=[{"slug": "home"}])
        slug = path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={
                "slug": "guide/start" if slug == "guide%2Fstart" else "home",
                "title": slug,
                "format": "markdown",
                "encoding": "UTF-8",
                "content": f"complete:{slug}",
            },
        )

    client = _mock_client(handler)
    result = client.group_wiki_pages(7)
    assert result.status_code == 200
    assert result.pages is not None
    assert [page["content"] for page in result.pages] == [
        "complete:start",
        "complete:home",
    ]
    assert "%2F" in requests[2][0]
    detail_queries = [
        params
        for url, params in requests
        if not url.split("?", 1)[0].endswith("/wikis")
    ]
    assert detail_queries == [{}, {}]
    client.__exit__()


@pytest.mark.parametrize("status", [401, 403, 404])
def test_group_wiki_api_preserves_expected_http_evidence(status: int) -> None:
    client = _mock_client(lambda request: httpx.Response(status))
    assert client.group_wiki_pages(7) == GroupWikiPages(status, None)
    client.__exit__()


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([httpx.Response(200, text="bad")], "invalid JSON"),
        ([httpx.Response(200, json={})], "invalid list"),
        (
            [httpx.Response(200, json=[], headers={"X-Next-Page": "bad"})],
            "invalid pagination",
        ),
        ([httpx.Response(200, json=[{}])], "invalid group-wiki slug"),
        (
            [
                httpx.Response(200, json=[], headers={"X-Next-Page": "2"}),
                httpx.Response(200, text="bad"),
            ],
            "invalid JSON",
        ),
    ],
)
def test_group_wiki_api_rejects_partial_or_invalid_lists(
    responses: list[httpx.Response], message: str
) -> None:
    values = iter(responses)
    client = _mock_client(lambda request: next(values))
    with pytest.raises(DiscoveryError, match=message):
        client.group_wiki_pages(7)
    client.__exit__()


def test_group_wiki_api_full_page_without_header_fetches_next_page() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200, json=[{"slug": str(value)} for value in range(100)]
            )
        if calls == 2:
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json={
                "slug": request.url.path.rsplit("/", 1)[-1],
                "title": "page",
                "format": "markdown",
                "content": "source",
            },
        )

    client = _mock_client(handler)
    assert len(client.group_wiki_pages(7).pages or ()) == 100
    assert calls == 102
    client.__exit__()


def test_wiki_probe_full_page_without_pagination_header() -> None:
    responses = iter(
        (
            httpx.Response(200, json=[{"slug": str(value)} for value in range(100)]),
            httpx.Response(200, json=[{"slug": str(value)} for value in range(100)]),
            httpx.Response(200, json=[]),
        )
    )
    client = _mock_client(lambda request: next(responses))
    assert client.probe_project_wiki(7) == WikiProbe(200, 200)
    client.__exit__()


@pytest.mark.parametrize(
    "value",
    [
        {"id": 8, "path_with_namespace": "root/app"},
        {
            "id": 7,
            "path_with_namespace": "root/app",
            "default_branch": 1,
            "empty_repo": False,
            "ssh_url_to_repo": "ssh",
            "http_url_to_repo": "https",
            "wiki_enabled": True,
        },
    ],
)
def test_project_sync_details_reject_invalid_values(value: dict[str, Any]) -> None:
    client = _mock_client(lambda request: httpx.Response(200, json=value))
    with pytest.raises(DiscoveryError, match="sync details"):
        client.project_details(7)
    client.__exit__()


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([httpx.Response(200, text="bad")], "invalid JSON"),
        ([httpx.Response(200, json={})], "invalid list"),
        (
            [httpx.Response(200, json=[], headers={"X-Next-Page": "bad"})],
            "invalid pagination",
        ),
        (
            [
                httpx.Response(200, json=[], headers={"X-Next-Page": "2"}),
                httpx.Response(200, text="bad"),
            ],
            "invalid JSON",
        ),
        (
            [
                httpx.Response(200, json=[], headers={"X-Next-Page": "2"}),
                httpx.Response(200, json={}),
            ],
            "invalid list",
        ),
    ],
)
def test_wiki_probe_rejects_invalid_pages(
    responses: list[httpx.Response], message: str
) -> None:
    values = iter(responses)
    client = _mock_client(lambda request: next(values))
    with pytest.raises(DiscoveryError, match=message):
        client.probe_project_wiki(7)
    client.__exit__()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, text="bad"), "invalid JSON"),
        (httpx.Response(200, json=[]), "invalid object"),
    ],
)
def test_optional_object_rejects_invalid_response(
    response: httpx.Response, message: str
) -> None:
    client = _mock_client(lambda request: response)
    with pytest.raises(DiscoveryError, match=message):
        client.get_optional_object("metadata")
    client.__exit__()


def test_custom_ca_loading_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DiscoveryError, match="CA bundle"):
        GitLabClient(
            "https://gitlab.example.test",
            "secret",
            timeout=1,
            max_attempts=1,
            ca_bundle="/does/not/exist",
        )

    sentinel = ssl.create_default_context()
    observed: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            observed.update(kwargs)

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(ssl, "create_default_context", lambda cafile: sentinel)
    monkeypatch.setattr(httpx, "Client", FakeClient)
    with GitLabClient(
        "https://gitlab.example.test",
        "secret",
        timeout=3,
        max_attempts=1,
        ca_bundle="ca.pem",
    ):
        pass
    assert observed["verify"] is sentinel
    assert observed["headers"] == {"PRIVATE-TOKEN": "secret"}
    assert observed["follow_redirects"] is False
    assert observed["trust_env"] is False
    assert observed["closed"] is True


def test_discovery_rejects_invalid_and_conflicting_identities() -> None:
    responses = iter(
        [
            httpx.Response(200, json={"id": 1, "full_path": "root"}),
            httpx.Response(
                200,
                json=[{"id": 1, "full_path": "renamed"}],
            ),
        ]
    )
    client = _mock_client(lambda request: next(responses))
    with pytest.raises(DiscoveryError, match="conflicting group identity"):
        discover_inventory(client, "root", include_shared=False, include_archived=True)
    client.__exit__()

    for value in (
        {"id": True, "full_path": "root"},
        {"id": 0, "full_path": "root"},
        {"id": 1, "full_path": ""},
        {"id": 1},
    ):
        client = _mock_client(
            lambda request, value=value: httpx.Response(200, json=value)
        )
        with pytest.raises(DiscoveryError, match="invalid group identity"):
            discover_inventory(
                client, "root", include_shared=False, include_archived=True
            )
        client.__exit__()


def test_inventory_diff_all_categories_and_incomplete_rejection() -> None:
    catalog = _inventory(
        groups=((1, "root"), (2, "root/renamed"), (3, "root/reused")),
        projects=((10, "root/old"), (11, "root/absent")),
    )
    live = _inventory(
        groups=((1, "root"), (2, "root/new"), (4, "root/reused")),
        projects=((10, "root/old"), (12, "root/added")),
    )
    drift = compare_inventories(catalog, live)
    assert isinstance(drift, InventoryDiff)
    assert [(item.kind, item.id) for item in drift.added] == [
        ("group", 4),
        ("project", 12),
    ]
    assert [(item.kind, item.id) for item in drift.absent] == [
        ("group", 3),
        ("project", 11),
    ]
    assert [(item.id, item.catalog_path, item.live_path) for item in drift.renamed] == [
        (2, "root/renamed", "root/new")
    ]
    assert [(item.kind, item.id, item.live_path) for item in drift.path_reused] == [
        ("group", 4, "root/reused")
    ]
    with pytest.raises(DiscoveryError, match="incomplete"):
        compare_inventories(catalog, _inventory(complete=False))
    with pytest.raises(FrozenInstanceError):
        live.root_group.full_path = "mutated"  # type: ignore[misc]


def test_refresh_preserves_settings_selections_and_is_deterministic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    original = _config_text("https://persisted.example")
    path.write_text(original)
    path.chmod(0o640)
    inventory = _inventory(
        root_path="root-renamed",
        groups=((3, "root-renamed/new"), (1, "root-renamed")),
        projects=((20, "root-renamed/new"), (10, "root-renamed/app")),
    )
    refresh_catalog(path, inventory)
    first = path.read_bytes()
    loaded = YAML(typ="safe").load(first)
    assert loaded["gitlab"]["url"] == "https://persisted.example"
    assert loaded["hand_managed"] == {"value": "retained"}
    assert [item["id"] for item in loaded["inventory"]["groups"]] == [1, 3]
    assert loaded["inventory"]["groups"][0]["wiki"] is True
    assert loaded["inventory"]["groups"][1]["wiki"] is False
    assert loaded["inventory"]["projects"][0]["repository"] is True
    assert loaded["inventory"]["projects"][1] == {
        "id": 20,
        "full_path": "root-renamed/new",
        "repository": False,
        "wiki": False,
        "work_items": False,
    }
    assert path.stat().st_mode & 0o777 == 0o640
    refresh_catalog(path, inventory)
    assert path.read_bytes() == first


def test_refresh_root_replacement_incomplete_and_invalid_files(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    original = _config_text("https://example.test")
    path.write_text(original)
    changed = _inventory(root_id=2, groups=((2, "replacement"),))
    with pytest.raises(DiscoveryError, match="--replace-root"):
        refresh_catalog(path, changed)
    assert path.read_text() == original
    refresh_catalog(path, changed, replace_root=True)
    assert YAML(typ="safe").load(path.read_text())["inventory"]["root_group"]["id"] == 2

    with pytest.raises(DiscoveryError, match="incomplete"):
        refresh_catalog(path, _inventory(complete=False))
    missing = tmp_path / "missing.yaml"
    with pytest.raises(DiscoveryError, match="could not read"):
        refresh_catalog(missing, _inventory())
    path.write_text("[not, a, mapping]\n")
    with pytest.raises(DiscoveryError, match="must contain a mapping"):
        refresh_catalog(path, _inventory())
    path.write_text("inventory: []\n")
    with pytest.raises(DiscoveryError, match="inventory must be a mapping"):
        refresh_catalog(path, _inventory())
    path.write_text("inventory: [\n")
    with pytest.raises(DiscoveryError, match="could not read"):
        refresh_catalog(path, _inventory())


def test_refresh_empty_inventory_and_config_conversion(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("gitlab: {url: https://example.test}\n")
    refresh_catalog(path, _inventory())
    loaded = YAML(typ="safe").load(path.read_text())
    assert loaded["inventory"]["projects"] == []
    assert inventory_from_config({"inventory": {"root_group": None}}) is None
    converted = inventory_from_config(loaded)
    assert converted == _inventory()


def test_atomic_write_failure_removes_temporary_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    original = "inventory: {root_group: null, groups: [], projects: []}\n"
    path.write_text(original)

    def fail_replace(source: str, destination: Path) -> None:
        del destination
        os.unlink(source)
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(DiscoveryError, match="atomically"):
        refresh_catalog(path, _inventory())
    assert path.read_text() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_cli_replace_root_option_and_refresh_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "gitlab:\n  url: https://example.test\n"
        "storage:\n  destination: /tmp/reference\n"
    )
    observed: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            observed["client"] = (args, kwargs)

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            pass

    monkeypatch.setattr(cli, "GitLabClient", FakeClient)
    monkeypatch.setattr(cli, "discover_inventory", lambda *args, **kwargs: _inventory())

    def capture(
        path: str,
        inventory: Inventory,
        *,
        replace_root: bool,
        lfs_objects: dict[int, bool | None],
    ) -> None:
        del path, inventory, lfs_objects
        observed["replace_root"] = replace_root
        raise DiscoveryError("safe refresh failure")

    monkeypatch.setattr(cli, "refresh_catalog", capture)
    result = CliRunner().invoke(
        cli.main,
        ["discover", "--config", str(path), "--replace-root"],
        env={"GITLAB_TOKEN": "secret"},
    )
    assert result.exit_code == 2
    assert observed["replace_root"] is True
    assert "safe refresh failure" in result.output
    assert "secret" not in result.output
