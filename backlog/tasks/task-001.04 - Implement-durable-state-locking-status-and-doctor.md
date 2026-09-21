---
id: TASK-001.04
title: 'Implement durable state, locking, status, and doctor'
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 07:46'
updated_date: '2026-09-21 05:52'
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
- [x] #1 A versioned SQLite database persists instance and root identity, objects, resources, runs, checkpoints, retry queues, and recovery records transactionally
- [x] #2 A destination cannot be reused for a different GitLab instance or root group without an explicit safe workflow
- [x] #3 An OS-backed exclusive lock yields exit code 3 for contention and process death does not require stale lock cleanup
- [x] #4 status is local and read-only, supports human and JSON output, and reports last-run health, freshness, retained content, and last-observed inventory drift
- [x] #5 doctor validates configuration, Git, authentication, TLS and custom CA behavior, root visibility, server metadata, and requested capabilities without publishing corpus content
- [x] #6 Manifest and resource metadata writes are atomic and tests cover identity mismatch, locking, interrupted runs, drift reporting, and diagnostic failures
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a stdlib SQLite state module with transactional versioned migrations, normalized instance/root binding, managed-directory initialization, immutable state models, serialized transaction APIs for objects/resources/runs/checkpoints/retries/drift/recovery, interrupted-run recovery, and read-only status snapshots.
2. Add Linux flock destination locking and atomic JSON publication helpers for manifest/resource metadata, including safe cleanup/error behavior and manifest projection from SQLite without making JSON authoritative.
3. Add diagnostics that render local human/JSON status without credentials or network access and run doctor checks for Git, token-authenticated root visibility, complete discovery, optional server metadata/version, selected API capabilities, and TLS/custom CA behavior using injectable adapters.
4. Wire status and doctor to real workflows and sync to the real lock boundary while retaining an explicit non-exporting placeholder; map configuration/setup to exit 2, doctor partial failures to 1, and lock contention to 3.
5. Add focused state, locking, atomic-write, status, doctor, and CLI tests; preserve later repository/wiki/work-item exporter scope. Run 100% coverage, Ruff check/format, mypy, diff check, uv lock check, and build, then finalize TASK-001.04 only.

6. Add transport-aware local diagnostics so an SSH configuration reports a missing ssh executable before synchronization, while HTTPS requires no SSH client.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: TASK-001.01-.03 are intentionally in Review under human-authorized sequential continuation. Existing code provides validated token-free config references, credential loading, immutable inventory/drift models, complete discovery, and a redirect-resistant TLS-aware GitLab client. status/doctor/sync are placeholders. This task will add state/diagnostics around those interfaces without implementing any content exporter; status will use SQLite read-only mode plus a kernel-lock probe and will never resolve credentials.

Implementation checkpoint: added `gitlab_groupsync/state.py` with schema version 1 and transactional tables for identity, objects, resources, runs, checkpoints, retries, drift snapshots, and recovery operations. Destination initialization creates only the managed layout, binds normalized instance URL plus root ID, and rejects mismatches. SQLite access uses an RLock and immediate transactions for future worker serialization. Linux `flock` locking is nonblocking and status probes it without treating the lock file as liveness. Atomic JSON publication exposes manifest identity/run state/drift/freshness/coverage and resource sidecars.
Diagnostics checkpoint: status is implemented as a credential-free, network-free SQLite read-only projection with human/JSON rendering, uninitialized/current/interrupted run distinction, resource freshness/counts, retained content, and latest drift. Doctor validates Git, authenticated root visibility, TLS/custom CA, optional metadata/version, complete discovery, and selected group-wiki/project-wiki/work-item capabilities using read-only probes; missing metadata is informational, operational failures produce exit 1, configuration/token setup remains exit 2. Sync remains an explicit non-exporting placeholder but now enforces the destination lock and maps contention to exit 3. Repository/wiki/work-item exporters remain untouched.
Test checkpoint: 80 tests are present and the full suite reached 100% package coverage before the final release-check pass. Tests include migration rollback, all durable models, normalized identity mismatch, threaded serialization, interruption, local-only status, drift/retained reporting, context and child-process lock release, doctor success/auth/TLS/Git/capability/metadata-absence failures, CLI exits, and atomic JSON failure preservation.

Final verification: `uv run pytest --cov=gitlab_groupsync --cov-report=term-missing tests/` passed 80 tests at 100.00% coverage. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy gitlab_groupsync`, `git diff --check`, `uv lock --check`, and `uv build` all passed. AC evidence: state tests inspect schema version/tables and transaction rollback/all model APIs (AC1); normalized instance/root mismatch tests and unrelated-file preservation prove binding safety (AC2); contention, CLI exit 3, context release, and child `os._exit` release prove flock behavior (AC3); local-only CLI tests fail if token/network adapters are touched and verify human/JSON interruption/freshness/count/retained/drift output (AC4); fake doctor tests cover healthy, Git missing/version failure, 401/403 auth, TLS/custom CA, root/discovery, metadata fallback/absence, and selected capability failures without writes (AC5); atomic replacement failure preservation plus manifest/resource metadata, interruption, drift and diagnostics tests prove AC6.

Live review finding: doctor reported Git healthy for git_transport:ssh even though the devcontainer lacked the separate ssh executable, causing every repository fetch to fail only during sync.

Review correction complete: doctor now runs ssh -V only when git_transport is ssh and reports a dedicated failed check when the executable is unavailable; HTTPS does not invoke or require SSH. Focused diagnostics tests and the full 234-test suite pass at 100% coverage.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @opencode
created: 2026-09-20 08:22
---
The human explicitly authorized sequential continuation while dependencies remain in Review; this dependency state is intentional.
---

author: Agent
created: 2026-09-20 14:36
---
Agent: The live failure shows that checking only git --version is insufficient for the selected SSH transport. Doctor should perform a local ssh executable/version check only when SSH is configured.
---

author: Agent
created: 2026-09-20 14:41
---
Ready for human review after the live-test correction. The credentialed live doctor could not be rerun because GITLAB_TOKEN is not available in the agent shell.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented versioned stdlib SQLite destination state with transactional migration and focused serialized APIs for identity, discovered objects/resources, runs, checkpoints, retries, drift snapshots, and relocation/publication recovery. Added managed-directory initialization with normalized instance/root binding and safe mismatch rejection; Linux nonblocking `fcntl.flock` locking with exit 3; atomic manifest/resource JSON publication; local read-only human/JSON status; and read-only doctor checks for Git, authentication/root visibility, TLS/custom CA, server metadata/version, complete discovery, and selected API capabilities. Sync deliberately remains a non-exporting placeholder but enforces the lock; later repository/wiki/work-item exporters were not implemented.

Verification: 80 tests pass at 100% coverage, including transaction rollback, migration/schema tables, identity mismatch, serialized threaded writes, child-process lock death/release, interrupted runs, local-only status, drift/retained reporting, all requested doctor failure modes, and atomic write failures. Ruff check and format check, mypy, `git diff --check`, `uv lock --check`, and `uv build` pass. Known limitations: content synchronization remains assigned to TASK-001.05-.07; no new blocker, follow-up task, or ADR was required. Architectural reference remains `docs/adr/0001-generated-stable-id-selection-catalog.md`.

Live-review correction: added a transport-aware SSH prerequisite check to doctor. Missing SSH is now reported before synchronization only for SSH configurations, while HTTPS remains independent. Verified by focused tests plus 234 full-suite tests at 100% coverage; Ruff, format, mypy, diff, lock, and build checks pass.
<!-- SECTION:FINAL_SUMMARY:END -->
