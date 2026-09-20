---
id: TASK-001.03
title: Implement GitLab discovery and selectable inventory refresh
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 07:46'
updated_date: '2026-09-20 08:21'
labels: []
dependencies:
  - TASK-001.02
references:
  - specs/gitlab_reference_sync_spec.md
  - docs/adr/0001-generated-stable-id-selection-catalog.md
modified_files:
  - gitlab_groupsync/gitlab_api.py
  - gitlab_groupsync/discovery.py
  - gitlab_groupsync/cli.py
  - gitlab_groupsync/config.py
  - pyproject.toml
  - uv.lock
  - tests/test_discovery.py
  - tests/test_gitlab_groupsync.py
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Users need an authoritative pre-discovery phase before choosing what to synchronize. Implement the read-only GitLab API traversal and same-file generated catalog so selections remain stable through path changes and incomplete API traversal cannot corrupt scope.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Discovery resolves the root group and retrieves the root, every visible descendant group, and every owned project with complete pagination, archived-project inclusion, shared-project exclusion, and ID deduplication
- [x] #2 A successful discover command atomically refreshes the same YAML file and produces deterministic project and group ordering
- [x] #3 Selections are preserved by global ID, renamed paths are updated, new projects and group wikis default to disabled, and objects absent from a complete inventory are removed
- [x] #4 A failed or partial discovery leaves the existing YAML unchanged and does not report an authoritative empty inventory
- [x] #5 Changing the stable root-group identity requires explicit replacement rather than silently replacing the catalog
- [x] #6 Inventory comparison identifies added, absent, renamed, and path-reused objects for sync warnings and manifest reporting
- [x] #7 Tests cover nested and empty groups, pagination, archived and shared projects, deduplication, refresh preservation, failed pages, and root replacement protection
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add immutable discovery/domain models and a focused HTTPX GitLab client using PRIVATE-TOKEN, verified TLS or a configured CA, strict API URL construction, same-origin pagination, bounded transient retries, safe redacted errors, and injectable transport/sleep behavior.
2. Resolve the root group, enumerate all descendant groups and root-scope projects with complete pagination and configured shared/archive filters, then deduplicate by global ID while rejecting conflicting identities and marking only completed traversals authoritative.
3. Implement read-only inventory drift classification and deterministic catalog merging by object kind/global ID, preserving selection flags and mutable hand settings while protecting root replacement.
4. Implement same-directory atomic YAML refresh with flush/fsync/replace, reading the persisted file rather than resolved override layers so secrets and transient overrides cannot be serialized. Wire only discover to the real workflow with an explicit --replace-root option and useful counts/errors.
5. Add comprehensive model/client/discovery/refresh/CLI tests, including a local stdlib HTTP server for auth, pagination, filters, retries, failures, and redirect isolation; update dependencies with uv and run coverage, Ruff, mypy, diff check, and build.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: TASK-001.01/.02 are intentionally in Review under explicit human authorization. The current code has validated Onacol YAML loading and separate token resolution; discover alone is a placeholder. Current GitLab docs specify GET /groups/:id, /groups/:id/descendant_groups, and /groups/:id/projects; project listing defaults with_shared=true, accepts include_subgroups, and includes archived/nonarchived when archived is omitted. REST pages allow per_page=100 and expose X-Next-Page/Link. HTTPX verifies TLS and does not follow redirects by default; discovery will retain that strict redirect behavior to prevent cross-host token forwarding.

Implementation complete. Added immutable inventory/drift values, a PRIVATE-TOKEN HTTPX client with verified TLS/custom CA support, no redirects, same-origin URL enforcement, complete pagination, bounded transient retries and redacted errors. Discovery resolves the root and descendant_groups, lists root-scope projects with include_subgroups and configured shared/archive filters, deduplicates IDs, and rejects conflicting identities. Catalog refresh reads only persisted YAML, merges selections by kind/global ID, sorts by ID, protects root replacement, and performs same-directory flush/fsync/replace while preserving file mode and hand-maintained settings. Read-only comparison classifies added, absent, renamed, and path-reused objects. The discover CLI now performs the workflow and exposes --replace-root; later command placeholders remain untouched. Shared projects outside the root are accepted by semantic validation only when include_shared_projects is enabled.

Verification checkpoint: 61 tests pass at 100% coverage. The suite uses a real local stdlib HTTP server for encoded root resolution, nested/empty descendants, pagination, archived/nonarchived inclusion, shared filtering, ID deduplication, authentication, request parameters, failed pages, and CLI persistence; focused tests cover TLS/custom CA, redirects/cross-host safety, retries, redaction, malformed responses, deterministic atomic refresh, mode/settings/selection preservation, additions/removals/renames/reappearance defaults, root replacement, atomic failure, immutability/completeness, and all drift categories. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy gitlab_groupsync`, `git diff --check`, `uv lock --check`, and `uv build` pass.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-09-20 08:12
---
The human explicitly authorized sequential continuation while TASK-001.01 and TASK-001.02 remain in Review; this dependency state is intentional.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented complete GitLab group/project discovery and same-file selectable inventory refresh. Added a testable HTTPX client with PRIVATE-TOKEN authentication, verified TLS/custom CA, strict same-origin/no-redirect handling, bounded retries, complete pagination and redacted failures; immutable complete inventories and drift categories; deterministic stable-ID merge with disabled defaults, selection preservation, explicit root replacement, and same-directory flush/fsync/atomic replace; and real discover CLI behavior while leaving later workflows untouched.

Objective evidence: 61 tests pass at 100% coverage. Local stdlib HTTP integration verifies nested/empty groups, encoded roots, all-page project/group traversal, archived inclusion, configured shared behavior, deduplication, auth and failed-page byte preservation. Focused tests verify conflicts, TLS/CA/retry/redaction/cross-host semantics, deterministic refresh, selection/rename/addition/removal behavior, transient override and token non-serialization, atomic failures, root replacement, completeness/immutability, and added/absent/renamed/path-reused drift. Ruff check and format check, mypy, `git diff --check`, `uv lock --check`, and `uv build` pass.

Known limitations: none within TASK-001.03. State, sync, manifest publication, and use of the drift model remain intentionally assigned to existing downstream tasks. Architectural reference: `docs/adr/0001-generated-stable-id-selection-catalog.md`; no new ADR or follow-up task was needed.
<!-- SECTION:FINAL_SUMMARY:END -->
