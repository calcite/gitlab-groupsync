# History

## 0.2.0 (2026-11-05)

* Add optional per-project Git LFS downloads for the current default-branch
  checkout, offered during discovery only for projects with stored LFS objects
  and disabled by default.
* Materialize LFS files on unchanged revisions, verify hydration before staged
  publication, preserve local edits, and retain caches when downloads are disabled.
* Add selected-only Git LFS diagnostics and include Git LFS in the development
  container. Preserve meaningful Git operation names in failures with scoped
  configuration options.
* Record human-confirmed live synchronization and parent/child hierarchy query
  validation against GitLab 19.5.3, with captured-response regression coverage.
* Add `gl-groupsync --version`, GitHub CI and tag-triggered PyPI Trusted
  Publishing, with version consistency checks and isolated wheel/sdist smoke tests.
* Limit source distributions to application source, bundled configuration,
  package metadata, README, changelog and license.

## 0.1.0 (2026-09-20)

* Add the Python 3.13 `gl-groupsync` CLI with Onacol YAML configuration,
  discovery and stable-ID selections, durable status/doctor workflows, and safe
  one-way synchronization of repositories, wikis, issues, tasks, and discussions.
* Add reconciliation, quarantine, recovery, path/credential safety, generated
  search guidance, operational examples, fixture-only capability documentation,
  and a deterministic sample corpus.
