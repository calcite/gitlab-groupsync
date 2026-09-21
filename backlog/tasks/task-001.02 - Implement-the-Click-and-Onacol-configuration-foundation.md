---
id: TASK-001.02
title: Implement the Click and Onacol configuration foundation
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 07:46'
updated_date: '2026-09-21 05:52'
labels: []
dependencies:
  - TASK-001.01
references:
  - specs/gitlab_reference_sync_spec.md
  - docs/adr/0001-generated-stable-id-selection-catalog.md
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
- [x] #1 The package installs the gl-groupsync command with config-template, discover, sync, status, and doctor help
- [x] #2 Configuration layers bundled defaults, an optional user YAML file, environment overrides, and nested CLI overrides through one Onacol ConfigManager
- [x] #3 The bundled schema validates GitLab, storage, sync, and generated inventory settings, including semantic constraints not expressible by Onacol alone
- [x] #4 Token values are loaded from a named environment variable or protected token file and are never exported in configuration or diagnostics
- [x] #5 Invalid configuration exits with code 2 and focused tests cover command help, layering, validation, and secret handling
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace the scaffold entry point with the installed `gl-groupsync` Click group and the required `config-template`, `discover`, `sync`, `status`, and `doctor` command/options/help; keep later-task workflows as explicit tested placeholders.
2. Add a configuration module that creates exactly one Onacol 0.3.5 `ConfigManager` per command invocation from `importlib.resources`, layers optional YAML, `GL_GROUPSYNC__...` environment values, and nested CLI extras, validates once, then applies focused semantic validation and passes the resulting config reference to command handlers.
3. Expand bundled defaults/schema for GitLab, storage, sync, and generated inventory, generate schema-free templates through Onacol, and implement separate token resolution from a named environment variable or permission-protected file without placing secret values in configuration or diagnostics.
4. Replace scaffold tests with focused CLI, precedence, schema/semantic validation, dependency-injection, token safety, and resource tests while preserving 100% coverage.
5. Update the lockfile through uv, run pytest with coverage, Ruff check/format check, mypy, and package build, then finalize only TASK-001.02 for human review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: TASK-001.01 is intentionally in Review per human authorization. The current package exposes only `gitlab_groupsync`, imports unavailable `pkg_resources`, and has a placeholder command/default file. Onacol 0.3.5 loads defaults and optional files in its constructor, then cascades environment and CLI layers before `validate()`. Its validator uses `allow_unknown=True`, requiring an application semantic pass for unknown/cross-field constraints. Onacol appends `_` to `env_var_prefix`; using `GL_GROUPSYNC_` is required to produce the specified `GL_GROUPSYNC__SECTION__KEY` names. Nested CLI keys replace underscores with hyphens. `ConfigManager` only needs the bundled resource path while constructing, so `importlib.resources.as_file()` can safely scope creation.

Implementation checkpoint: replaced `pkg_resources` with scoped `importlib.resources`, installed `gl-groupsync`, added all required Click commands/options/help, and isolated configuration/credential concerns in `gitlab_groupsync/config.py`. Domain workflows intentionally stop with tested exit-1 not-implemented errors after real config/token loading; discovery/API/state behavior remains in later tasks. The bundled schema covers GitLab, storage, sync, and inventory structures; semantic validation adds URL/base-path, credential-source exclusivity, absolute destination, unknown-key, stable-ID/path, root-membership, and duplicate constraints. Tokens resolve only into a local return value from the configured env-var name or owner-only regular file and are absent from generated YAML and diagnostics.

Verification checkpoint: `uv run pytest --cov=gitlab_groupsync --cov-report=term-missing tests/` passes 39 tests at 100%; `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy gitlab_groupsync`, and `git diff --check` pass. `uv lock` completed with no lockfile delta because no dependency versions changed. `uv build` produced both sdist and wheel; a clean temporary environment installed the wheel, ran `gl-groupsync --help`, and confirmed `default_config.yaml` is packaged.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-09-20 08:04
---
The human explicitly authorized proceeding while TASK-001.01 remains in Review; this dependency state is intentional.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented the `gl-groupsync` Click command group with schema-free template generation and the required discover/sync/status/doctor interfaces. Added a single-manager Onacol loading pipeline with bundled defaults/schema, optional YAML, `GL_GROUPSYNC__...` and nested CLI precedence, validation, config-reference injection, semantic GitLab/storage/sync/inventory checks, safe exit-2 mapping, and separate non-serialized token resolution from an environment-variable name or protected file. Later domain behavior remains explicit tested placeholders for downstream tasks.

Evidence: 39 focused tests pass at 100% coverage, including installed entry point/help, exact layer precedence, semantic/schema failures, exit codes, config injection, token-file permissions, and secret-free templates/diagnostics. Ruff check and format check, mypy, `git diff --check`, and `uv build` pass. A clean environment installed the wheel, executed `gl-groupsync --help`, and contained the bundled YAML resource. `uv lock` completed with no diff because dependencies did not change.

Known limitation: discover, sync, status, and doctor intentionally report not implemented after foundation loading; existing TASK-001.03 through TASK-001.07 own those workflows. No new follow-up or blocker was found. Architectural reference: `docs/adr/0001-generated-stable-id-selection-catalog.md`.
<!-- SECTION:FINAL_SUMMARY:END -->
