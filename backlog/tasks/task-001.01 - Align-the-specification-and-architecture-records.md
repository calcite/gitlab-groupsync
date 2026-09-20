---
id: TASK-001.01
title: Align the specification and architecture records
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 07:46'
updated_date: '2026-09-20 08:03'
labels: []
dependencies: []
references:
  - specs/gitlab_reference_sync_spec.md
  - docs/adr/0001-generated-stable-id-selection-catalog.md
modified_files:
  - specs/gitlab_reference_sync_spec.md
  - docs/adr/0001-generated-stable-id-selection-catalog.md
parent_task_id: TASK-001
priority: high
type: docs
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The source specification still describes TOML configuration, the gl-reference command, global group-wiki policy, and unconditional project inclusion. Bring the durable project records into agreement with the approved Python 3.13, uv, Click, Onacol YAML, generated-selection, and gl-groupsync design before implementation depends on stale requirements.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The implementation specification names gl-groupsync and describes YAML configuration orchestrated by Onacol
- [x] #2 The specification defines same-file atomic discovery refresh, stable-ID selection preservation, disabled defaults for new projects, and per-group wiki selection
- [x] #3 The specification defines normal-sync inventory drift warnings and their non-blocking exit-code behavior
- [x] #4 A repository ADR records the long-lived generated stable-ID selection catalog decision and its tradeoffs
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Align the stack, installed command, CLI examples, and configuration contract with Python 3.13, uv, Click, and Onacol-layered YAML.
2. Define the generated project/group inventory in the same YAML file, including stable-ID selection preservation, disabled defaults, deterministic atomic refresh, and incomplete-discovery safety.
3. Align synchronization scope, per-group wiki behavior, drift warnings, disappearance semantics, exit codes, acceptance tests, and deliverables with selectable discovery.
4. Add ADR 0001 documenting the generated stable-ID selection catalog, alternatives, and tradeoffs.
5. Run focused textual consistency checks and lightweight repository checks, then verify every acceptance criterion before finalization.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: `pyproject.toml` already requires Python >=3.13 and depends on Click and Onacol; the existing specification still names `gl-reference`, TOML/`tomllib`, unconditional inclusion, and a global `group_wikis` setting. No `docs/adr/` directory or ADR template exists, so this task will create a concise standard ADR as `docs/adr/0001-generated-stable-id-selection-catalog.md`.

Specification and ADR implementation complete. The specification now defines `gl-groupsync`, uv, Click/Onacol YAML layering, same-file atomic catalog refresh, stable-ID selection merging, disabled defaults, independent project-component/group-wiki flags, read-only normal-sync drift comparison, non-blocking drift-only exit behavior, and aligned quarantine/tests/deliverables. ADR 0001 records the decision, alternatives, and operational tradeoffs.

Verification checkpoint: legacy-term scans found no `gl-reference`, TOML/config.toml, `tomllib`, or global group-wiki mode references in the revised specification. `git diff --check` passes. `uv run pytest` is blocked during collection by the pre-existing `pkg_resources` import in `gitlab_groupsync/cli.py`; `uv run ruff check .` reports pre-existing import-order and unused-import findings in `cli.py` and `tests/test_gitlab_groupsync.py`. Those implementation files are outside this docs task and were not changed. `backlog task list --status "In Progress"` confirms TASK-001.01 is the only active task.

Final AC evidence from full manual review: AC1 is covered by specification sections 2 and 4 (installed command, uv/Click, Onacol ConfigManager layering, YAML example); AC2 by section 5.1 and group-wiki behavior (same-file atomic replacement, merge by object kind/global ID, disabled new entries, independent group flags); AC3 by sections 4 and 5.1 plus acceptance scenario 3 (actionable drift warning, continued valid work, drift-only exit 0); AC4 by ADR 0001 sections Decision, Consequences, and Alternatives considered.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Aligned the implementation specification with the approved Python 3.13/uv/Click/Onacol YAML and `gl-groupsync` design. Defined same-file atomic discovery refresh, stable-ID selection preservation, disabled defaults, independent project-component and per-group wiki selections, read-only normal-sync drift detection, drift-only exit code 0, and consistent disappearance/tests/deliverables. Added `docs/adr/0001-generated-stable-id-selection-catalog.md` with the decision, consequences, and rejected alternatives. Verification: full specification/ADR review and legacy-term consistency scans passed; `git diff --check` passed. Existing scaffold checks remain blocked outside this task: pytest cannot collect because `pkg_resources` is unavailable, and Ruff reports existing import findings. No additional follow-up task was created; downstream implementation remains in the existing TASK-001 subtasks.
<!-- SECTION:FINAL_SUMMARY:END -->
