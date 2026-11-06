# Optional Live Integration Testing

No live GitLab test is enabled by default. The normal suite uses fixtures and
temporary local Git repositories and performs no request to a user server.

## Human Operational Validation (2026-11-05)

The human ran discovery and synchronization using `temp/test_config.yaml` against
their GitLab instance and confirmed both LFS fetching and overall operation.
The manifest records successful repository, project-wiki and work-item resources;
see `docs/CAPABILITIES.md` for the observed counts and remaining local conflicts.
This was an operational run, not execution of the optional pytest contract below.

The human supplied doctor output reporting GitLab **19.5.3**, Git 2.47.3 and Git
LFS 3.6.1. Authentication and TLS checks passed; discovery reported 7 groups and
68 projects. The edition is unreported. For TASK-004 the human subsequently ran
the targeted read-only hierarchy query, saved both responses, and confirmed in
GitLab that issue 16 is the child of issue 15. The human explicitly approved using
the existing instance and the known `zero-iot/lambda_api` issue 15 -> child 16 pair,
superseding the original disposable-instance/single-item-with-parent-and-child
setup for TASK-004. No server changes or fixture creation are part of this check.

To retrieve server metadata with the existing configuration, the human can run:

```console
uv run gl-groupsync doctor --config temp/test_config.yaml
```

Record the exact `server_metadata` result when available; do not infer a version
from successful synchronization.

### Approved Human-Run Hierarchy Check

From the workspace root, with `GITLAB_TOKEN` exported, run the following. It uses
the existing configuration, sends the same read-only GraphQL query as the current
adapter for both issue IIDs, and saves each response body verbatim under `temp/`.
It does not invoke sync or alter the corpus. The human executed this procedure
and supplied the responses and relationship confirmation on 2026-11-05.

```bash
uv run python - <<'PY'
import ssl
from pathlib import Path

import httpx

from gitlab_groupsync.config import load_config, load_token

config = load_config("temp/test_config.yaml", [])
gitlab = config["gitlab"]
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
verify = (
    ssl.create_default_context(cafile=gitlab["ca_bundle"])
    if gitlab["ca_bundle"] else True
)
with httpx.Client(
    headers={"PRIVATE-TOKEN": load_token(config)},
    verify=verify,
    timeout=config["sync"]["api_timeout_seconds"],
    follow_redirects=False,
    trust_env=False,
) as client:
    for iid in ("15", "16"):
        response = client.post(
            gitlab["url"].rstrip("/") + "/api/graphql",
            json={
                "query": query,
                "variables": {
                    "path": "zero-iot/lambda_api", "iid": iid, "after": None,
                },
            },
        )
        output = Path(f"temp/hierarchy-{iid}-response.json")
        output.write_bytes(response.content)
        print(f"Saved {output} (HTTP {response.status_code})")
        print(response.text)
PY
```

Confirm in GitLab that issue 15 is the parent of issue 16. Expected evidence is
child IID `16` in issue 15's hierarchy widget and parent IID `15` in issue 16's
widget, with no GraphQL errors. If `hasNextPage` is true, additional child pages
are required before claiming complete child coverage. Retain errors or null
responses as evidence too; do not replace the query shape before recording its
actual result. Once the files exist, the agent can inspect them locally, compare
the response envelope with fixtures, and update TASK-004. Do not include tokens
or request authentication headers in shared evidence.

### Recorded Result

The original saved response bodies are `temp/hierarchy-15-response.json` and
`temp/hierarchy-16-response.json`. Durable JSON response copies (with a terminal
newline added) are in `docs/live-evidence/gitlab-19.5.3/`. No field values were
changed. No authentication headers or token values are included.

The current namespace/project-path query returned the expected hierarchy in both
directions, with no GraphQL errors and `hasNextPage: false` in both responses.
The human independently confirmed the relationship in GitLab. Offline replay
through `GitLabClient.work_item_hierarchy` matches the expected fixture shape,
including empty non-hierarchy widgets and string IIDs. No query replacement or
product-code change is required. TASK-004's targeted verification is complete.
These were read-only GraphQL queries on existing work items; no server content
was created, edited or deleted.

## Contract

Future live tests must use the pytest marker `live` and skip unless every
required read-only variable is explicitly set:

- `GL_GROUPSYNC_LIVE_URL`: disposable GitLab base URL;
- `GL_GROUPSYNC_LIVE_ROOT_GROUP`: dedicated root full path or numeric ID;
- `GL_GROUPSYNC_LIVE_TOKEN`: short-lived read-only token;
- `GL_GROUPSYNC_LIVE_EXPECTED_VERSION`: exact expected server version, recorded
  before capability claims are updated.

Run only the explicit marker:

```console
GL_GROUPSYNC_LIVE_URL=https://gitlab-disposable.example \
GL_GROUPSYNC_LIVE_ROOT_GROUP=groupsync-fixture \
GL_GROUPSYNC_LIVE_TOKEN='...' \
GL_GROUPSYNC_LIVE_EXPECTED_VERSION='X.Y.Z' \
uv run pytest -m live
```

The repository currently contains no enabled live test because no disposable
instance/version was provided. Any future live test must be read-only by default:
GET/query discovery, capability probes, and cloning dedicated fixtures are
allowed; creating, editing, closing, or deleting groups, projects, issues,
comments, wiki pages, or repository refs is forbidden.

Mutation setup is a separate activity, not implied by `-m live`. It requires a
disposable dedicated instance plus separate explicit authorization documented in
the active Backlog task. A user or production server must never be populated with
fixture issues/comments. Do not introduce a generic "allow mutation" variable
that could accidentally authorize an arbitrary configured server.

After an authorized run, record the exact observed GitLab version, edition and
license-relevant capabilities, fixture setup, and pass/failure evidence in
`docs/CAPABILITIES.md`. Never replace a missing version with "latest".
