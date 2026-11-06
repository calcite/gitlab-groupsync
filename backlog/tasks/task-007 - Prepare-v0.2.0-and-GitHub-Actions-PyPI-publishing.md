---
id: TASK-007
title: Prepare v0.2.0 and GitHub Actions PyPI publishing
status: Review
assignee:
  - '@opencode'
created_date: '2026-11-05 22:03'
updated_date: '2026-11-05 22:19'
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
The human accepted live GitLab and LFS operation and requested release preparation as v0.2.0: consistent version metadata, an updated changelog, and GitHub CI prepared to publish distributions to PyPI. At the start, the checkout had no GitHub workflows or configured Git remote. The human explicitly selected publishing on pushed version tags, using PyPI Trusted Publishing after tests and package validation pass.

Prepare the repository release assets under the package identity already declared in pyproject.toml: gitlab-groupsync on PyPI and JNevrly/gitlab_groupsync on GitHub. Share CI between branch/PR validation and tagged releases, validate that a tag matches the package/runtime/lock versions, and publish exactly the tested wheel and source artifacts from a separate pypi job. Document the external GitHub environment and PyPI publisher registration needed for the first publication. Actual publisher registration, GitHub execution and public upload depend on owner access; this task prepares and locally verifies the release path.
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
1. Bump pyproject/runtime/lock versions to 0.2.0, expose the installed CLI version, and write the dated changelog. 2. Add a reusable CI test/build workflow and a version-tag release workflow using approved PyPI Trusted Publishing in a separate pypi job. Pin action references and uv, install Git/LFS/SSH prerequisites, enforce metadata/tag consistency, build wheel/sdist, validate distribution metadata and isolated installed behavior, and publish only the tested artifacts. 3. Document exact Trusted Publisher setup for JNevrly/gitlab_groupsync and the release/tag procedure; capture the publishing architecture in ADR 0004. 4. Verify positive and mismatched version/tag behavior, run full coverage/static/workflow/build/install checks, then move TASK-007 to Review with external setup requirements recorded.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Release metadata is 0.2.0 in pyproject.toml, gitlab_groupsync/__init__.py and uv.lock. The lock diff changes only the project version, without dependency upgrades. Added the installed CLI --version option, current release references, and a 2026-11-05 changelog entry covering LFS, diagnostics/hydration fixes, live GitLab 19.5.3/hierarchy evidence and release tooling. Internal SQLite schema stays independently versioned at 1.

Workflow design: .github/workflows/ci.yml runs on branch pushes, PRs, manual dispatch and workflow_call. Ubuntu 24.04 + Python 3.13 + uv 0.12.17 install Git, Git LFS and OpenSSH, then install the locked development environment, check release metadata, run Ruff/mypy/actionlint/100%-coverage tests, build wheel/sdist, validate with Twine 7.0.0, smoke-test isolated installations and upload python-distributions. release.yml runs on pushed v* tags, calls that same CI workflow and publishes the artifact in a separate pypi-environment job with only id-token:write. That job neither checks out nor rebuilds source. Actions are SHA-pinned from verified official references. No PyPI API token is stored or required.

Release verification: 262 tests passed at 100.00% package statement coverage. Ruff lint/format, mypy, actionlint 1.7.12, uv lock --check and git diff --check passed. Source/runtime/installed/lock/changelog checks pass for v0.2.0 and reject mismatched CLI tags, RELEASE_TAG=v0.2.1/vgarbage, and a simulated runtime/source mismatch. Built dist/v0.2.0/gitlab_groupsync-0.2.0-py3-none-any.whl and gitlab_groupsync-0.2.0.tar.gz; strict Twine 7 metadata checks pass on both. Both clean isolated installations pass version/provenance, CLI version/help, bundled default_config.yaml and config-template checks. Archive inspection proves wheel contents are limited to app+installation metadata and sdist contents to app/release inputs plus standard Hatchling metadata/.gitignore; no temp corpus, Backlog or local evidence artifacts are included.

Useful constraints: Twine 6.2 rejects Core Metadata 2.5 emitted by current Hatchling, so pin verified Twine 7.0.0. uv isolated environments use overlays/cache paths outside sys.prefix; verify imported-module provenance against installed distribution metadata instead of requiring a prefix-relative path. Hatchling includes root .gitignore and generated metadata in an otherwise allowlisted sdist.

Documentation: docs/RELEASING.md records exact PyPI publisher fields (owner JNevrly, repository gitlab_groupsync, workflow release.yml, environment pypi), pending-publisher setup for first publication, local checks, and committing/pushing the reviewed release commit before tagging v0.2.0. ADR 0004 records the tag-triggered OIDC/artifact-handoff approach and remains Proposed for human review. PyPI JSON returned 404 for the project during preparation. No Git remote is configured and gh is unavailable, so no remote environment/publisher configuration, GitHub workflow run, tag push or PyPI upload was performed. These owner setup requirements remain documented; no separate follow-up task was created.
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
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Prepared v0.2.0 package/runtime/lock versions, dated changelog and CLI --version. Added shared GitHub CI and the human-selected version-tag PyPI release workflow, with SHA-pinned actions, isolated publishing OIDC permissions, metadata/tag guards, strict build validation, isolated wheel/sdist smoke tests and tested-artifact handoff. Source distributions are restricted to release inputs. Added owner setup/release instructions and Proposed ADR 0004.

Verification: 262 tests, 100.00% package statement coverage; Ruff lint/format, mypy, actionlint, lock validation, diff checks, positive/negative version-tag checks, wheel/sdist builds, strict Twine checks, archive membership checks and both isolated installed-distribution smoke tests all pass.

Known external prerequisites: configure the intended GitHub remote and pypi environment; register the PyPI normal/pending Trusted Publisher for JNevrly/gitlab_groupsync, release.yml, pypi; commit/push reviewed changes and then push v0.2.0 to initiate publishing. GitHub execution/OIDC upload is not live-verified and no publication was performed. No new follow-up task. Ready for human review.
<!-- SECTION:FINAL_SUMMARY:END -->
