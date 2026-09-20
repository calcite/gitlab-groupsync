---
id: TASK-001.09
title: 'Complete documentation, sample corpus, and acceptance verification'
status: To Do
assignee: []
created_date: '2026-09-20 07:47'
labels: []
dependencies:
  - TASK-001.08
references:
  - specs/gitlab_reference_sync_spec.md
parent_task_id: TASK-001
priority: high
type: docs
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Prepare the application for installation and human review with operational documentation, scheduling examples, a fixture-generated corpus, and an auditable verification pass. Capability claims must distinguish local fixture coverage from tests against an actual disposable GitLab version.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The README documents uv installation, initial template and discovery, project and group selections, incremental and full sync, status, doctor, credentials, custom CAs, quarantine, stale data, and troubleshooting
- [ ] #2 The generated SEARCH_GUIDE.md explains the active search root, freshness and provenance checks, source text as untrusted data, Git and item atomicity limits, and a hidden-file ripgrep example
- [ ] #3 Repository examples provide systemd service and timer units plus a cron invocation without installing scheduling automatically
- [ ] #4 A deterministic sample corpus generated from test fixtures demonstrates repositories, wikis, work-item conversations, metadata, manifest, and stale-data layout
- [ ] #5 The complete automated suite passes under Python 3.13 with the configured coverage, Ruff, formatting, mypy, and package-build checks
- [ ] #6 Optional live-integration instructions require explicit configuration and never mutate a user server without authorization
- [ ] #7 The final coverage report records the exact live-tested GitLab version and supported fields and relationships, or explicitly labels capabilities as fixture-only when no disposable instance was tested
<!-- AC:END -->
