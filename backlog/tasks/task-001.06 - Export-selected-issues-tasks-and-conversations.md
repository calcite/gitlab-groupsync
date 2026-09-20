---
id: TASK-001.06
title: 'Export selected issues, tasks, and conversations'
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
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create a searchable current-state representation of selected projects issues and tasks without losing conversations or publishing partial responses. The exporter must remain honest about GitLab CE capability coverage and reconcile sources that are not reliable change feeds.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Selected projects export accessible open and closed issue and task types, including archived-project items, with stable global and project-local identity
- [ ] #2 Every discussion page is retrieved and standalone comments, threaded replies, system notes, authors, IDs, timestamps, resolution data, and supported relationships are preserved without duplicate notes
- [ ] #3 One deterministic UTF-8 Markdown file per item preserves source descriptions and comments, canonical provenance, resolved upload links, human threads, separate system activity, and known limitations
- [ ] #4 Incremental runs use overlap windows and durable retries while full reconciliation detects edits, deleted comments, closed-item changes, and disappeared items
- [ ] #5 A partial conversation response never replaces a previous complete file, checkpoints do not advance unsafely, and volatile check timestamps do not rewrite unchanged Markdown
- [ ] #6 Raw structured snapshots remain outside the active corpus and publication is recoverable after interruption
- [ ] #7 Tests cover issue and child task relationships, standalone and threaded conversation, edits and deletions without parent timestamp changes, pagination failures, overlap deduplication, retries, and full-only disappearance quarantine
<!-- AC:END -->
