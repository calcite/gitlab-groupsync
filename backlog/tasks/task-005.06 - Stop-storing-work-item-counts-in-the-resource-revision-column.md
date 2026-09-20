---
id: TASK-005.06
title: Stop storing work-item counts in the resource revision column
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-09-20 12:12'
labels: []
dependencies: []
parent_task_id: TASK-005
type: chore
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found that `WorkItemExporter.sync_project` writes `str(len(...))`, an item count, into the `revision` column of the work_items resource row. That column carries Git commit revisions for every other resource kind and is published through `manifest.json` and `gl-groupsync status --json`. An agent or operator reading provenance sees a small integer where a commit SHA appears elsewhere and has no way to tell which it is, which undercuts the provenance contract in specification section 10.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The `revision` column holds only revision identifiers, or null for resources that have none
- [x] #2 Work-item counts are published under a distinctly named field
- [x] #3 Manifest and status output let a reader distinguish a revision from an item count
- [x] #4 Existing destinations are handled without presenting a stale count as a revision
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Enforce null revision for work_items resource writes and clear legacy values on writable state open.
2. Derive a distinct item_count from durable work-item rows in object and status projections while suppressing legacy revisions in read-only output.
3. Remove count-as-revision writes from WorkItemExporter and preserve existing all-row count semantics.
4. Update state/work-item/orchestrator tests plus generated sample corpus to distinguish revision from item_count.
5. Run focused tests, regenerate checked-in examples, and run static checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Work-item revisions are normalized to null on write and legacy values are cleared on writable open. Read-only/object/status projections defensively suppress legacy values and derive item_count from all durable work_items rows, preserving the prior count semantics without denormalization.
Validation: 67 affected tests passed, including legacy read-only status, manifest, writable cleanup, exporter, and orchestration assertions; sample corpus regenerated; focused Ruff and format checks passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Separated work-item counts from source revisions. Work-item metadata/status now exposes item_count with revision null, legacy count-shaped revisions cannot leak through read-only projections and are cleared on writable open, and the generated sample demonstrates the contract.
<!-- SECTION:FINAL_SUMMARY:END -->
