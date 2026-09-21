---
id: TASK-005.02
title: Remove cross-module private imports and calls
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-09-21 05:52'
labels: []
dependencies: []
parent_task_id: TASK-005
type: chore
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found modules reaching into each other internals. `search_guide.py` imports the private `work_items._atomic_write_text`. `SyncOrchestrator._run_resources` calls the private `WorkItemExporter._recover_publications` and `GroupWikiExporter._recover`. The coupling ties unrelated modules to implementation details, and calling recovery through a private name makes a mandatory part of the run contract look optional to a future reader.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Atomic text publication is a shared public helper used by both call sites
- [x] #2 Run-start recovery is reachable through a public method on each exporter
- [x] #3 No module imports or calls an underscore-prefixed name belonging to another module
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Move atomic text publication into state.py as public atomic_write_text and update both production callers.
2. Rename exporter recovery hooks to the public recover method and update orchestration/tests.
3. Move direct atomic text failure coverage beside state persistence tests.
4. Run focused tests and scan production code for cross-module private references.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added state.atomic_write_text with unchanged-file detection and atomic durability, and switched work-item/Search Guide publication to it. Renamed exporter recovery hooks to recover and updated run-start orchestration.
Validation: 77 affected tests passed; focused Ruff check passed; repository search found no former private helper/recovery names or private production imports.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Centralized atomic text publication in the state module and made both exporter recovery contracts public. Verified state, work-item, group-wiki, orchestrator, and documentation behavior with 77 passing tests plus Ruff.
<!-- SECTION:FINAL_SUMMARY:END -->
