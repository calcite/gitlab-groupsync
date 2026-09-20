---
id: TASK-001
title: Implement GitLab group reference synchronization
status: To Do
assignee: []
created_date: '2026-09-20 07:45'
updated_date: '2026-09-20 07:45'
labels: []
dependencies: []
references:
  - specs/gitlab_reference_sync_spec.md
priority: high
type: feature
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Build the one-way local GitLab group reference corpus described by the implementation specification. The current repository is a Python 3.13 scaffold using uv, Click, and Onacol. Configuration is YAML and includes a generated stable-ID inventory that lets users select projects, project wikis, work items, and group wikis before synchronization. The installed command is gl-groupsync.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The gl-groupsync CLI provides config template generation, discover, sync, status, and doctor workflows
- [ ] #2 Discovery atomically refreshes the same YAML configuration, preserves selections by GitLab global ID, defaults new projects and group wikis to disabled, and never replaces the file after incomplete discovery
- [ ] #3 Normal synchronization detects inventory drift, logs an actionable discovery-refresh warning, and continues synchronizing valid selected resources
- [ ] #4 Selected repositories, project wikis, work items, and group wikis are synchronized with the failure, provenance, reconciliation, quarantine, and security behavior required by the specification
- [ ] #5 Automated tests cover the specification acceptance scenarios and the discovery-selection workflow without requiring a production GitLab instance
- [ ] #6 Installation, configuration, authentication, scheduling, search, status, stale-content, and optional live-test behavior are documented
<!-- AC:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-09-20 07:45
---
Use the installed command name `gl-groupsync`. Discovery refreshes the same YAML file, new projects default to disabled, and group/subgroup wikis are selected per group. The remainder of the proposed implementation plan is approved.
---
<!-- COMMENTS:END -->
