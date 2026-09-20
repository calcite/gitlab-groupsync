---
id: TASK-001.08
title: 'Harden reconciliation, recovery, and path safety'
status: To Do
assignee: []
created_date: '2026-09-20 07:47'
labels: []
dependencies:
  - TASK-001.05
  - TASK-001.06
  - TASK-001.07
references:
  - specs/gitlab_reference_sync_spec.md
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Bring all exporters under the same safe lifecycle for renames, selection changes, disappearance, quarantine, restoration, concurrent state writes, and interrupted publication. This stage closes cross-component behavior that cannot be proven within any one exporter.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Managed paths are containment-checked, reject traversal and symlink hazards, and never overwrite unrelated or unmanaged directories
- [ ] #2 Project and group renames relocate content by stable ID, path reuse by another ID cannot overwrite prior content, and interrupted relocation recovers on a later run
- [ ] #3 Complete authoritative discovery quarantines missing managed objects while incomplete discovery never drives scope-wide disappearance decisions
- [ ] #4 Disabling a selected project or component removes prior output from the active corpus without deleting retained data, and safe re-selection or reappearance restores by ID
- [ ] #5 Bounded concurrency, retries, rate-limit handling, API and Git timeouts, state serialization, and credential redaction behave consistently across resources
- [ ] #6 One component failure does not block unrelated components and exit codes distinguish success, partial failure, fatal setup or discovery, and lock contention
- [ ] #7 Tests cover rename, path reuse, disappearance, quarantine, restoration, unmanaged collisions, symlinks, interrupted relocation and publication, repeated authentication errors, token redaction, and TLS behavior
<!-- AC:END -->
