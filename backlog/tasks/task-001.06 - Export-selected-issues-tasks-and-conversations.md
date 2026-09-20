---
id: TASK-001.06
title: 'Export selected issues, tasks, and conversations'
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 07:46'
updated_date: '2026-09-20 09:10'
labels: []
dependencies:
  - TASK-001.04
references:
  - specs/gitlab_reference_sync_spec.md
modified_files:
  - gitlab_groupsync/cli.py
  - gitlab_groupsync/gitlab_api.py
  - gitlab_groupsync/orchestrator.py
  - gitlab_groupsync/state.py
  - gitlab_groupsync/work_items.py
  - tests/test_discovery.py
  - tests/test_gitlab_groupsync.py
  - tests/test_orchestrator.py
  - tests/test_state.py
  - tests/test_work_items.py
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create a searchable current-state representation of selected projects issues and tasks without losing conversations or publishing partial responses. The exporter must remain honest about GitLab CE capability coverage and reconcile sources that are not reliable change feeds.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Selected projects export accessible open and closed issue and task types, including archived-project items, with stable global and project-local identity
- [x] #2 Every discussion page is retrieved and standalone comments, threaded replies, system notes, authors, IDs, timestamps, resolution data, and supported relationships are preserved without duplicate notes
- [x] #3 One deterministic UTF-8 Markdown file per item preserves source descriptions and comments, canonical provenance, resolved upload links, human threads, separate system activity, and known limitations
- [x] #4 Incremental runs use overlap windows and durable retries while full reconciliation detects edits, deleted comments, closed-item changes, and disappeared items
- [x] #5 A partial conversation response never replaces a previous complete file, checkpoints do not advance unsafely, and volatile check timestamps do not rewrite unchanged Markdown
- [x] #6 Raw structured snapshots remain outside the active corpus and publication is recoverable after interruption
- [x] #7 Tests cover issue and child task relationships, standalone and threaded conversation, edits and deletions without parent timestamp changes, pagination failures, overlap deduplication, retries, and full-only disappearance quarantine
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extend the GitLab adapter with explicit all-state project issue and task listings, complete discussion and issue-link pagination, and a narrowly scoped paginated GraphQL hierarchy query that distinguishes unsupported schema coverage from operational failures.
2. Add deterministic work-item parsing/rendering with stable global/project-IID identity, complete exposed metadata, upload URL resolution, REST links plus available hierarchy/local references, chronologically grouped human threads, separately sorted system activity, provenance links, and explicit coverage limitations.
3. Migrate SQLite state for durable work-item identities/publication metadata, checkpoint/full-success state, retry inspection, and recoverable publication records; stage complete structured raw snapshots outside content and publish raw then Markdown with restart recovery and unchanged-byte avoidance.
4. Implement per-project incremental/full reconciliation using run-start checkpoints, overlap-based updated_after filters for both issue and task types, durable retries, complete conversation refresh, scheduled/full-success tracking, partial-full due retention, and quarantine only after a complete full listing.
5. Integrate selected work items into orchestration and --full flow independently of repository/wiki details and failures; publish project/manifest resource status, continue after item/project failures, and preserve exit 1 versus fatal setup/discovery exit 2 semantics.
6. Add focused API, renderer, state, exporter, orchestration, and CLI tests for child tasks, archived/closed metadata, discussions/order/source links/uploads/system separation, deterministic no-op publication, overlap/retry/checkpoints, later-page preservation, full edit/delete repair, partial-full due state, recovery, and full-only quarantine.
7. Run the complete 100% coverage suite, Ruff check/format, mypy, diff check, lock check, and build; record verified limitations and finalize only TASK-001.06 to Review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: dependencies and TASK-001.05 are in Review under explicit human authorization. Existing schema v2 has generic checkpoints/retries/recovery records but lacks work-item identity/publication APIs; sync currently ignores --full and only enters selected projects when repository/wiki is enabled. Current GitLab docs (reviewed 2026-09-20) confirm project Issues REST supports all-state issue_type=issue/task listings and updated_after; Discussions includes standalone notes, threaded DiscussionNotes, and system notes with pagination, so Notes need not also be fetched. REST issue links expose relates_to/blocks/is_blocked_by. Parent-child hierarchy is exposed by the experimental GraphQL WorkItemWidgetHierarchy and must be treated as optional capability evidence, not proof of complete modern work-item coverage.

Implementation checkpoint: added explicit issue/task REST inventory, full Discussions and issue-link pagination, and optional paginated GraphQL hierarchy enrichment with non-claiming limitations on GraphQL errors. Added deterministic Markdown rendering and complete structured raw snapshots, schema-v3 work-item publication state, overlap checkpoints/retries/full-success tracking, full-only quarantine, and restartable raw-first publication records. Integrated work-items-only project selection and --full through CLI/orchestration independently from repository/wiki details and failures. The current full suite passes 132 tests at 100% coverage before the final edge-case and release-check pass.

Final verification: 133 tests pass at 100.00% package coverage. Fake GitLab transport tests prove explicit issue/task all-state updated_after requests, offset pagination, duplicate identity suppression, Discussions/links endpoints, GraphQL child pagination, unsupported/error degradation, malformed responses, retry/redaction, and pagination failures. Exporter tests prove closed confidential child tasks, full metadata, standalone/threaded/system note separation and stable ordering, source anchors, upload resolution, local/remote relationships, no-op byte preservation, overlap checkpoints, durable retries, later-page preservation, full edit/delete repair without parent timestamp movement, partial-full due retention, raw-first recovery, malformed-list exit behavior, and full-only quarantine. Orchestrator/CLI tests prove work-items-only selection, --full propagation, repository independence, path failure exit 1, project metadata, and manifest publication. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy gitlab_groupsync`, `git diff --check`, `uv lock --check`, and `uv build` all pass.
Capability limitations: coverage deliberately includes only accessible REST issue_type=issue and issue_type=task records, not every modern work-item type. Discussions is the authoritative conversation source because current GitLab documentation states it includes individual notes and threaded DiscussionNotes; Notes is therefore not also fetched or merged. Parent/child hierarchy uses only the experimental GraphQL WorkItemWidgetHierarchy and records a limitation instead of claiming completeness when GraphQL returns errors or no widget. Resource-event endpoints, historical revisions, and attachment downloads remain excluded. Tests use local/fake current-API fixtures; no live GitLab CE version was available or claimed.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-09-20 08:53
---
The human explicitly authorized sequential continuation while dependencies and sibling TASK-001.05 remain in Review; this dependency state is intentional.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented selected project issue/task export and reconciliation. GitLab REST now explicitly enumerates all open/closed issue and task records with updated_after and complete pagination, retrieves complete Discussions and issue links, and uses narrowly scoped paginated GraphQL only for optional parent/child hierarchy. Deterministic UTF-8 Markdown includes stable identities, requested metadata, original source text, resolved upload URLs, relationship/source/local links, ordered human threads, separate system activity, and honest limitations; complete structured snapshots live under `.sync/raw`. SQLite schema v3 persists work-item/publication identity, per-project overlap checkpoints, durable retries, separate full-success state, and recoverable raw-first publication records. Full passes repair edited/deleted notes and alone can quarantine missing Markdown; partial fetches preserve prior raw/Markdown and remain due. CLI/orchestration forwards --full and runs work items only for work_items:true independently of repository/wiki outcomes, with selected failures returning partial exit 1 and project/manifest status publication.
Verification: 133 tests pass at 100.00% coverage; Ruff check/format, mypy, diff check, uv lock check, and uv build pass. Known limitations are accessible REST issue/task scope only, experimental/optional GraphQL hierarchy, no separate resource-event history, no revision reconstruction, no attachment download, and fixture-only API capability validation without a claimed live GitLab version. No blocker, follow-up task, or ADR was required; ADR 0001 remains applicable.
<!-- SECTION:FINAL_SUMMARY:END -->
