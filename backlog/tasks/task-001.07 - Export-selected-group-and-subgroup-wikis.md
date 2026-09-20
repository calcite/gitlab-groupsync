---
id: TASK-001.07
title: Export selected group and subgroup wikis
status: To Do
assignee: []
created_date: '2026-09-20 07:47'
labels: []
dependencies:
  - TASK-001.04
references:
  - specs/gitlab_reference_sync_spec.md
parent_task_id: TASK-001
priority: medium
type: feature
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The generated inventory allows each root or descendant group wiki to be selected independently, including groups without projects. Implement this optional licensed capability without turning one unavailable wiki into an instance-wide assumption or a failure for unselected groups.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every discovered root or descendant group has an independent wiki selection and unselected groups make no wiki requests
- [ ] #2 Selected group wikis are exported into the group content tree through a verified clone mechanism or the documented Group Wikis API while preserving searchable source content
- [ ] #3 Observed empty, unavailable, forbidden, missing, unsupported, and transient-error evidence is recorded without inferring an instance-wide result from one response
- [ ] #4 An unavailable selected group wiki is a partial failure that does not block other groups or project resources
- [ ] #5 Tests cover groups without projects, disabled selections, fixture-supported exports, per-group unavailable responses, and honest capability limitations
<!-- AC:END -->
