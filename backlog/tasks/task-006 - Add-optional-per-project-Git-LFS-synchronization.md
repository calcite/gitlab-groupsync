---
id: TASK-006
title: Add optional per-project Git LFS synchronization
status: Done
assignee:
  - '@opencode'
created_date: '2026-11-04 14:27'
updated_date: '2026-11-05 10:29'
labels: []
dependencies: []
references:
  - gitlab_groupsync/discovery.py
  - gitlab_groupsync/git_sync.py
  - gitlab_groupsync/default_config.yaml
  - docs/adr/0001-generated-stable-id-selection-catalog.md
  - 'https://docs.gitlab.com/api/projects/'
  - gitlab_groupsync/config.py
  - gitlab_groupsync/orchestrator.py
  - gitlab_groupsync/diagnostics.py
  - tests/test_lfs.py
  - docs/adr/0003-optional-project-lfs.md
type: feature
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The reference corpus currently leaves Git LFS pointer files in project checkouts, so selected repositories can lack the actual files needed for offline reference. The human requested optional LFS support, default off, with the option exposed only for projects containing LFS objects, and confirmed that downloads should cover only the current default-branch checkout. Extend the existing generated stable-ID selection catalog and repository synchronization workflow. Discovery must distinguish confirmed object presence, confirmed absence, and unavailable evidence; merely enabling LFS on GitLab is not proof that objects exist. Preserve compatibility with existing configurations and the existing one-way, noninteractive, credential-safe synchronization contract. LFS hydration is part of the project repository resource and its success reporting. Project/group wikis and downloading all refs or historical LFS objects are outside this feature scope.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Discovery generates an optional per-project lfs:false field only where stored LFS objects are confirmed; projects confirmed to have no LFS objects have no lfs field. The GitLab lfs_enabled setting alone does not establish object presence.
- [x] #2 Unavailable LFS statistics are reported as unknown rather than zero: new options are omitted, existing LFS selections are preserved, and actual discovery request failures leave the persisted YAML unchanged.
- [x] #3 Discovery preserves existing LFS selections by stable project ID across renames; newly eligible or reappearing projects default to lfs:false.
- [x] #4 Existing configurations without lfs remain valid and imply false. lfs accepts only booleans, and lfs:true requires repository:true.
- [x] #5 With LFS disabled, synchronization performs no LFS payload downloads. Turning it off stops further downloads without deleting cached LFS objects.
- [x] #6 With LFS enabled, actual file content for the exact current default-branch commit is materialized through explicit LFS fetch/checkout with automatic smudging disabled. Other refs and historical versions are not downloaded.
- [x] #7 Enabling LFS hydrates an existing pointer-only checkout even when its Git revision has not changed. Repeated and incremental synchronization handles hydrated files cleanly without falsely reporting local conflicts or overwriting local tracked or untracked changes.
- [x] #8 New repositories are published from staging only after required LFS hydration succeeds, and repository success is recorded only after the required Git and LFS operations succeed. LFS failures remain isolated to that repository and can be retried.
- [x] #9 LFS operations retain existing noninteractive authentication, custom-CA support, credential-free persisted remotes, secret redaction, scoped repository trust, and configured timeout handling.
- [x] #10 Doctor checks git-lfs availability only when LFS synchronization is selected. The development container provides git-lfs for real integration verification.
- [x] #11 Meaningful discovery/configuration and real LFS integration tests cover availability and unknown evidence, selection/default behavior, compatibility, initial hydration, unchanged-revision enablement, incremental updates, local-edit preservation, missing objects, and retries. Required coverage, lint, formatting, and type checks pass.
- [x] #12 README, specification, capability and search guidance, and configuration examples describe the opt-in behavior and current-checkout scope. Record the lasting catalog/detection contract in an ADR linked from the task.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extend discovery with optional per-project LFS statistics probes for the discover command only, report unknown evidence, and conditionally merge lfs selections; keep existing config files valid. 2. Add explicit exact-commit LFS fetch and hydration, scoped filter setup, clean-worktree protection, staged publication, and repository error isolation using existing Git controls. 3. Add selected-only doctor checks and install git-lfs in the devcontainer. 4. Exercise real local Git/LFS repositories and API/config/diagnostic contracts, including unchanged-commit enablement, missing objects/retry, local edits, and disabling downloads. 5. Update README/specification/capability/search guidance/examples and ADR 0003. 6. Run full coverage, Ruff, mypy, lock/build/diff checks, then synchronize task criteria and summary and move to Review.

7. Record the human-confirmed live run and manifest evidence, update compatibility documentation to distinguish operational validation from version-specific contract testing, then close under explicit human acceptance.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementation: per-project optional lfs selection, default false, conditionally generated from project LFS statistics; unknown evidence preserves existing intent. Existing configurations remain valid, and true requires repository:true. Explicit exact-commit LFS fetching occurs before changing an existing worktree, and hydration also runs at unchanged revisions. Repository-local skip-smudge filters are installed without hooks. Post-checkout verification rejects unresolved pointers because git lfs checkout can exit zero after skipping missing objects. Disabling downloads retains caches and unchanged hydrated files; retaining git-lfs allows Git to recognize those files as clean.

Automated verification from implementation: 261 tests pass with 100.00% package statement coverage, including real git-lfs 3.6.1 repositories and a local HTTP batch/transfer fixture for askpass authentication, redaction and retry. Ruff lint/format, mypy, uv lock --check, uv build, and git diff --check pass. git-lfs was installed in the sandbox and added to the devcontainer; Docker was unavailable for a clean image rebuild.

Human acceptance on 2026-11-05 supersedes the earlier fixture-only live-status note: the human explicitly confirmed working LFS fetching and the entire system against https://gitext.alps.cz (zero-iot, root 1189), and authorized related task closure. Inspected temp/zero-iot/manifest.json run 5, finished 2026-11-05T09:07:23+00:00: 142 resources, 92 ok (38 repositories, 9 project wikis, 45 work-item exports), 27 empty, 21 disabled, 2 local_conflict, zero error/unavailable. Project 1262 (0mt-certification) now has an ok master checkout at revision 37219f3c4a2657f9dba7a163f148d7dbc3840363. Partial exit 1 is solely due to preserved local changes in project 830 (aws-lambdas) and 1373 (0mt-eol-deployment), not a remaining LFS failure. No corpus content was modified during inspection.

Updated README, capability report, live-testing notes, acceptance-matrix context and ADR 0003 to record the limited live evidence accurately; ADR 0003 is now Accepted under human feature acceptance. Documentation checks: uv run pytest -q tests/test_documentation.py (4 passed) and git diff --check pass. Exact GitLab version/edition and the targeted hierarchy contract remain open in TASK-004. Group-wiki selections were disabled, so no licensed group-wiki live support is claimed. Statistics edge cases remain fixture-tested. No additional implementation follow-up was created.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-11-04 14:27
---
Requested optional Git LFS support, default off, offered only for projects containing LFS objects. Selected current-checkout scope rather than all refs/history. After clarification of automatic smudging and the proposed explicit download/materialization approach, agreed and requested creation of this task.
---

author: Human
created: 2026-11-04 14:33
---
Authorized implementation of TASK-006.
---

author: Agent
created: 2026-11-04 14:49
---
Implementation and required automated checks are complete. Ready for review, including Proposed ADR 0003. GitLab server behavior is fixture-only; the devcontainer recipe includes git-lfs and local installation/integration tests passed, but Docker is unavailable for an image rebuild.
---

author: Human
created: 2026-11-05 10:27
---
Confirmed that LFS fetching works and that the entire system works when connected to the GitLab instance. Requested closure of related tasks, or a prompt for any outstanding confirmation needed for closure.
---

author: Agent
created: 2026-11-05 10:29
---
Human acceptance recorded and manifest inspected. Closed TASK-006 as Done under the explicit instruction to close accepted work. The latest partial outcome reflects only two protected local-change conflicts; LFS repository synchronization is successful. TASK-004 remains open for its specific version/query-response requirements.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented optional per-project Git LFS synchronization, default off and offered only on positive stored-object evidence. Downloads and hydrates only the current default-branch commit, supports unchanged-revision enablement, protects local edits, verifies materialization, and publishes or records success only after required LFS completion. Added selected-only diagnostics, devcontainer dependency, documentation/examples, real LFS/HTTP tests, and ADR 0003 (now Accepted; extends ADR 0001 without state-schema changes).

Verification: implementation suite 261 passed with 100.00% statement coverage; Ruff lint/format, mypy, lock validation, wheel/sdist build, and diff checks passed. Closure documentation checks: 4 passed. Human explicitly confirmed live LFS fetching and overall synchronization and authorized closure on 2026-11-05. Manifest run 5 corroborates 92 ok resources and no error/unavailable states; its two local conflicts correctly preserve user changes. Project 1262 now has a successful repository checkout.

Known validation limits: exact GitLab version/edition remains unrecorded; TASK-004 retains the targeted hierarchy-response/version verification; disabled licensed group wikis are not live-verified. Docker image rebuild was not exercised. No new follow-up tasks. Accepted by the human and closed.
<!-- SECTION:FINAL_SUMMARY:END -->
