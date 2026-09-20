---
id: TASK-001.02
title: Implement the Click and Onacol configuration foundation
status: To Do
assignee: []
created_date: '2026-09-20 07:46'
labels: []
dependencies:
  - TASK-001.01
references:
  - specs/gitlab_reference_sync_spec.md
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace the placeholder entrypoint with the public command structure and a schema-validated YAML configuration foundation. The CLI must retain Onacol layering and dependency injection while ensuring secrets are referenced rather than serialized into generated configuration.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The package installs the gl-groupsync command with config-template, discover, sync, status, and doctor help
- [ ] #2 Configuration layers bundled defaults, an optional user YAML file, environment overrides, and nested CLI overrides through one Onacol ConfigManager
- [ ] #3 The bundled schema validates GitLab, storage, sync, and generated inventory settings, including semantic constraints not expressible by Onacol alone
- [ ] #4 Token values are loaded from a named environment variable or protected token file and are never exported in configuration or diagnostics
- [ ] #5 Invalid configuration exits with code 2 and focused tests cover command help, layering, validation, and secret handling
<!-- AC:END -->
