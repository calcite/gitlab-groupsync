---
id: TASK-001.01
title: Align the specification and architecture records
status: To Do
assignee: []
created_date: '2026-09-20 07:46'
labels: []
dependencies: []
references:
  - specs/gitlab_reference_sync_spec.md
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
- [ ] #1 The implementation specification names gl-groupsync and describes YAML configuration orchestrated by Onacol
- [ ] #2 The specification defines same-file atomic discovery refresh, stable-ID selection preservation, disabled defaults for new projects, and per-group wiki selection
- [ ] #3 The specification defines normal-sync inventory drift warnings and their non-blocking exit-code behavior
- [ ] #4 A repository ADR records the long-lived generated stable-ID selection catalog decision and its tradeoffs
<!-- AC:END -->
