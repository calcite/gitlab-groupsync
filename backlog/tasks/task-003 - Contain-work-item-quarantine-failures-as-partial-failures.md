---
id: TASK-003
title: Contain work-item quarantine failures as partial failures
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 11:07'
updated_date: '2026-09-21 05:52'
labels: []
dependencies: []
references:
  - specs/gitlab_reference_sync_spec.md
documentation:
  - docs/CODE_REVIEW_2026-09-20.html
modified_files:
  - gitlab_groupsync/work_items.py
  - tests/test_work_items.py
  - tests/test_orchestrator.py
priority: high
type: bug
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found that `WorkItemExporter.sync_project` calls `_quarantine_missing` outside any `try` block, and `_quarantine_item` can raise `UnsafePathError` from `contained_path` or `OSError` from `os.replace`. `SyncOrchestrator._run_project` does not wrap that call either.

Reproduced with a complete listing that omits a known item plus an unusable `stale/` directory: `sync_project` raises `UnsafePathError` instead of returning a failure count. The exception escapes `executor.map`, discards every other project result in the same run, records the run as outcome `failed` with exit code 2, and leaves the Click command to print an unhandled traceback.

Specification section 8 requires other resources to continue when one resource fails, and section 4 reserves exit code 2 for configuration and fatal setup failures. A single work-item quarantine problem is a partial operational failure and belongs in exit code 1.

Detail: comment #2 on TASK-001 and `docs/CODE_REVIEW_2026-09-20.html`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A quarantine failure for one work item is counted as a failure and does not propagate out of `WorkItemExporter.sync_project`
- [x] #2 A quarantine failure in one project does not prevent other projects in the same run from being synchronized
- [x] #3 A run whose only failures are quarantine failures exits with code 1 and is recorded with outcome `partial`
- [x] #4 No unhandled traceback reaches the CLI for this failure class
- [x] #5 The failure is recorded against the affected resource with a redacted, actionable error and retained-content state
- [x] #6 Regression tests cover containment at both the exporter and the orchestrator level
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Contain each missing-item quarantine operation inside the exporter and count failures without exposing filesystem exception details.
2. Report a redacted quarantine-specific project resource error, retain prior-content state, and withhold full-success state on failure.
3. Add exporter-level reproduction and a two-project orchestration regression proving continuation, partial outcome, and exit code 1.
4. Run focused and full quality checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Confirmed _quarantine_missing runs outside containment and _quarantine_item can expose StateError, UnsafePathError, and OSError. A contained exporter result already flows through the orchestrator as exit code 1/outcome partial, so exporter containment plus a real two-project orchestration regression is the minimal fix.

Implemented per-item quarantine containment and failure counting. Missing-item quarantine failures now produce a redacted resource error, retain active content, leave full-success unchanged, and return normally; unsafe replacement quarantine errors also enter item-level containment. The orchestration regression performs two real project exports, induces one quarantine path failure, and verifies the other project continues with exit code 1/outcome partial.
Validation: uv run tox passed (196 tests, 100% coverage, Ruff lint/format, and mypy). Existing CLI partial-exit coverage plus the non-propagating orchestration test verifies no traceback path remains. No known limitations or follow-up work; no ADR was needed.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-09-21 05:52
---
The human confirmed the tool is working as expected and requested closure of every task that was in Review, including this task.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Contained work-item quarantine failures as partial operational failures. Failed quarantine operations are counted, reported with a redacted actionable error and retained-content state, and no longer abort other projects or the CLI run. Verified exporter and two-project orchestration behavior plus the full uv run tox pipeline: 196 tests passed at 100% coverage; lint, formatting, and type checks passed.
<!-- SECTION:FINAL_SUMMARY:END -->
