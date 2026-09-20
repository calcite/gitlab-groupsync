---
id: TASK-001.05
title: Synchronize selected repositories and project wikis
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 07:46'
updated_date: '2026-09-20 08:52'
labels: []
dependencies:
  - TASK-001.04
references:
  - specs/gitlab_reference_sync_spec.md
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Materialize selected project default branches and optional project wikis as independently managed Git resources. Updates must remain one-way and safe in the presence of force-pushes, branch changes, local modifications, empty resources, timeouts, and interrupted staging.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A selected project repository is cloned through staging and published only after a successful detached default-branch checkout
- [x] #2 Existing clean checkouts fetch the current default branch with force-push-safe refspecs, remove upstream-deleted files, and skip unchanged revisions
- [x] #3 Project repositories and wikis have independent states, revisions, timestamps, and failure handling
- [x] #4 Empty, disabled, inaccessible, and transiently failed wikis are distinguished to the extent supported by observed API and Git evidence
- [x] #5 Local tracked or untracked changes are never discarded and produce a local-conflict result for only that resource
- [x] #6 Git operations disable LFS smudging and submodule recursion, are noninteractive, enforce timeouts, and never expose tokens in URLs, arguments, logs, or errors
- [x] #7 Tests use temporary real Git repositories and cover initial import, incremental and no-op updates, deleted files, branch rename, force-push, wiki branch differences, component isolation, local conflicts, and timeouts
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extend the GitLab API adapter with validated project sync details and an observed-status project-wiki probe, preserving retry/redaction behavior and deriving only credential-free wiki remotes from verified project clone URLs.
2. Add a testable Git subprocess adapter that always uses argv, sanitized environments, LFS/submodule suppression, SSH BatchMode, ephemeral HTTPS askpass credentials, process-group timeout termination, and redacted failures.
3. Add contained managed path helpers and a Git resource synchronizer for staged first publication, unmanaged/symlink collision rejection, clean-worktree checks, force-safe explicit fetches, detached checkouts, unchanged-revision skips, empty resources, and credential-free persisted remotes.
4. Add a minimal extensible sync orchestrator that locks, performs complete live discovery, validates live root identity, records drift without changing YAML, starts/finishes runs, upserts live objects, independently synchronizes selected project repositories/wikis, persists resource outcomes, and atomically publishes project metadata plus manifest while mapping exits 0/1/2/3. Work-item and group-wiki handlers remain future slices.
5. Wire the CLI to the orchestrator and add real temporary bare/work repository tests plus fake API/subprocess cases covering imports, incremental/no-op/deletion/rename/force-push, empty and inaccessible wikis, independent failures, local conflicts, staging/fetch/checkout errors, timeout child termination, credential hygiene, drift, metadata/state, and locking.
6. Run the full 100% coverage suite, Ruff check/format, mypy, diff check, lock check, and build; then finalize only TASK-001.05 for human review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: dependencies TASK-001.01-.04 are in Review under explicit human authorization. The current 80-test suite passes at 100% coverage. Existing state supports locking, identity, runs, drift, objects/resources, and atomic JSON but sync is a placeholder. Current GitLab docs confirm project details expose default_branch, empty_repo, ssh_url_to_repo, http_url_to_repo, and wiki access fields; GET /projects/:id/wikis is the documented list probe. A successful empty list is authoritative empty evidence, disabled project metadata is distinct, and HTTP 401/403/404 or transport failures must be retained as observed evidence rather than guessed causes. Project wikis are separate Git repositories and their remote HEAD/default branch must be discovered independently.

Implementation checkpoint: added `gitlab_groupsync/git_sync.py` with argv-only subprocess execution, LFS/submodule suppression, SSH BatchMode with host-key verification retained, ephemeral HTTPS askpass authentication, optional custom CA, generic/redacted failures, and process-group TERM/KILL timeout handling. Managed project/resource markers and path checks reject traversal, symlink roots/ancestors/Git internals, identity mismatches, and unmanaged collisions. First imports use `.sync/staging` plus atomic rename; existing checkouts require a clean porcelain status, fetch an explicit `+refs/heads/<branch>:refs/remotes/origin/gl-groupsync` refspec, and detach at the fetched revision.
Orchestration checkpoint: added complete live discovery, live-root identity binding, drift persistence/actionable reporting without YAML writes, durable run lifecycle including initialized-destination discovery failures, discovered-object upserts, and independent selected repository/wiki processing. Project details come from the API. Wiki list status preserves empty/disabled/401/403/404/transient evidence, and nonempty wikis resolve their own remote HEAD. Resource state schema v2 adds independent branch persistence with an in-place v1 migration; project metadata and manifest use atomic writers. Resource failures preserve prior success/revision/branch and do not block sibling resources. Work items and group wikis remain untouched for TASK-001.06/.07.
Verification checkpoint: 106 tests pass with 100.00% package coverage. Real temporary bare/work Git tests cover staged import, no-op, incremental/deleted files, default-branch rename, force-push, empty remotes, differing wiki branch, tracked/untracked conflicts, checkout/staging/publication race failures, timeout child/process-group termination, secret redaction, credential-free persisted remotes, SSH noninteractive settings, custom CA, and path collisions. Fake API/orchestrator tests cover drift exit 0 behavior, repository/wiki isolation and exit 1, empty/disabled/inaccessible/transient wiki evidence, metadata/manifest/state, retained success, fatal discovery exit 2 recording, and lock contention/exit 3. `ruff check`, `ruff format`, mypy, `git diff --check`, `uv lock --check`, and `uv build` pass.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-09-20 08:36
---
Dependencies TASK-001.01 through TASK-001.04 remain in Review; the human explicitly authorized sequential continuation for this task.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented selected project repository and project-wiki synchronization end to end. The new Git adapter uses argument lists, force-safe branch refspecs, detached checkouts, staged atomic first publication, clean-worktree conflict detection, credential-free remotes, ephemeral HTTPS askpass, SSH BatchMode, custom CA support, LFS/submodule suppression, redacted errors, and process-group timeouts. The orchestrator now locks, performs complete live discovery, binds live root identity, records actionable catalog drift without YAML mutation, persists runs/objects/independent resources, continues sibling resources after failure, and atomically publishes project metadata and the manifest with exit codes 0/1/2/3. Project wiki API evidence distinguishes disabled, observed empty, HTTP-inaccessible/ambiguous, and transient failures; wiki remote HEAD is independent of the project branch. State schema v2 adds per-resource branch tracking and migrates v1 in place.
Verification: `uv run pytest --cov=gitlab_groupsync --cov-report=term-missing tests/` passes 106 tests at 100.00% coverage. Real temporary bare/work repositories prove staged imports, no-op and incremental updates, upstream deletion, branch rename, force-push, empty repositories/remotes, differing wiki branches, local tracked/untracked conflict safety, staging/checkout failure behavior, and credential-free persisted remotes. Fake API/orchestrator and subprocess tests prove component isolation, wiki evidence states, drift warning exit 0, partial failure exit 1, fatal setup/discovery exit 2, lock exit 3, durable metadata/manifest/run updates, HTTPS secret redaction, SSH settings, and timeout child termination. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy gitlab_groupsync`, `git diff --check`, `uv lock --check`, and `uv build` pass.
Known scope boundaries: work-item export remains TASK-001.06, group-wiki export remains TASK-001.07, and broad relocation/quarantine/recovery reconciliation remains TASK-001.08. No blocker or new follow-up was found. No ADR was needed; ADR 0001 remains the applicable catalog architecture.
<!-- SECTION:FINAL_SUMMARY:END -->
