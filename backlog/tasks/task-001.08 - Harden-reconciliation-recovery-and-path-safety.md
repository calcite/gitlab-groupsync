---
id: TASK-001.08
title: 'Harden reconciliation, recovery, and path safety'
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 07:47'
updated_date: '2026-09-20 10:03'
labels: []
dependencies:
  - TASK-001.05
  - TASK-001.06
  - TASK-001.07
references:
  - specs/gitlab_reference_sync_spec.md
modified_files:
  - gitlab_groupsync/config.py
  - gitlab_groupsync/git_sync.py
  - gitlab_groupsync/gitlab_api.py
  - gitlab_groupsync/group_wikis.py
  - gitlab_groupsync/orchestrator.py
  - gitlab_groupsync/path_safety.py
  - gitlab_groupsync/reconcile.py
  - gitlab_groupsync/state.py
  - gitlab_groupsync/work_items.py
  - tests/test_discovery.py
  - tests/test_git_sync.py
  - tests/test_group_wikis.py
  - tests/test_orchestrator.py
  - tests/test_reconcile.py
  - tests/test_state.py
  - tests/test_work_items.py
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Bring all exporters under the same safe lifecycle for renames, selection changes, disappearance, quarantine, restoration, concurrent state writes, and interrupted publication. This stage closes cross-component behavior that cannot be proven within any one exporter.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Managed paths are containment-checked, reject traversal and symlink hazards, and never overwrite unrelated or unmanaged directories
- [x] #2 Project and group renames relocate content by stable ID, path reuse by another ID cannot overwrite prior content, and interrupted relocation recovers on a later run
- [x] #3 Complete authoritative discovery quarantines missing managed objects while incomplete discovery never drives scope-wide disappearance decisions
- [x] #4 Disabling a selected project or component removes prior output from the active corpus without deleting retained data, and safe re-selection or reappearance restores by ID
- [x] #5 Bounded concurrency, retries, rate-limit handling, API and Git timeouts, state serialization, and credential redaction behave consistently across resources
- [x] #6 One component failure does not block unrelated components and exit codes distinguish success, partial failure, fatal setup or discovery, and lock contention
- [x] #7 Tests cover rename, path reuse, disappearance, quarantine, restoration, unmanaged collisions, symlinks, interrupted relocation and publication, repeated authentication errors, token redaction, and TLS behavior
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Detect project stable IDs whose durable object path differs from complete live discovery before lifecycle relocation/upsert.
2. Force the existing complete work-item inventory/conversation path for selected renamed IDs, preserving full-success/checkpoint and incomplete-list no-quarantine behavior.
3. Resolve cross-project local links through current stable project-object paths so concurrent renamed-project refresh order cannot emit old links.
4. Add an integration test for an incremental-due project rename with unchanged item timestamps, asserting active/stale paths, SQLite paths, rendered provenance/links, checkpoints, and exit code; audit project/group metadata rename publication.
5. Run full 100% coverage and all release checks, update task evidence, and return only TASK-001.08 to Review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: reviewed all 165 prerequisite tests/modules, the complete specification, ADR 0001, parent, and dependencies. Confirmed that mutable paths were upserted without relocation, disappearance/selection retirement was incomplete, path checks were duplicated and symlink-following, startup recovery was selection-dependent, and configured workers were unused.

Implementation: added centralized path_safety lstat containment; schema-v5 stable object evidence and active-only work-item IID identity; stable-ID relocation/quarantine/restoration in reconcile; startup recovery for relocations and all known work-item/group-wiki publications; retained stale component generations for repository, project wiki, work-items, and group wiki; ID-safe work-item IID reuse with distinct raw snapshots; bounded project/group workers over serialized SQLite; deterministic final manifest publication; bounded Retry-After including HTTP dates; token-bearing Git argv/remote rejection; symlink-safe destination locking; and fsync for atomic files, staged trees, Git publication, and relocation directory entries.

Hardening review: complete discovery alone drives object quarantine; failed discovery records exit 2 when state exists and does not enter reconciliation. Incremental work-item omission remains non-destructive; only successful full listing quarantines. Fetch failures retain valid prior checkout metadata, checkout failures are inconsistent, and sibling components continue. Absolute/traversal/backslash/NUL/Git-internal paths, symlink ancestors, unmanaged markers, inconsistent IDs, unsafe persisted recovery paths, and staging/stale escapes are rejected. Quarantine metadata records stable ID, prior path, timestamp, reason, and non-claiming evidence; stale content is never automatically deleted.

Verification: 189 tests pass at 100.00% package coverage. Ruff check and format check, mypy, git diff --check, uv lock --check, and uv build pass. Tests cover project/group rename, path reuse, disappearance/reappearance, interrupted relocation/publication, all component retirement/restoration primitives, conclusive empty and transient retention, unmanaged/symlink/traversal collisions, work-item full-only disappearance and IID reuse, lock contention/symlink locking, bounded concurrency/state safety, repeated auth errors, bounded rate limits, redaction/credential-free remotes, custom CA/TLS/redirect behavior, and exit codes. No blocker or follow-up task was found. No new ADR was needed; ADR 0001 remains applicable. External GitLab capability limitations from prerequisite exporter tasks remain unchanged.

Review follow-up investigation: LifecycleReconciler correctly moves the project tree and orchestrator rewrites project.json/group.json at the new base, but work_items.content_path and rendered project_path remain mutable-path data. If no item updated_at changes, normal incremental selection can be empty and these fields remain stale. The existing force_full path already provides the correct complete-list safety contract, so the smallest robust change is to force it for selected IDs whose durable object path changed before reconciliation. Cross-project local links also need to use current project-object paths to remain deterministic under concurrent rename refreshes.

Review fix implemented: before lifecycle reconciliation overwrites object paths, orchestration records stable project IDs whose live path changed and forces only those selected work-item exporters through the existing complete-list path. This refreshes unchanged items, conversations, raw snapshots, rendered project_path/provenance/source/upload links, and SQLite content_path at the relocated destination. Cross-project links now derive target paths from current stable project-object state, avoiding concurrent worker-order dependence and failing closed for unsafe persisted object paths. The metadata audit confirmed project.json and group.json were already rewritten at current relocated paths; no metadata code change was required.

Review-fix verification: a two-run orchestration integration test starts incrementally current, renames both root group and selected work-items project while item updated_at values remain unchanged, and proves a complete second listing, no old active payload/metadata, current DB/raw/rendered paths and links, updated incremental/full-success checkpoints, and exit code 0. Existing full-list failure tests continue to prove incomplete listings do not quarantine and failed full refreshes remain due. 190 tests pass with 100.00% package coverage. Ruff check/format, mypy, git diff --check, uv lock --check, and uv build pass.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @human
created: 2026-09-20 09:24
---
The human authorized continuation of TASK-001.08 while dependencies TASK-001.05/.06/.07 remain in Review.
---

author: @human
created: 2026-09-20 09:56
---
Review found that relocating a selected work-items project can leave persisted item paths and rendered provenance stale when incremental selection returns no candidates. The requested fix must refresh rename-affected work items without weakening full-list failure semantics.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented the rename review fix by detecting stable project IDs whose durable path changed before reconciliation and forcing the existing safe complete work-item refresh only for those selected projects. Unchanged items now move with correct SQLite content_path, raw project_path, rendered provenance and source/upload links; cross-project local links resolve through current stable project-object paths instead of stale item paths. Project/group metadata publication was audited and already rewrites current paths. Verified by a two-run unchanged-timestamp rename integration test plus the existing failure-safety suite: 190 tests pass at 100.00% coverage, and Ruff, formatting, mypy, diff hygiene, lock validation, and package build all pass. No new limitation, follow-up task, or ADR is required.
<!-- SECTION:FINAL_SUMMARY:END -->
