---
id: TASK-001.07
title: Export selected group and subgroup wikis
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 07:47'
updated_date: '2026-09-21 05:52'
labels: []
dependencies:
  - TASK-001.04
references:
  - specs/gitlab_reference_sync_spec.md
modified_files:
  - gitlab_groupsync/gitlab_api.py
  - gitlab_groupsync/group_wikis.py
  - gitlab_groupsync/orchestrator.py
  - gitlab_groupsync/state.py
  - tests/test_discovery.py
  - tests/test_group_wikis.py
  - tests/test_orchestrator.py
  - tests/test_state.py
parent_task_id: TASK-001
priority: medium
type: feature
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The generated inventory allows each root or descendant group wiki to be selected independently, including groups without projects. Implement this optional licensed capability without turning one unavailable wiki into an instance-wide assumption or a failure for unselected groups.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Every discovered root or descendant group has an independent wiki selection and unselected groups make no wiki requests
- [x] #2 Selected group wikis are exported into the group content tree through a verified clone mechanism or the documented Group Wikis API while preserving searchable source content
- [x] #3 Observed empty, unavailable, forbidden, missing, unsupported, and transient-error evidence is recorded without inferring an instance-wide result from one response
- [x] #4 An unavailable selected group wiki is a partial failure that does not block other groups or project resources
- [x] #5 Tests cover groups without projects, disabled selections, fixture-supported exports, per-group unavailable responses, and honest capability limitations
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extend the GitLab adapter with a group-wiki listing result that preserves first-response HTTP 401/403/404 evidence, paginates every successful list page, and retrieves every listed slug through the documented single-page endpoint without requesting rendered HTML.
2. Add a group-wiki exporter that validates documented source formats and safe nested slugs, writes source plus page metadata sidecars into a complete staging tree, stores deterministic complete raw snapshots under .sync/raw, rejects traversal/symlink/unmanaged collisions, and atomically swaps only complete trees with durable recovery records and unchanged-byte no-op behavior.
3. Record per-group resource outcomes and metadata for configured-disabled, confirmed-empty, selected-success, HTTP-unavailable/ambiguous, and transient/API failures; preserve prior successful active content and success metadata as retained/stale-visible on failures, and state fixture-only/API/attachment limitations explicitly.
4. Integrate an independent root/descendant group pass after complete discovery and before/alongside project processing so groups without projects run, disabled groups issue zero wiki requests, and one group failure contributes exit 1 without blocking other groups or project exporters.
5. Add focused API/exporter/orchestrator tests for pagination and complete page retrieval, all documented formats and nested slugs, root/nested/no-project groups, all-disabled zero requests, empty/error evidence, retained content after list/later-page failures, component isolation, deterministic publication, raw location, path collisions, interrupted-swap recovery, and manifest/state/group metadata.
6. Run the full 100% coverage suite and all release checks, update task evidence and exact capability limitations, then move only TASK-001.07 to Review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: dependencies and siblings through TASK-001.06 remain in Review under explicit human authorization. Current GitLab documentation reviewed 2026-09-20 identifies Group Wikis as Premium/Ultimate and documents GET /groups/:id/wikis with optional with_content plus GET /groups/:id/wikis/:slug with render_html disabled by default. Documented source formats are markdown, rdoc, asciidoc, and org. The API does not expose a group-wiki clone URL; user documentation only provides UI clone instructions and group export bundles, so implementation will use REST rather than infer a remote. Attachment upload responses establish uploads/... references, but no read/download API is documented for exporter use; source references will remain unchanged and payload download is explicitly out of scope. Existing complete discovery, generic group resources, atomic JSON, and recovery records are reusable; broad object rename/disappearance quarantine remains TASK-001.08.

Implementation checkpoint: added documented Group Wikis REST listing with exact 401/403/404 evidence, complete offset pagination, and an explicit complete-source GET for every slug without render_html. Added group_wikis.py with safe group paths, documented format extensions (Markdown .md, RDoc .rdoc, AsciiDoc .adoc, Org .org), nested-slug validation, source-preserving files, page sidecars/provenance, deterministic complete raw snapshots, staged whole-tree swaps, durable recovery, unchanged-byte no-op behavior, and rejection of traversal, symlink, identity, unmanaged, and filesystem-collision hazards. Existing complete content/revision/success is retained and marked stale-visible after API/transient failures; confirmed empty is a successful complete raw snapshot with no active wiki directory.
Orchestration checkpoint: every configured live root/descendant group is handled independently before project selections. wiki:false records disabled coverage and issues no Group Wikis API request; selected group failures contribute exit 1 while sibling groups and project exporters continue. group.json and manifest per-resource details expose status, attempts/success, retained content, exact observed evidence, API mechanism, attachment limitation, and fixture-only coverage. Broad group rename/disappearance/quarantine remains TASK-001.08.

Final verification: `uv run pytest --cov=gitlab_groupsync --cov-report=term-missing tests/` passed 165 tests at 100.00% coverage. Tests prove root/nested/projectless groups, disabled zero requests, successful paginated complete-source export, all documented formats/nested slugs, confirmed empty without an active wiki directory, exact 401/403/404 ambiguity, transient retention after complete prior content, sibling group/project continuation, deterministic no-op writes, raw snapshots outside content, traversal/symlink/unmanaged/collision rejection, interrupted publication recovery, and state/group/manifest evidence. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy gitlab_groupsync`, `git diff --check`, `uv lock --check`, and `uv build` all passed.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-09-20 09:12
---
Dependencies and implemented siblings remain in Review; the human explicitly authorized sequential continuation for TASK-001.07.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented independent root and descendant group-wiki synchronization through the documented Premium/Ultimate Group Wikis REST API. Successful selections paginate every list page, retrieve every page again for complete unrendered source, preserve Markdown/RDoc/AsciiDoc/Org content and nested slugs with provenance sidecars, write complete deterministic raw snapshots under `.sync/raw`, and stage/recover whole-tree publication without exposing partial searchable exports. Disabled selections make zero wiki requests; confirmed empty is successful without an active wiki directory; exact 401/403/404 and transient evidence remains per group; failures retain prior complete content and do not block sibling groups or project resources. State, `group.json`, and manifest details expose attempt/success, status, retained content, evidence, and limitations.
Verification: 165 tests pass at 100.00% package coverage. Ruff check/format, mypy, `git diff --check`, `uv lock --check`, and `uv build` pass. Exact limitations: no API-provided or licensed-instance-verified group-wiki clone URL was established, so REST is used; group-wiki capability is fixture-tested only with no live licensed GitLab version claimed; attachment links/source references are preserved but attachment payloads are not downloaded; HTTP 401/403/404 remains intentionally ambiguous among authorization, visibility, disabled/missing wiki, and unsupported/unavailable capability; broad group rename/disappearance/quarantine remains TASK-001.08. No new blocker, follow-up task, or ADR was required; ADR 0001 remains applicable.
<!-- SECTION:FINAL_SUMMARY:END -->
