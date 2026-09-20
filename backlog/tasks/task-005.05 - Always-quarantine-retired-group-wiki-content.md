---
id: TASK-005.05
title: Always quarantine retired group-wiki content
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-09-20 12:09'
labels: []
dependencies: []
parent_task_id: TASK-005
type: chore
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found two divergent behaviours for the same condition. When a selected group wiki becomes conclusively empty, `GroupWikiExporter._remove_active` deletes the active tree outright, while the lifecycle-backed path quarantines it into `stale/`. The deleting branch runs only when the exporter is constructed with `lifecycle is None`, which `SyncOrchestrator` never does, so today it is reachable from tests alone. It is a live trap: any future caller that omits the lifecycle silently destroys retained content instead of retaining it. Specification section 6 requires a formerly populated resource that becomes conclusively empty to have its old searchable content moved to stale storage, and section 9 forbids automatic deletion of retained content in version 1.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Retiring a conclusively-empty group wiki always moves prior content to `stale/` with its ID, prior path, and reason
- [x] #2 The exporter cannot be constructed in a configuration whose retirement path deletes retained content
- [x] #3 Tests exercise retirement only through the supported path
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Require LifecycleReconciler when constructing GroupWikiExporter.
2. Remove the lifecycle-none branch and destructive _remove_active implementation.
3. Update all test exporters to use the supported lifecycle-backed path.
4. Strengthen empty-wiki tests to assert stale content and metadata identity, prior path, and reason.
5. Run focused group-wiki/orchestrator tests and static checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
GroupWikiExporter now requires a keyword-only LifecycleReconciler and always retires conclusively empty content through it; the destructive fallback was deleted. Empty-wiki coverage asserts retained page bytes and record metadata for object ID, prior source path, component, and reason.
Validation: 42 group-wiki/orchestrator tests passed; focused Ruff and format checks passed; no destructive fallback references remain.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Eliminated the group-wiki deletion configuration by making lifecycle retention mandatory. Prior wiki content now always moves to stale storage with durable identity/path/reason metadata, verified through supported-path tests.
<!-- SECTION:FINAL_SUMMARY:END -->
