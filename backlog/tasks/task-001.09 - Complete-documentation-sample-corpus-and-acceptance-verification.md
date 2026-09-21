---
id: TASK-001.09
title: 'Complete documentation, sample corpus, and acceptance verification'
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 07:47'
updated_date: '2026-09-21 05:52'
labels: []
dependencies:
  - TASK-001.08
references:
  - specs/gitlab_reference_sync_spec.md
modified_files:
  - README.md
  - CHANGELOG.md
  - pyproject.toml
  - gitlab_groupsync/orchestrator.py
  - gitlab_groupsync/search_guide.py
  - tests/test_orchestrator.py
  - tests/test_documentation.py
  - docs/CAPABILITIES.md
  - docs/LIVE_TESTING.md
  - docs/ACCEPTANCE_TEST_MATRIX.md
  - examples
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
- [x] #1 The README documents uv installation, initial template and discovery, project and group selections, incremental and full sync, status, doctor, credentials, custom CAs, quarantine, stale data, and troubleshooting
- [x] #2 The generated SEARCH_GUIDE.md explains the active search root, freshness and provenance checks, source text as untrusted data, Git and item atomicity limits, and a hidden-file ripgrep example
- [x] #3 Repository examples provide systemd service and timer units plus a cron invocation without installing scheduling automatically
- [x] #4 A deterministic sample corpus generated from test fixtures demonstrates repositories, wikis, work-item conversations, metadata, manifest, and stale-data layout
- [x] #5 The complete automated suite passes under Python 3.13 with the configured coverage, Ruff, formatting, mypy, and package-build checks
- [x] #6 Optional live-integration instructions require explicit configuration and never mutate a user server without authorization
- [x] #7 The final coverage report records the exact live-tested GitLab version and supported fields and relationships, or explicitly labels capabilities as fixture-only when no disposable instance was tested
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add deterministic SEARCH_GUIDE.md content and atomically publish it after every initialized sync pass that completes resource processing, including partial operational outcomes, without publishing it after fatal setup/discovery failure.
2. Replace the scaffold README with complete Python 3.13/uv installation, configuration layering, credentials/transports/CA, discover/select/sync/status/doctor, destination/search/freshness, conflict/retry/exit/quarantine/stale, troubleshooting, scheduling, and capability guidance using only gl-groupsync examples.
3. Add schema-free bootstrap/discovered CE YAML, systemd hourly service/timer, cron equivalent, optional read-only live-test contract, and an exact fixture-only capability/coverage report.
4. Add a deterministic fixture-data sample-corpus generator using production work-item and search-guide renderers; check in its repository, project wiki, REST group wiki, issue/task conversation, metadata, manifest, and stale/quarantine output while excluding secrets, SQLite, and Git internals.
5. Add tests for deterministic search-guide publication, sample regeneration freshness, examples/docs contracts, package data, and the acceptance-scenario audit; fix any concrete defect exposed without broadening scope.
6. Update the initial-release changelog and run pytest at configured 100% coverage, Ruff check/format, mypy, tox if feasible, uv lock --check, uv build, clean wheel install plus gl-groupsync --help, package-data/default-config inspection, docs/example scans, and git diff hygiene.
7. Follow task-finalization guidance, reread and objectively verify every criterion, record exact checks and fixture-only/live-test limitations, and move only TASK-001.09 to Review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: all eight dependencies are in Review under explicit human authorization. The complete application and 190 tests implement the specification behavioral core, including discovery/drift, real Git updates, work-item and group-wiki exports, recovery, quarantine, status/doctor, safety, retries, and exit codes. Missing TASK-001.09 deliverables are destination SEARCH_GUIDE.md generation/publication, production README, checked-in config/scheduler/live-test/capability documentation, a fixture-generated sample corpus and freshness validator, and a numbered acceptance-test audit. No disposable GitLab instance/version was provided, so all API capability claims must remain explicitly fixture-only and not live-tested.

Implementation checkpoint: added deterministic atomic SEARCH_GUIDE.md publication after every initialized sync that completes resource processing (including partial resource outcomes), replaced the scaffold README, added schema-free bootstrap/discovered CE config examples, systemd/cron examples, fixture-only capability and optional read-only live-test contracts, and mapped all 16 numbered specification scenarios to existing automated evidence. Added a reproducible generator and checked-in synthetic sample corpus with selected repository/project wiki/REST group wiki/work-item conversations and relationships, metadata/manifest, SEARCH_GUIDE, and stale object/component records; a test regenerates and compares every byte while checking exclusion of Git internals, SQLite, credentials, and secrets. Focused tests pass, and the complete suite passes 194 tests at 100.00% coverage.

Final acceptance audit: AC1 is exercised by tests/test_documentation.py against the complete README workflow and troubleshooting contract. AC2 is exercised against production search_guide_content plus successful and partial orchestrator publication, deterministic no-op writes, and sample inclusion. AC3 validates hourly systemd service/timer and cron examples, persisted full_reconcile_hours behavior, and no-auto-install wording. AC4 regenerates the fixture corpus in a temporary directory and compares every file byte-for-byte while asserting required source/metadata/stale evidence and prohibited internals/secrets. AC5: CPython 3.13.15 ran 194 tests at 100.00%; Ruff check/format, mypy, tox lint+py313, uv lock --check, uv build, git diff --check, and clean wheel installation/help/package-data smoke all passed. AC6 validates the explicit live marker/environment contract and prohibition on mutation without separate authorization. AC7 is satisfied by docs/CAPABILITIES.md: no disposable instance/version was supplied, so it states not live-tested and fixture-only while recording exact REST/GraphQL/group-wiki fields, relationships, coverage, and limitations. All 16 numbered specification scenarios were re-audited in docs/ACCEPTANCE_TEST_MATRIX.md with automated evidence; no additional product defect or missing behavioral scenario was found.

Release metadata follow-up: corrected the scaffold package description to accurately describe selected GitLab repositories, wikis, and work items for offline reference search. The independent repository-wide release gate still passes.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @human
created: 2026-09-20 10:04
---
The human authorized autonomous sequential continuation while all dependencies remain in Review, including a full implementation, acceptance audit, and move of only TASK-001.09 to Review.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Completed the installation/operations/documentation release layer and acceptance verification. Added atomic deterministic destination SEARCH_GUIDE.md publication; a full Python 3.13/uv and gl-groupsync README; schema-free bootstrap/discovered CE configs; non-installing hourly systemd and cron examples; explicit read-only live-test instructions; exact fixture-only capability reporting; and a production-renderer-based, secret-free deterministic sample corpus with repository, project/group wiki, issue/task conversations, metadata, manifest, and stale/quarantine examples. Added documentation/sample freshness tests and a mapping for all 16 numbered specification scenarios. Verification passed on CPython 3.13.15: 194 tests and 100.00% coverage, Ruff check/format, mypy, tox, uv lock --check, uv build, git diff hygiene, and clean wheel install with gl-groupsync --help and default-config package-data inspection. Known limitation: no disposable GitLab instance/version was provided, so API and licensed group-wiki capabilities are explicitly not live-tested and fixture-only. No follow-up task or new ADR was needed; ADR 0001 remains applicable. Human acceptance remains pending in Review.

Release metadata was also corrected to remove the scaffold typo and accurately describe the implemented package.
<!-- SECTION:FINAL_SUMMARY:END -->
