# ADR 0004: Tag-triggered GitHub PyPI Trusted Publishing

- Status: Accepted
- Date: 2026-11-05
- Accepted: 2026-11-06, by explicit human approval with closure of TASK-007.

## Context

The human requested release 0.2.0 and GitHub CI prepared for PyPI publishing.
The package already uses Hatchling, uv and a locked Python 3.13 development
environment, but has no GitHub workflows. The human selected pushed version tags
as the release trigger and approved Trusted Publishing after test/build checks.

## Decision

Use a reusable CI workflow for branch pushes, pull requests and release builds.
Install Git/LFS/SSH prerequisites, enforce consistent project/runtime/installed/
lock versions, run existing coverage/static checks, and build wheel and source
distributions. Validate metadata and independently smoke-test isolated artifact
installations, including the bundled Onacol configuration and installed CLI.
Allowlist source-distribution inputs to the application and package documents.

A separate `release.yml` workflow triggers on pushed `v*` tags and calls CI for
that exact tag. The tag must equal `v` plus the package version. Only a successful
build can hand its tested artifacts to the separate `pypi` publishing job. That
job downloads the artifacts without rebuilding source and publishes through the
PyPA action with OIDC Trusted Publishing and its default attestations.

The publishing job alone receives `id-token: write`. The build/test job receives
read-only repository permissions, and ordinary CI cannot publish. Configure the
PyPI publisher for `calcite/gitlab-groupsync`, workflow `release.yml`, environment
`pypi`, matching the existing project identity. Action references are pinned to
commit SHAs; uv and metadata-validator versions are also pinned.

## Consequences

- A version tag is the explicit publishing event; a GitHub Release page is
  optional and does not initiate another upload.
- Source, runtime, lockfile, installed package and tag inconsistencies fail
  before publishing.
- The artifacts tested are the artifacts uploaded, and publishing credentials
  are separate from source execution and tests.
- The owner must register a normal or pending Trusted Publisher and create the
  matching GitHub environment before the first upload. No persistent PyPI token
  is required.
- Dependency/action pin updates are maintenance work. Local checks validate the
  repository configuration but cannot establish that external publisher setup is
  correct until an actual tagged workflow run succeeds.
- Package version 0.2.0 does not change the independently versioned SQLite schema.

## Alternatives considered

- Publish when a GitHub Release is published: offered to the human, who selected
  pushed version tags instead.
- Store a long-lived PyPI API token in GitHub secrets: rejected in favor of
  Trusted Publishing's job-scoped OIDC identity.
- Rebuild inside the publishing job: rejected because it could upload artifacts
  different from those checked by CI.
- Separate test steps copied into each workflow: rejected in favor of one shared
  reusable workflow so release validation cannot drift from ordinary CI.
