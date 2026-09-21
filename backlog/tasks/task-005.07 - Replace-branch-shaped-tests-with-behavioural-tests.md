---
id: TASK-005.07
title: Replace branch-shaped tests with behavioural tests
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-09-21 05:52'
labels: []
dependencies:
  - TASK-002
parent_task_id: TASK-005
type: task
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found several tests named and structured around branch coverage rather than behaviour, for example `test_publication_and_all_recovery_fallback_branches` and `test_listing_failure_bad_retry_full_due_and_recovery_failure_paths`. They keep the 100% gate green while asserting many unrelated concerns in one function, so a failure does not localize to a behaviour and a reader cannot tell what contract is being protected.

The gate is also misleading as a safety signal: both confirmed defects from the review sat inside covered lines. Line coverage measures which statements ran, not which inputs were tried, and the fixtures supplied only the inputs the code already handled. TASK-002 fixes the specific task-URL fixture; this task addresses the pattern behind it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Tests asserting several unrelated behaviours are split so one failure identifies one behaviour
- [x] #2 Test names state the behaviour asserted rather than the branches reached
- [x] #3 Work-item fixtures carry realistic URL and payload shapes for every exported item type
- [x] #4 Coverage remains at the configured threshold
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Split explicitly branch/path-shaped group-wiki, work-item, and reconciliation grab-bag tests into behavior-named tests with focused setup.
2. Extract task canonical-URL/upload behavior from the broad exporter scenario.
3. Correct every remaining task fixture and generated sample relationship to use /-/work_items URLs and realistic per-type payload fields.
4. Regenerate the sample corpus and strengthen documentation assertions for issue/task routes.
5. Run affected suites, then the full configured 100% coverage gate and static checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Split the review-cited group-wiki and work-item grab-bags plus related reconciliation/recovery collections into behavior-named tests. Extracted task URL/upload and no-rewrite contracts. Corrected task URLs in state, cross-project, discovery, and sample fixtures, including issue-to-task relationships.
Validation: full suite passed 232 tests at 100.00% coverage; repository-wide Ruff and format checks passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced branch-shaped test collections with focused behavioral tests and made issue/task fixture routes realistic throughout tests and the generated sample. The full 232-test suite retains 100% coverage and passes formatting/lint checks.
<!-- SECTION:FINAL_SUMMARY:END -->
