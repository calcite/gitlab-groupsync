---
id: TASK-001.04
title: 'Implement durable state, locking, status, and doctor'
status: To Do
assignee: []
created_date: '2026-09-20 07:46'
labels: []
dependencies:
  - TASK-001.03
references:
  - specs/gitlab_reference_sync_spec.md
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Synchronization needs transactional identity, checkpoint, and run history before content exporters can safely publish or recover. Add local state and diagnostics that distinguish current locks, interrupted runs, stale retained content, configuration drift, and remote capability failures.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A versioned SQLite database persists instance and root identity, objects, resources, runs, checkpoints, retry queues, and recovery records transactionally
- [ ] #2 A destination cannot be reused for a different GitLab instance or root group without an explicit safe workflow
- [ ] #3 An OS-backed exclusive lock yields exit code 3 for contention and process death does not require stale lock cleanup
- [ ] #4 status is local and read-only, supports human and JSON output, and reports last-run health, freshness, retained content, and last-observed inventory drift
- [ ] #5 doctor validates configuration, Git, authentication, TLS and custom CA behavior, root visibility, server metadata, and requested capabilities without publishing corpus content
- [ ] #6 Manifest and resource metadata writes are atomic and tests cover identity mismatch, locking, interrupted runs, drift reporting, and diagnostic failures
<!-- AC:END -->
