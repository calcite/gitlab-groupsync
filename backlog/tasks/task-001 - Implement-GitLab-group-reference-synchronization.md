---
id: TASK-001
title: Implement GitLab group reference synchronization
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 07:45'
updated_date: '2026-09-20 10:17'
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
- [x] #1 The gl-groupsync CLI provides config template generation, discover, sync, status, and doctor workflows
- [x] #2 Discovery atomically refreshes the same YAML configuration, preserves selections by GitLab global ID, defaults new projects and group wikis to disabled, and never replaces the file after incomplete discovery
- [x] #3 Normal synchronization detects inventory drift, logs an actionable discovery-refresh warning, and continues synchronizing valid selected resources
- [x] #4 Selected repositories, project wikis, work items, and group wikis are synchronized with the failure, provenance, reconciliation, quarantine, and security behavior required by the specification
- [x] #5 Automated tests cover the specification acceptance scenarios and the discovery-selection workflow without requiring a production GitLab instance
- [x] #6 Installation, configuration, authentication, scheduling, search, status, stale-content, and optional live-test behavior are documented
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Audit the completed staged subtasks and final specification, ADR 0001, README, capability report, and acceptance matrix against the parent scope. 2. Verify each parent acceptance criterion from concrete implementation/test evidence and the independent repository-wide final gate. 3. Record the consolidated architecture, verification evidence, fixture-only/no-live-GitLab limitation, and follow-up status, then move only TASK-001 to Review for human acceptance.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Parent acceptance audit:
- AC1: `pyproject.toml` installs `gl-groupsync`; current `gl-groupsync --help` exposes config-template, discover, sync, status, and doctor. TASK-001.02 and CLI/diagnostics tests verify workflow help, configuration, exits, status, and doctor.
- AC2: ADR 0001 and specification section 5.1 define the stable-ID same-file catalog. TASK-001.03 plus discovery tests verify deterministic atomic replacement, selection preservation, disabled defaults, root protection, and byte-identical retention after incomplete pages.
- AC3: TASK-001.05/.08 and orchestrator/discovery tests verify added/absent/renamed/path-reused drift persistence, the actionable discover warning, continued selected-resource work, no YAML rewrite, and drift-only exit 0.
- AC4: TASK-001.05-.08 verify repositories/project wikis with temporary real Git, issue/task conversations, group wikis, independent failure handling, provenance/raw metadata, retries/checkpoints, stable-ID relocation, quarantine/restoration/recovery, path/symlink containment, credential redaction, TLS, locking, and exit semantics.
- AC5: `docs/ACCEPTANCE_TEST_MATRIX.md` maps all 16 specification scenarios to automated tests; current collection is exactly 194 tests. The independent final gate passed on CPython 3.13.15 with 194 tests and 100.00% coverage, Ruff check, Ruff format check, mypy, `uv lock --check`, `uv build`, `git diff --check`, and full `uv run tox`. Current lightweight confirmation: CPython 3.13.15, 194 tests collected, `uv lock --check`, installed CLI help, and `git diff --check` pass.
- AC6: `README.md`, generated SEARCH_GUIDE behavior, `docs/CAPABILITIES.md`, `docs/LIVE_TESTING.md`, scheduler/config examples, and TASK-001.09 documentation tests cover installation, configuration, credentials/custom CA, scheduling, search/freshness, status/doctor, quarantine/stale content, troubleshooting, and optional live testing.
Architecture: ADR 0001 (`docs/adr/0001-generated-stable-id-selection-catalog.md`) records the generated same-file stable-ID selection catalog and tradeoffs. Known limitation: GitLab API and licensed group-wiki compatibility are fixture-only; no disposable live GitLab instance/version was tested or claimed. No concrete follow-up task was identified.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-09-20 07:45
---
Use the installed command name `gl-groupsync`. Discovery refreshes the same YAML file, new projects default to disabled, and group/subgroup wikis are selected per group. The remainder of the proposed implementation plan is approved.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented the complete one-way selected GitLab group reference corpus through nine staged subtasks: Click/Onacol YAML configuration, stable-ID discovery/catalog refresh, SQLite state and diagnostics, repository/project-wiki synchronization, issue/task conversation export, per-group wiki export, and shared reconciliation/recovery/path-safety behavior, plus operational documentation and a deterministic sample corpus. ADR 0001 records the generated same-file stable-ID catalog architecture.

Verification: all nine subtasks remain in Review with every child criterion checked. The independent final gate passed on CPython 3.13.15: 194 tests, 100.00% coverage, Ruff check and format check, mypy, `uv lock --check`, `uv build`, `git diff --check`, and full `uv run tox`. This parent audit reconfirmed Python 3.13.15, exactly 194 collected tests, lock validity, installed CLI workflow help, and diff hygiene without duplicating the long gate. All six parent criteria are objectively met through the files and test evidence mapped in `docs/ACCEPTANCE_TEST_MATRIX.md`.

Known limitation: no disposable live GitLab instance/version was available; API and licensed group-wiki claims are explicitly fixture-only in `docs/CAPABILITIES.md`, with optional read-only live validation documented in `docs/LIVE_TESTING.md`. No concrete follow-up work was identified. Human acceptance remains pending.
<!-- SECTION:FINAL_SUMMARY:END -->
