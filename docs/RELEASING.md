# Releases And PyPI Publishing

## Release Identity

- Current package version: **0.2.0**.
- Installed command: `gl-groupsync`; `gl-groupsync --version` reports the installed
  distribution version.
- PyPI project: `gitlab-groupsync` (normalized from the metadata name
  `gitlab_groupsync`).
- GitHub repository declared by the project: `JNevrly/gitlab_groupsync`.
- Release tag: `v` followed by the exact package version, initially `v0.2.0`.

Version sources are `pyproject.toml`, `gitlab_groupsync/__init__.py` and the
project entry in `uv.lock`. `scripts/check_release.py` checks these against the
installed metadata, a dated changelog entry, and the release tag when supplied.
Internal SQLite schema version 1 is independent of the package version and does
not change for 0.2.0.

## One-Time Publisher Setup

Create a GitHub Actions environment named **`pypi`** in the repository settings.
Then configure a GitHub Trusted Publisher on PyPI using exactly:

| PyPI field | Value |
| --- | --- |
| Project name (for a pending publisher) | `gitlab-groupsync` |
| Owner | `JNevrly` |
| Repository name | `gitlab_groupsync` |
| Workflow filename | `release.yml` |
| Environment name | `pypi` |

For an existing PyPI project, add the publisher in its Publishing settings. For
a first publication, create a **pending publisher** in the PyPI account's
Publishing settings. The project is created when that publisher successfully
uploads its first distributions. The package was not listed by the PyPI JSON API
when this release preparation was performed.

These fields use the repository URLs already declared in `pyproject.toml`.
If the actual GitHub owner/repository changes, update the publisher identity and
project URLs together. The local checkout currently has no Git remote configured;
connect it to the intended GitHub repository before the first release push.

No `PYPI_TOKEN`, password or other PyPI repository secret is used. PyPI
authenticates the `publish` job through GitHub OIDC. Only that job has
`id-token: write`; the build/test job has read-only repository permissions. See
[ADR 0004](adr/0004-github-pypi-trusted-publishing.md).

## What CI Runs

`.github/workflows/ci.yml` runs on branch pushes, pull requests, manual dispatch,
and calls from the release workflow. It uses Ubuntu 24.04, Python 3.13 and uv
0.12.17, installs Git, Git LFS and OpenSSH, and then:

1. Installs the development environment with `uv sync --locked --group dev`.
2. Checks metadata/changelog consistency and any supplied release tag.
3. Runs Ruff lint/format checks, mypy, actionlint and pytest at the configured
   100% coverage threshold. Tests use fixtures and local Git/LFS servers; no
   GitLab token or live server is needed.
4. Builds a source distribution, then a wheel from it.
5. Runs strict Twine 7.0.0 metadata validation.
6. Installs each artifact into an isolated environment and checks package/runtime
   versions, CLI version/help, bundled configuration and template generation.
7. Uploads the tested distributions as the `python-distributions` artifact.

The source distribution includes only the application package and its bundled
configuration, `pyproject.toml`, README, changelog and license. Hatchling also
retains the root `.gitignore` and generated package metadata. Workspace exports,
internal Backlog records and local validation artifacts are outside that include
list. The wheel contains the application package and installation metadata.

GitHub actions are pinned to commit SHAs. Update those pins deliberately when
upgrading actions, along with the uv/Twine pins when needed. Twine 7 is used
because current build tooling emits Core Metadata 2.5, which Twine 6.2 rejects.

## Prepare A Version

1. Update `pyproject.toml` and `gitlab_groupsync/__init__.py`.
2. Add a dated changelog entry and update the current release in README and this
   guide. Preserve historical changelog versions.
3. Run `uv lock` to refresh the project's version in `uv.lock`.
4. Run the local checks below with the intended tag/version.
5. Commit the reviewed release changes, including the workflows and lockfile,
   and push that commit to GitHub before tagging it.

Local checks for this release, from the repository root:

```bash
uv sync --locked --group dev
uv run --frozen python scripts/check_release.py --tag v0.2.0
uv run --frozen gl-groupsync --version
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy gitlab_groupsync
uv run --frozen pytest --cov=gitlab_groupsync --cov-report=term-missing tests/
uvx --from actionlint-py==1.7.12.25 actionlint
uv build --out-dir dist/v0.2.0
uvx --from twine==7.0.0 twine check --strict dist/v0.2.0/*
for distribution in dist/v0.2.0/*.whl dist/v0.2.0/*.tar.gz; do
  uv run --isolated --no-project --with "$distribution" \
    python scripts/smoke_distribution.py 0.2.0
done
```

`scripts/check_release.py --tag v0.2.1` must fail while the package is 0.2.0. The
release workflow supplies the actual tag through `RELEASE_TAG`, so a mismatched
tag cannot reach the publishing job. Ordinary branch/PR CI never publishes.

## Publish v0.2.0

After the publisher setup and release commit are on GitHub, tag that commit:

```bash
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

`.github/workflows/release.yml` triggers on pushed `v*` tags. It calls the same CI
workflow for that tag, then a separate `pypi` publishing job downloads the tested
artifact from that workflow run. The publishing job does not check out or rebuild
source; `pypa/gh-action-pypi-publish` publishes those distributions and creates its
default Trusted Publishing attestations.

Watch the **Publish to PyPI** workflow, then check
<https://pypi.org/project/gitlab-groupsync/0.2.0/>. A GitHub Release page can be
created separately for release notes; it is not the publishing trigger.

This preparation performs local builds and workflow validation. Creating the
GitHub environment, registering the PyPI publisher, pushing the tag and observing
the actual OIDC upload require the repository/package owner's configured access.
