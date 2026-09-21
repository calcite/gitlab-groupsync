---
id: TASK-005.03
title: Collapse speculative state schema migrations
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-09-21 05:52'
labels: []
dependencies: []
documentation:
  - docs/adr/0002-initial-state-schema-baseline.md
parent_task_id: TASK-005
type: chore
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found that `state.py` carries incremental upgrade paths from schema versions 1, 2, 3 and 4 up to version 5, including a table rebuild and copy. The package has never been released, so no destination in existence can hold a schema earlier than the current one. These branches can only ever run against databases the project itself never shipped, they are maintained and type-checked forever, and they exist in the suite solely to satisfy the coverage gate.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Only current-schema creation and the newer-than-supported rejection remain
- [x] #2 A destination created by the current code opens without running any migration
- [x] #3 The first released schema version is documented as the baseline that future migrations start from
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Reset the complete current SQLite layout to first-release schema baseline version 1.
2. Replace incremental pre-release upgrades with baseline creation, current-version open, and newer-version rejection.
3. Replace synthetic migration tests with tests for baseline initialization, reopen without initialization, and unsupported newer schemas.
4. Add ADR 0002 and README guidance documenting the supported migration baseline and pre-release database recreation.
5. Run focused state/documentation tests and static checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The released baseline is now SCHEMA_VERSION 1 with the full current table/index layout. Writable opens create only version-0 stores, leave version 1 untouched, and reject higher versions; pre-release versions 2-5 require recreation.
Validation: 17 state/documentation tests passed, including a reopen test that fails if schema creation runs; focused Ruff and format checks passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Squashed unreleased SQLite history into first-release baseline version 1, removed all speculative upgrade branches/tests, and documented future migration policy in ADR 0002 and README. Verified current initialization/reopen and newer-schema rejection with focused tests and static checks.
<!-- SECTION:FINAL_SUMMARY:END -->
