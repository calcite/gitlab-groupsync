---
id: TASK-005
title: Clear design and maintenance debt found in review
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-09-20 12:22'
labels: []
dependencies: []
documentation:
  - docs/CODE_REVIEW_2026-09-20.html
  - docs/adr/0002-initial-state-schema-baseline.md
priority: medium
type: chore
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The TASK-001 review recorded eight design and maintenance observations. None is a correctness defect, so none blocks acceptance, but all are cheapest to clear now while the code is fresh and before 0.1.0 is published and a released schema and public surface have to be kept stable.

They are grouped as subtasks because they share one goal and one codebase while touching independent modules, so they can be reviewed and landed separately.

A theme runs through several of them: the `fail_under = 100` coverage gate keeps dead and speculative code alive by requiring a test for every branch, which makes coverage useless as a signal for what is actually reachable in production.

Detail: comment #2 on TASK-001 and `docs/CODE_REVIEW_2026-09-20.html`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Every subtask is closed or explicitly declined with a recorded reason
- [x] #2 The full gate still passes: tests, configured coverage threshold, ruff check, ruff format, mypy
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Complete each maintenance subtask independently, preserving observable behavior unless its acceptance criteria require a correction.
2. Keep shared persistence/recovery interfaces public and collapse unreleased compatibility code before 0.1.0.
3. Strengthen operational provenance, retention, diagnostics, and behavioral test fixtures.
4. Run the full repository quality gate and move every subtask plus the parent to human review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
All seven subtasks are in Review with every acceptance criterion checked. ADR 0002 records the first-release SQLite baseline; pre-release schema versions 2-5 require destination recreation.
Final validation: uv run tox passed 232 tests at 100.00% coverage, Ruff check, Ruff format --check, and mypy. git diff --check also passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed all TASK-005 maintenance work: removed dead/test-only APIs; centralized atomic text writes and public recovery contracts; established SQLite schema baseline 1 in ADR 0002; added actionable redacted Git failures; made group-wiki quarantine mandatory; separated work-item item_count from revision with legacy suppression/cleanup; and replaced branch-shaped tests with realistic behavioral fixtures.

Verification: uv run tox passed 232 tests with 100.00% coverage, Ruff lint/format, and mypy; git diff --check passed.

Known limitation: unreleased development databases marked schema versions 2-5 must be recreated, as documented in README and ADR 0002. No follow-up task was added.
<!-- SECTION:FINAL_SUMMARY:END -->
