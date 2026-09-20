---
id: TASK-001.03
title: Implement GitLab discovery and selectable inventory refresh
status: To Do
assignee: []
created_date: '2026-09-20 07:46'
labels: []
dependencies:
  - TASK-001.02
references:
  - specs/gitlab_reference_sync_spec.md
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Users need an authoritative pre-discovery phase before choosing what to synchronize. Implement the read-only GitLab API traversal and same-file generated catalog so selections remain stable through path changes and incomplete API traversal cannot corrupt scope.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Discovery resolves the root group and retrieves the root, every visible descendant group, and every owned project with complete pagination, archived-project inclusion, shared-project exclusion, and ID deduplication
- [ ] #2 A successful discover command atomically refreshes the same YAML file and produces deterministic project and group ordering
- [ ] #3 Selections are preserved by global ID, renamed paths are updated, new projects and group wikis default to disabled, and objects absent from a complete inventory are removed
- [ ] #4 A failed or partial discovery leaves the existing YAML unchanged and does not report an authoritative empty inventory
- [ ] #5 Changing the stable root-group identity requires explicit replacement rather than silently replacing the catalog
- [ ] #6 Inventory comparison identifies added, absent, renamed, and path-reused objects for sync warnings and manifest reporting
- [ ] #7 Tests cover nested and empty groups, pagination, archived and shared projects, deduplication, refresh preservation, failed pages, and root replacement protection
<!-- AC:END -->
