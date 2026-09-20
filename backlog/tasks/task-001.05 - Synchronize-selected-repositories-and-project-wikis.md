---
id: TASK-001.05
title: Synchronize selected repositories and project wikis
status: To Do
assignee: []
created_date: '2026-09-20 07:46'
labels: []
dependencies:
  - TASK-001.04
references:
  - specs/gitlab_reference_sync_spec.md
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Materialize selected project default branches and optional project wikis as independently managed Git resources. Updates must remain one-way and safe in the presence of force-pushes, branch changes, local modifications, empty resources, timeouts, and interrupted staging.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A selected project repository is cloned through staging and published only after a successful detached default-branch checkout
- [ ] #2 Existing clean checkouts fetch the current default branch with force-push-safe refspecs, remove upstream-deleted files, and skip unchanged revisions
- [ ] #3 Project repositories and wikis have independent states, revisions, timestamps, and failure handling
- [ ] #4 Empty, disabled, inaccessible, and transiently failed wikis are distinguished to the extent supported by observed API and Git evidence
- [ ] #5 Local tracked or untracked changes are never discarded and produce a local-conflict result for only that resource
- [ ] #6 Git operations disable LFS smudging and submodule recursion, are noninteractive, enforce timeouts, and never expose tokens in URLs, arguments, logs, or errors
- [ ] #7 Tests use temporary real Git repositories and cover initial import, incremental and no-op updates, deleted files, branch rename, force-push, wiki branch differences, component isolation, local conflicts, and timeouts
<!-- AC:END -->
