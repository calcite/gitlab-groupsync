---
id: TASK-005.01
title: Remove dead scaffold code and unused result fields
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-09-21 05:52'
labels: []
dependencies: []
parent_task_id: TASK-005
type: chore
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found production code kept alive only by tests. `gitlab_groupsync/gitlab_groupsync.py::hello()` is project-generator scaffold. `diagnostics.doctor_as_dict` has no production caller. `GitResourceResult.changed` is set but never read outside tests, and `.error` is never set at all. Because each has a test written to satisfy the coverage gate, coverage reports them as exercised and cannot flag them as dead.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The scaffold module is removed together with its test, or gains a real caller
- [x] #2 `doctor_as_dict` is consumed by production code or removed with its test
- [x] #3 Fields on `GitResourceResult` that no production code reads are removed or consumed
- [x] #4 The suite passes at the configured coverage threshold after removal
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Remove the unused scaffold module and its sole test.
2. Remove the unused structured doctor helper and its test-only assertions.
3. Reduce GitResourceResult to status, revision, and branch; retain observable Git synchronization assertions.
4. Run focused tests and the configured coverage suite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Removed the generator scaffold and doctor_as_dict rather than expanding either public surface. GitResourceResult now carries only status, revision, and branch; tests assert filesystem/revision behavior instead of the removed changed flag.
Validation: 76 focused tests passed; full suite passed 195 tests with 100.00% coverage.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Removed production code that only tests consumed and reduced GitResourceResult to fields used by orchestration. Verified with the focused CLI/diagnostics/Git/orchestrator suites and the full 195-test suite at 100% coverage.
<!-- SECTION:FINAL_SUMMARY:END -->
