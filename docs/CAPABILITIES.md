# Capability And Coverage Report

## Validation Status

On **2026-11-05**, the human confirmed that LFS fetching and the overall system
work against `https://gitext.alps.cz`, root group `1189` (`zero-iot`). This is
human-confirmed operational validation. The human subsequently supplied doctor
output identifying GitLab **19.5.3** (`server_metadata: metadata: 19.5.3`), Git
2.47.3 and Git LFS 3.6.1, with TLS verification and authentication passing and
discovery reporting 7 groups and 68 projects. A subsequent human-run read-only
query verified the current hierarchy query for a known parent/child pair in both
directions. The edition remains unreported.

The inspected local manifest (`temp/zero-iot/manifest.json`, run 5, finished
`2026-11-05T09:07:23+00:00`) records 142 resources: **92 ok, 27 empty, 21 disabled,
and 2 local conflicts**, with no error or unavailable states. The successful
resources comprise 38 repositories, 9 project wikis, and 45 work-item exports.
`zero-iot/0mt-certification` now has an `ok` repository checkout on `master`,
revision `37219f3c4a2657f9dba7a163f148d7dbc3840363`. The run remains partial
(exit 1) because local changes were preserved in `zero-iot/aws-lambdas` and
`zero-iot/0mt-manufacturing/0mt-eol-deployment`; these conflicts do not invalidate
the successful LFS validation. This manifest is local operational evidence, not
a checked-in fixture.

Automated API coverage below uses local HTTP fakes and production-shaped
payloads, supplemented by real local Git/LFS repositories and the live
observations above. No disposable GitLab instance was supplied; the human
explicitly approved the existing instance and known issue pair for TASK-004.
Group wikis remain separately untested on a licensed instance. Do not infer
support for every GitLab version or capability from this run; see
[`LIVE_TESTING.md`](LIVE_TESTING.md).

The subsequent doctor output reports 11 selected project wikis as unavailable
(IDs 813, 981, 1141, 1159, 1256, 1264, 1274, 1284, 1311, 1341 and 1373).
All 11 are recorded as `disabled`, with no error, by the inspected sync manifest.
Doctor currently probes every selected wiki endpoint and fails non-200 responses,
while sync recognizes server-disabled wikis from project details and treats them
as expected disabled resources. These diagnostics do not indicate LFS failure.

## Discovery And Git

Fixture coverage includes:

- root group `id` and `full_path`;
- descendant group pagination and stable-ID deduplication;
- project `id`, `path_with_namespace`, archived inclusion, shared exclusion, and
  complete pagination;
- project `default_branch`, `empty_repo`, `ssh_url_to_repo`,
  `http_url_to_repo`, `wiki_access_level`/`wiki_enabled`;
- project-wiki list status/page count and independently discovered Git remote
  HEAD;
- detached selected-branch checkouts, force-push, branch rename, upstream file
  deletion, no-op update, local conflict, timeout, and credential-free remote.

Only the selected default branch is materialized. Other refs and submodule
content are not synchronized. Project wiki remotes use GitLab's documented
sibling `.wiki.git` convention; the observed run includes 9 successful project
wiki checkouts.

Git LFS is optional per project and defaults off. Discovery offers `lfs: false`
only on positive `statistics.lfs_objects_size` evidence from the Projects API;
`lfs_enabled` alone is insufficient. Statistics require Reporter-level access.
Missing statistics are unknown, preserving existing intent without adding an
option; zero removes the option. Storage statistics are project-wide and may lag
changes or include historical files, rather than describing only the default
branch. The human confirmed working LFS downloads after discovery exposed
per-project options. This confirms the operational path on their instance;
version-specific statistics/authorization edge cases remain fixture-tested.

Real Git LFS 3.6.1 local-repository tests cover exact-commit downloads, initial
staged hydration, enabling at an unchanged revision, incremental updates,
override of recent/path download settings, local conflict preservation,
missing-object failure/retry, and stopping downloads while retaining caches.
Local HTTP batch/transfer fixtures verify real Git LFS askpass authentication,
token redaction, credential-free persisted remotes, and retry after denial.
Automatic smudging is always disabled. Explicit LFS hydration belongs to the
repository resource, not a separate resource. Other refs/history are not fetched
as LFS payloads, and downloaded binary content is not text-extracted or indexed.

## Issues, Tasks, And Conversations

REST fixture coverage explicitly requests project Issues API records twice with
`issue_type=issue` and `issue_type=task`, `scope=all`, and `state=all`, including
closed records and records belonging to archived projects visible in discovery.
The renderer records these item fields when exposed:

- global `id`, project-local `iid`, `issue_type`, `title`, `state`, `web_url`;
- `author`, `assignees`, `labels`, `milestone`, `confidential`;
- `created_at`, `updated_at`, and `closed_at`;
- original `description` and resolved project upload links.

The Discussions REST fixtures cover complete pagination, standalone notes,
threaded notes/replies, de-duplication by note ID, system notes, author, body,
created/updated timestamps, confidentiality/internal flags when exposed, and
resolution fields (`resolvable`, `resolved`, `resolved_at`). Issue Links REST
fixtures cover relationship type, target global/project/IID identity, title,
source URL, and a local link when the target is present.

Parent/child coverage uses the narrowly scoped GraphQL
`WorkItemWidgetHierarchy` parent and paginated children fields: `id`, `iid`,
`title`, and `webUrl`. GraphQL schema errors or absent widgets degrade to an
explicit limitation; hierarchy completeness is not claimed.

The inspected live-run cache contains 408 work-item snapshots: 75 contain an
extracted hierarchy parent and 18 contain extracted hierarchy children (75 child
edges). For example, `zero-iot/lambda_api` issue 15 has a child and issue 16 has a
parent. These are application-extracted results, not verbatim GraphQL response
envelopes.

The human subsequently ran the exact current GraphQL query and confirmed in
GitLab that `zero-iot/lambda_api` issue **16 is the child of 15**. Both responses
are retained under [`live-evidence/gitlab-19.5.3/`](live-evidence/gitlab-19.5.3/):

- Issue 15: `parent: null`, one child with IID `16` and global ID
  `gid://gitlab/WorkItem/4013`.
- Issue 16: parent IID `15`, global ID `gid://gitlab/WorkItem/3816`, no children.
- Both return `data.namespace.workItem.widgets`, with empty objects for
  unselected widget types, a hierarchy widget, and no GraphQL errors.
- Both child connections have `hasNextPage: false`; issue 15 has non-null
  `endCursor: "MQ"`, which does not require another page when `hasNextPage` is
  false. Multi-page behavior remains covered by synthetic pagination fixtures.

Thus `namespace(fullPath: <project path>) { workItem(iid: ...) }` works for this
pair on **GitLab 19.5.3**. No alternative query shape or product-code follow-up is
needed. `tests/test_discovery.py::test_gitlab_19_5_3_recorded_hierarchy_responses`
replays both recorded envelopes through the existing adapter, verifying fixture
compatibility. TASK-004's targeted validation is complete; reproduction steps
and the human-authorized scope are in `LIVE_TESTING.md`. This evidence does not
claim compatibility with every server version or work-item type.

Exact limitations:

- Modern work-item types other than accessible REST issues and tasks are not
  exported.
- Merge requests, epics, resource-event endpoints, and historical description or
  comment revisions are excluded.
- Discussions is treated as the conversation source; Notes is not concatenated,
  avoiding duplicate comments.
- Attachment links are preserved and project-relative upload links are resolved,
  but payloads are not downloaded, OCRed, or indexed.
- Permission-limited/confidential visibility is exactly the token's visible
  scope, not proof of complete server contents.

## Group Wikis

Group-wiki support is **fixture-only and not live-tested on a licensed
instance**. The exporter uses the documented Premium/Ultimate Group Wikis REST
API because no clone URL is exposed by that API and no licensed instance was
available to verify one.

Fixtures cover independently selected root, descendant, and projectless groups;
disabled selections making no request; complete list pagination; a second
unrendered source request per slug; Markdown, RDoc, AsciiDoc, and Org source;
nested safe slugs; deterministic sidecars/provenance; complete-tree publication;
empty lists; retained prior content; and isolated failures.

HTTP 401, 403, and 404 evidence remains deliberately ambiguous among
authorization, visibility, missing/disabled wiki, and unsupported/unavailable
capability. One group response never establishes instance-wide support. Source
attachment references remain unchanged and attachment payloads are not
downloaded.

## Local Fixture Coverage

The checked-in sample at `examples/sample-corpus/` is synthetic and generated by
`examples/generate_sample_corpus.py`. Automated tests compare regeneration
byte-for-byte. It demonstrates selected repository source, project wiki source,
REST group wiki source and provenance, issue/task relationships, human threads,
system activity, project/group metadata, manifest freshness, search guidance,
and stale object/component metadata. It intentionally excludes `.git`, SQLite,
raw internal snapshots, credentials, and secrets.
