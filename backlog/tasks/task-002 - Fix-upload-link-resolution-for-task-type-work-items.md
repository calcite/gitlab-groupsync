---
id: TASK-002
title: Fix upload-link resolution for task-type work items
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
priority: high
type: bug
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found that `work_items._project_url()` derives the project base URL by splitting `web_url` on the literal `/-/issues/`. GitLab serves task-type work items at `/-/work_items/<iid>`, so that marker is absent and the `rsplit("/", 2)[0]` fallback returns a base that still ends in `/-`. Every relative `/uploads/...` link in a task description or comment is then rewritten to `<project>/-/-/uploads/...`, which does not resolve. Confirmed by calling `_project_url()` directly; issue-type items are unaffected.

The defect survived the 100% coverage gate because every fixture in `tests/test_work_items.py` serves an `/-/issues/{iid}` URL even when `item_type="task"`, so no test ever supplies a realistic task URL. Specification section 7.2 requires upload links to resolve against the source project so they do not misleadingly point to nonexistent locations.

Detail: comment #2 on TASK-001 and `docs/CODE_REVIEW_2026-09-20.html`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Relative upload links in a task-type item description resolve to a project URL with no doubled `/-/` segment
- [x] #2 Relative upload links in comments on a task-type item resolve the same way
- [x] #3 Issue-type upload-link resolution is unchanged
- [x] #4 Work-item fixtures serve a `/-/work_items/<iid>` URL for `item_type="task"` and an `/-/issues/<iid>` URL for `item_type="issue"`
- [x] #5 A regression test fails against the current `_project_url` implementation and passes after the fix
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Derive the project base from GitLab's common /-/ route separator while preserving the non-canonical fallback.
2. Make issue/task fixtures emit their real canonical URL forms and assert description/comment upload resolution for both types.
3. Run focused and full quality checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Confirmed the defect in gitlab_groupsync/work_items.py: _project_url only recognizes /-/issues/. The existing fixture helper always emits issue URLs, including for task records; the existing fallback test covers URLs without GitLab's /-/ separator.

Implemented project-base extraction at the shared GitLab /-/ route boundary. Task fixtures now use /-/work_items/<iid>, including relationship URLs, and task description/comment uploads are asserted alongside unchanged issue behavior.
Validation: uv run tox passed (196 tests, 100% coverage, Ruff lint/format, and mypy). No known limitations or follow-up work; no ADR was needed.
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
Fixed task upload URLs by resolving both issue and work-item routes from the common GitLab project boundary. Added realistic task URLs and description/comment regression assertions. Verified with uv run tox: 196 tests passed at 100% coverage; lint, formatting, and type checks passed.
<!-- SECTION:FINAL_SUMMARY:END -->
