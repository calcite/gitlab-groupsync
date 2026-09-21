---
id: TASK-001
title: Implement GitLab group reference synchronization
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 07:45'
updated_date: '2026-09-21 05:52'
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

author: Agent
created: 2026-09-20 10:31
---
Independent review of the repository at commit 7cd6a96 (all nine subtasks and TASK-001 in Review).

Gate re-verified locally: 194 tests pass, 100.00% coverage, `ruff check`, `ruff format --check`, `mypy`, and `uv lock --check` all clean on CPython 3.13.15. Documentation honesty about fixture-only GitLab coverage is accurate.

Findings that are not yet reflected in the task record:

1. Upload-link resolution is wrong for task-type work items. `work_items._project_url()` splits on the literal `/-/issues/`; real GitLab tasks carry `web_url` of the form `.../-/work_items/<iid>`, so the fallback `rsplit("/", 2)[0]` yields a base ending in `/-` and every relative `/uploads/...` link in a task description or comment renders as `<project>/-/-/uploads/...`. Verified by calling `_project_url` directly. Not caught because every fixture in `tests/test_work_items.py` uses an `/-/issues/{iid}` URL even for `item_type="task"`. This defeats specification section 7.2 ("Resolve relative GitLab upload links against the source project so they do not misleadingly point to nonexistent local files") for exactly the item type section 7.1 singles out as needing verification.

2. A work-item quarantine failure aborts the whole run instead of degrading to a partial failure. `WorkItemExporter.sync_project` calls `_quarantine_missing` outside any try block, and `_quarantine_item` can raise `UnsafePathError`/`OSError` from `contained_path` and `os.replace`. Reproduced: with a full listing that drops a known item and an unusable `stale/` directory, `sync_project` raises `UnsafePathError` rather than returning a failure count. In `SyncOrchestrator._run_project` that call is also unwrapped, so the exception escapes `executor.map`, discards every other project's result in the run, is recorded as outcome `failed` with exit code 2, and then escapes the Click command as an unhandled traceback. Specification section 8 requires continuing other resources on one resource failure, and section 4 reserves exit 2 for configuration/fatal setup errors.

3. GraphQL parent/child hierarchy is an unverified API shape that fails silently. `GitLabClient.work_item_hierarchy` queries `namespace(fullPath: $path) { workItem(iid:) }` with a *project* full path. GitLab's `Query.namespace` resolves group and user namespaces; project work items are normally reached through `project(fullPath:)` or `Query.workItem(id:)`. If the field resolves to null on a real server, the code returns the "parent/child hierarchy was not exposed for this work item" limitation rather than an error, so relationship coverage would be permanently and quietly empty with no failure signal. Only fixtures exercise this path. This is the specific risk specification section 7.1 asks to verify live.

Lower-severity observations (design/maintenance, not correctness): scaffold `gitlab_groupsync/gitlab_groupsync.py::hello()` and `diagnostics.doctor_as_dict` are dead outside tests; `GitResourceResult.changed`/`.error` are never read in production; `search_guide.py` imports the private `work_items._atomic_write_text`; the orchestrator calls the private `WorkItemExporter._recover_publications` and `GroupWikiExporter._recover`; `state.py` carries schema migrations v1 through v5 for an unreleased 0.1.0; `GitRunner.run` discards Git stderr so operational errors are not actionable; `GroupWikiExporter._remove_active` deletes active content without quarantine on a path only reachable when `lifecycle is None` (tests only), diverging from the lifecycle-backed behaviour; `work_items` stores an item count in the `revision` column; and several tests are explicitly branch-coverage-shaped (for example `test_publication_and_all_recovery_fallback_branches`, `test_listing_failure_bad_retry_full_due_and_recovery_failure_paths`), so the 100% figure partly reflects coverage-driven tests rather than behavioural specification.
---

author: Human
created: 2026-09-20 11:03
---
Asked for the review to be delivered as an HTML report kept in the repository, not only as a task comment.
---

author: Agent
created: 2026-09-20 11:03
---
Review report written to `docs/CODE_REVIEW_2026-09-20.html` as a standalone page (own doctype/meta/reset, no build step, no external assets beyond the Google Fonts stylesheet). Content is identical to comment #2. Nothing in the test suite globs `docs/`, so the addition does not affect `tests/test_documentation.py`, which references only CAPABILITIES.md, LIVE_TESTING.md, and ACCEPTANCE_TEST_MATRIX.md by name. Left uncommitted for human review; not linked from README.
---

author: Agent
created: 2026-09-20 11:08
---
Review findings converted to tracked work at human request: TASK-002 (upload links for task-type items, bug), TASK-003 (quarantine failure containment, bug), TASK-004 (live GraphQL hierarchy verification, spike, requires a human tester and a disposable instance; unassigned by design), and TASK-005 with seven subtasks for the low-severity design and maintenance items. TASK-005.07 depends on TASK-002. TASK-002 and TASK-003 are the two that gate acceptance of TASK-001; TASK-004 is a documented deferral.
---

author: Human
created: 2026-09-21 05:52
---
The human confirmed the tool is working as expected and requested closure of every task that was in Review, including this parent and its reviewed subtasks.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented the complete one-way selected GitLab group reference corpus through nine staged subtasks: Click/Onacol YAML configuration, stable-ID discovery/catalog refresh, SQLite state and diagnostics, repository/project-wiki synchronization, issue/task conversation export, per-group wiki export, and shared reconciliation/recovery/path-safety behavior, plus operational documentation and a deterministic sample corpus. ADR 0001 records the generated same-file stable-ID catalog architecture.

Verification: all nine subtasks remain in Review with every child criterion checked. The independent final gate passed on CPython 3.13.15: 194 tests, 100.00% coverage, Ruff check and format check, mypy, `uv lock --check`, `uv build`, `git diff --check`, and full `uv run tox`. This parent audit reconfirmed Python 3.13.15, exactly 194 collected tests, lock validity, installed CLI workflow help, and diff hygiene without duplicating the long gate. All six parent criteria are objectively met through the files and test evidence mapped in `docs/ACCEPTANCE_TEST_MATRIX.md`.

Known limitation: no disposable live GitLab instance/version was available; API and licensed group-wiki claims are explicitly fixture-only in `docs/CAPABILITIES.md`, with optional read-only live validation documented in `docs/LIVE_TESTING.md`. No concrete follow-up work was identified. Human acceptance remains pending.
<!-- SECTION:FINAL_SUMMARY:END -->
