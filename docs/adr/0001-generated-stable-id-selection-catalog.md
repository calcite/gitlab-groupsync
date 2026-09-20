# ADR 0001: Generated stable-ID selection catalog

- Status: Accepted
- Date: 2026-09-20

## Context

The synchronizer must discover every visible group and owned project below a configured GitLab root while allowing users to opt into repositories, project wikis, work items, and individual group wikis. GitLab paths can change and discovery can fail partway through pagination. A separate generated inventory file would split operational settings from selections and create ambiguity about which file is authoritative.

## Decision

Store a generated `inventory` catalog in the same user YAML file as the hand-maintained configuration. `gl-groupsync discover --config <path>` is the only workflow that rewrites it.

Catalog entries use GitLab global IDs as identity and paths as mutable display metadata. Project entries have independent `repository`, `wiki`, and `work_items` flags; root and descendant group entries each have an independent `wiki` flag. Discovery preserves existing flags by object kind and global ID, updates mutable paths, defaults all selections for newly discovered or reappearing objects to disabled, and removes absent entries only after a complete authoritative traversal.

Discovery builds the full deterministic result before writing it. It writes a temporary file in the same directory and atomically replaces the configured YAML only after all pages succeed. Partial discovery leaves the existing file unchanged. A changed root-group ID requires explicit replacement.

Normal synchronization compares live inventory with the catalog but does not rewrite configuration. It reports added, absent, renamed, and path-reused objects and directs the user to rerun discovery. Drift warnings alone are non-blocking and do not change a successful exit code.

## Consequences

- Selections survive group and project renames because mutable paths are not identity.
- Newly visible resources cannot silently expand the searchable corpus.
- One reviewed file captures connection settings and synchronization intent, and atomic replacement prevents mixed old/new catalogs.
- Discovery must preserve hand-edited YAML settings and avoid serializing resolved secrets, environment overrides, or CLI overrides.
- Users must rerun discovery and review disabled additions to adopt inventory changes; normal sync deliberately does not auto-enroll them.
- Objects removed by a completed refresh lose their catalog selection. If they later reappear they default to disabled, although separately persisted corpus state may still support restoration by ID.
- Same-file generation creates merge noise and requires careful YAML rewriting, but avoids dual-file precedence and consistency problems.

## Alternatives considered

- Select resources by path: rejected because renames would lose selections and path reuse could apply intent to the wrong object.
- Enable every newly discovered project: rejected because discovery would silently broaden scope, storage use, and potentially confidential content collection.
- Keep generated inventory in a second file: rejected because users and automation would need precedence and transactional-consistency rules across two files.
- Let every normal sync rewrite discovery results: rejected because routine execution would mutate reviewed configuration and silently remove or add selectable resources.
