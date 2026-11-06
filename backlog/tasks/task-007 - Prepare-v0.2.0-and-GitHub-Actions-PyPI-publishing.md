---
id: TASK-007
title: Prepare v0.2.0 and GitHub Actions PyPI publishing
status: Done
assignee:
  - '@opencode'
created_date: '2026-11-05 22:03'
updated_date: '2026-11-06 09:34'
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
  - 'https://github.com/calcite/gitlab-groupsync/actions/runs/42193622682'
  - 'https://github.com/calcite/gitlab-groupsync/actions/runs/42193630840'
  - 'https://pypi.org/project/gitlab-groupsync/0.2.0/'
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
Current release state: v0.2.0 has been published successfully. Version metadata, runtime, lockfile, changelog and installed CLI identify 0.2.0. GitHub repository/publisher identity is calcite/gitlab-groupsync, workflow release.yml, environment pypi. The owner configured the external setup and pushed the tag; public workflow/PyPI evidence now supersedes earlier notes saying the corrected commit, OIDC upload or publisher setup were unverified.

Verified GitHub evidence on 2026-11-06: branch CI run 42193622682 completed successfully for main commit 5a541fa67db1230da06369e5df38b842409693e0. Release workflow run 42193630840 completed successfully for v0.2.0 at that same commit. Its build job completed every required step, including locked environment, tag/metadata checks, static/workflow checks, required coverage, distributions, strict metadata checks, both isolated installation smoke checks and artifact upload. Its separate publishing job successfully downloaded the tested artifact and completed Publish with PyPI Trusted Publishing. URLs are attached as references. gh is unavailable, so this read-only verification used the public GitHub API.

Verified PyPI evidence: https://pypi.org/pypi/gitlab-groupsync/0.2.0/json lists version 0.2.0, unyanked, with both artifacts. Wheel gitlab_groupsync-0.2.0-py3-none-any.whl uploaded 2026-11-06T09:16:29.040512Z, SHA256 8464479b5cb3fb630fcb86d3f4ee0bb0dc3950b12cd66056216a4faf1218976e. Source gitlab_groupsync-0.2.0.tar.gz uploaded 2026-11-06T09:16:30.667808Z, SHA256 f02b7aa7ae479efc243ef89d3a3579ecfbb5260a9bc98e7d7022e3d85cbeeef8. Project URLs point to the configured calcite repository. An isolated install directly from the public index passed: uv run --isolated --no-project --with gitlab-groupsync==0.2.0 python scripts/smoke_distribution.py 0.2.0. That verifies installed metadata/runtime version, module provenance, CLI version/help, bundled default configuration and template generation. docs/RELEASING.md now records this successful publication and links.

CI regression history: the setup/partial-exit test originally used /srv/gitlab-reference. Root sandbox runs masked the unwritable destination on GitHub, where lock creation precedes inventory validation. Fixed the test to pass a pytest tmp_path destination, preserving the intended real missing-inventory exit 2 and injected partial exit 1 without production changes, sudo or coverage relaxation. The full suite passed under UID/GID 1000 with cleared supplementary groups: 261 passed, 1 expected root-only ownership-test skip, 100.00% coverage. Ruff lint/format, mypy, documentation tests, version/build/Twine/diff checks and isolated wheel/sdist installs also passed locally; remote CI has now passed too.

Release tooling uses shared ci.yml and tag-triggered release.yml, job-isolated publishing permissions, SHA-pinned actions, uv 0.12.17, Twine 7.0.0 and tested-artifact transfer without rebuilding. Twine 6.2 cannot read current Core Metadata 2.5; uv overlay/cache installs require module provenance checking via installed metadata rather than sys.prefix containment; Hatchling includes .gitignore/generated metadata in the allowlisted sdist. These remain useful maintenance constraints. ADR 0004 is still Proposed pending human review. No remaining release/publishing failure or new follow-up task is identified. TASK-007 remains in Review awaiting explicit human acceptance.

Human acceptance checkpoint, 2026-11-06: explicitly authorized task closure and acceptance of ADR 0004. Updated docs/adr/0004-github-pypi-trusted-publishing.md to Accepted with the acceptance date. This supersedes all earlier references to Proposed ADR status or pending human acceptance. Current state: release and publishing verified, ADR accepted, task closed as Done. No remaining work or follow-up task.
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

author: Human
created: 2026-11-06 09:24
---
Reported that the CI build has completed.
---

author: Human
created: 2026-11-06 09:34
---
Explicitly authorized closing TASK-007 and marking ADR 0004 as Accepted.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Released and verified v0.2.0 with consistent package/runtime/lock/CLI versions, updated changelog, reusable GitHub CI and tag-triggered PyPI Trusted Publishing. Publishing uses isolated OIDC permissions and the exact tested wheel/sdist artifacts. Fixed the non-root CI test destination regression and aligned publisher setup with calcite/gitlab-groupsync.

Verification: successful branch CI run 42193622682 and tagged release/publish run 42193630840 at commit 5a541fa67db1230da06369e5df38b842409693e0. PyPI independently lists both unyanked 0.2.0 distributions, and an isolated install from the public index passed the smoke test. Local non-root verification passed 261 tests with 1 expected skip and 100% package coverage, plus static/workflow checks, metadata/tag guards, builds, Twine and distribution installation checks. Release evidence is recorded in docs/RELEASING.md.

The human explicitly accepted closure and ADR 0004 on 2026-11-06. ADR 0004 is now Accepted, TASK-007 is Done, and no implementation, publication or acceptance work remains. No follow-up task was created.
<!-- SECTION:FINAL_SUMMARY:END -->
