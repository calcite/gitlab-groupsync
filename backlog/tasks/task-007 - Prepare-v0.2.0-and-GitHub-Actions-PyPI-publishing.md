---
id: TASK-007
title: Prepare v0.2.0 and GitHub Actions PyPI publishing
status: Review
assignee:
  - '@opencode'
created_date: '2026-11-05 22:03'
updated_date: '2026-11-06 08:38'
labels: []
dependencies: []
references:
  - pyproject.toml
  - CHANGELOG.md
  - README.md
  - .github/workflows/ci.yml
  - .github/workflows/release.yml
  - scripts/check_release.py
  - scripts/smoke_distribution.py
  - docs/RELEASING.md
  - docs/adr/0004-github-pypi-trusted-publishing.md
priority: high
type: chore
ordinal: 23000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The human accepted live GitLab and LFS operation and requested release preparation as v0.2.0: consistent version metadata, an updated changelog, and GitHub CI prepared to publish distributions to PyPI. At the start, the checkout had no GitHub workflows or configured Git remote. The human selected publishing on pushed version tags, using PyPI Trusted Publishing after tests and package validation pass.

The current project URLs and configured origin identify calcite/gitlab-groupsync on GitHub; the PyPI package identity is gitlab-groupsync. Share CI between branch/PR validation and tagged releases, validate the tag against package/runtime/lock versions, and publish exactly the tested wheel and source artifacts from a separate pypi job. Document the exact external environment/publisher fields. Release checks must work for an unprivileged GitHub runner: tests that exercise sync setup use pytest-owned writable destinations, not the production /srv default. Actual PyPI registration and publication depend on owner access; this task prepares and locally verifies the release path.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Package metadata, runtime version and uv lockfile consistently identify version 0.2.0; the installed CLI reports the version.
- [x] #2 The changelog has a dated v0.2.0 entry covering optional LFS, relevant fixes and human-confirmed live GitLab hierarchy/synchronization evidence, preserving historical entries.
- [x] #3 GitHub CI installs Python and required system Git/LFS dependencies, uses the locked development environment, and runs the required tests, coverage, lint and typing checks on pull requests and pushes.
- [x] #4 The release workflow validates the release identifier against package/runtime/lock versions, builds wheel and sdist, checks their metadata and clean-installed CLI/package data, and passes exactly the tested artifacts to publishing.
- [x] #5 PyPI publishing uses the approved event trigger and Trusted Publishing with publishing permissions isolated to the publishing job; ordinary CI does not publish.
- [x] #6 Documentation specifies the exact PyPI publisher identity, GitHub environment and release procedure, and records the long-lived publishing approach in an ADR.
- [x] #7 Local release checks and workflow validation pass, and any unavailable external setup or live publishing verification is recorded honestly.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Keep package/runtime/lock versions at 0.2.0, expose the CLI version and maintain the dated changelog. 2. Use shared CI and a tag-triggered release workflow with separate PyPI Trusted Publishing permissions, metadata/tag guards and tested-artifact transfer. 3. Keep release instructions and ADR 0004 aligned with the configured calcite/gitlab-groupsync origin and project URLs. 4. Correct the reported setup/partial-exit test to use tmp_path rather than /srv/gitlab-reference; verify its intended exit-2 and exit-1 branches without privileged filesystem access. 5. Run the full required-coverage suite as UID 1000, plus static/documentation/version/build/metadata/isolated-install checks, then return to Review for a fresh GitHub run on the corrected commit.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Release preparation: package/runtime/lock versions are 0.2.0, CLI --version is implemented, and the dated changelog describes LFS, live GitLab 19.5.3/hierarchy validation and publishing. ci.yml runs locked tests/static/actionlint/build/metadata/isolated-install checks; release.yml handles v* tags and publishes the tested artifact through the pypi environment with job-scoped id-token:write. uv 0.12.17, Twine 7.0.0 and SHA-pinned actions are used. Prior root-only sandbox verification passed 262 tests at 100% coverage, version/tag rejection cases, actionlint, archive membership checks and isolated wheel/sdist installation.

GitHub regression reported 2026-11-06: the command uv run --frozen pytest --cov=gitlab_groupsync --cov-report=term-missing tests/ failed in test_sync_setup_and_partial_exit_codes. The test used the default /srv/gitlab-reference destination; run_sync acquires a destination lock before rejecting missing inventory. Root could create this lock locally, but an unprivileged GitHub runner could not, so the expected missing-inventory exit-2 branch never ran and subsequent partial-exit assertions were skipped, reducing coverage to 99.92%. Corrected that existing test to pass --storage--destination pointing to tmp_path/reference for both invocations. It still exercises the real missing-inventory error and the injected partial result. No production behavior, coverage threshold, CI user privileges or skip rules were changed.

Non-root verification: used setpriv with real/effective UID/GID 1000 and cleared supplementary groups, a newly created UID-1000-owned scratch HOME/TMPDIR, an external COVERAGE_FILE, disabled pytest cache/bytecode writes, and the locked .venv Python. Full tests ran with --cov=gitlab_groupsync --cov-config=pyproject.toml --cov-report=term-missing --cov-fail-under=100 tests/. Result: 261 passed, 1 expected root-only ownership-test skip, 100.00% package statement coverage, including all CLI lines. The focused failing test also passes. Ruff lint/format, mypy, 4 documentation tests and git diff --check pass. Version check v0.2.0 passes; rebuilt wheel/sdist both pass strict Twine validation and isolated installed-distribution smoke tests.

Repository identity: origin now points to git@github.com:calcite/gitlab-groupsync.git and pyproject.toml URLs already match. Updated README, docs/RELEASING.md and ADR 0004 to use owner calcite and repository gitlab-groupsync, replacing scaffold-derived JNevrly/gitlab_groupsync instructions. Current PyPI publisher fields: project gitlab-groupsync, owner calcite, repository gitlab-groupsync, workflow release.yml, environment pypi. No publisher registration or configuration was changed remotely.

Known constraints: Twine 6.2 rejects current Core Metadata 2.5, hence Twine 7; uv isolated package paths use overlays/cache locations, so smoke provenance checks installed metadata rather than sys.prefix containment; Hatchling includes .gitignore/generated metadata in the allowlisted sdist. ADR 0004 remains Proposed. The corrected commit has not yet run on GitHub; push it for a fresh CI run. Actual OIDC upload and external publisher/environment setup remain owner-managed. No additional task or ADR was created.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-11-05 22:07
---
Selected publishing on pushed version tags (for example v0.2.0), using PyPI Trusted Publishing after tests and package validation pass.
---

author: Agent
created: 2026-11-05 22:19
---
Release preparation and local verification are complete; TASK-007 is ready for review. See docs/RELEASING.md for the exact one-time PyPI/GitHub configuration and tag procedure. The workflows have not been run on GitHub and no package has been published from this sandbox.
---

author: Human
created: 2026-11-06 08:31
---
Reported GitHub CI failure in Test with required coverage: test_sync_setup_and_partial_exit_codes received an uncaught StateError(could not safely create destination lock) instead of exit 2. The CI run finished with 1 failure, 260 passed, 1 root-only skip, and 99.92% coverage (CLI lines 151 and 153 not reached).
---

author: Agent
created: 2026-11-06 08:38
---
Corrected the test destination and reproduced the full suite under UID 1000 with 261 passed, 1 expected root-only skip and 100% coverage. Also aligned publisher docs with the now-configured calcite/gitlab-groupsync origin. Returned to Review; push the corrected commit to trigger a fresh GitHub run.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Prepared v0.2.0 versioning/changelog/CLI version and shared GitHub test/build plus tag-triggered PyPI Trusted Publishing, with metadata/tag guards, isolated publishing permissions and tested-artifact handoff. Release instructions and Proposed ADR 0004 now match the configured calcite/gitlab-groupsync repository.

Fixed the reported GitHub CI regression by giving test_sync_setup_and_partial_exit_codes a pytest-owned temporary destination instead of the production /srv default. Verified the entire suite as unprivileged UID 1000: 261 passed, 1 expected root-only skip, 100.00% package statement coverage. Ruff lint/format, mypy, documentation tests, version checks and diff checks pass; rebuilt wheel/sdist pass strict Twine and isolated installation checks. Coverage was not relaxed and tests do not need sudo.

Ready for review and a fresh GitHub run after committing/pushing the fix. The corrected commit has not been tested on GitHub yet and no remote publishing setup or PyPI upload was performed by the agent. Verify Trusted Publisher fields for owner calcite, repository gitlab-groupsync, release.yml, environment pypi before publication. No new follow-up task.
<!-- SECTION:FINAL_SUMMARY:END -->
