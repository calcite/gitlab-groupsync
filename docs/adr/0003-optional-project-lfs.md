# ADR 0003: Optional project Git LFS hydration

- Status: Accepted
- Date: 2026-11-04
- Accepted: 2026-11-05, following human confirmation of live LFS fetching and
  authorization to close the feature task (TASK-006).

## Context

The stable-ID selection catalog (ADR 0001) offers project repositories for offline
reference. LFS pointer files do not contain the referenced content. Downloading
every LFS object can materially expand storage and network use. The human wants
opt-in LFS support only for projects that have objects, limited to the current
default-branch checkout.

## Decision

Extend project entries with an optional boolean `lfs`, omitted by default and
interpreted as false. True requires `repository: true`. Discovery requests
`GET /projects/:id?statistics=true` and offers `lfs: false` when
`statistics.lfs_objects_size` is positive. Existing choices follow stable project
IDs, including across renames. Confirmed zero removes the field. Newly eligible
or reappearing entries default false. `lfs_enabled` alone is insufficient.

Missing statistics or a missing size are unknown, not zero: report this, retain
any existing choice, and offer no new field. Invalid payloads and request
failures abort the atomic refresh. Normal synchronization does not rewrite the
catalog or query these statistics. Statistics require Reporter-level access and
are project-wide evidence that can lag changes or include historical files.

Keep automatic smudging disabled. Install only local skip-smudge filters without
hooks, explicitly fetch LFS objects for the exact target revision, and hydrate
the checkout. Override recent/path download settings to enforce that scope.
Fetch before switching existing worktrees and finish hydration before initial
staged publication or repository success reporting. Hydrate even when the Git
revision is unchanged, and verify that no LFS pointer files remain: LFS checkout
can exit zero after skipping unavailable objects. Preserve local-edit protection
and the existing Git subprocess controls, credentials, timeouts and error
isolation.

LFS is part of the repository resource, not a separate resource or state schema.
Disabling it stops downloads without deleting cached objects or proactively
rewriting unchanged hydrated files. Local filters remain necessary to recognize
hydrated content as clean. Doctor checks Git LFS only when LFS is selected.

## Consequences

- Existing configurations remain valid and do not start downloading payloads.
- Discovery needs one additional project request per visible project; routine
  synchronization does not incur these requests.
- Restricted statistics do not erase user intent or imply object absence.
- Historical-only LFS usage can offer an option that downloads nothing at HEAD.
- Repository success includes requested LFS hydration; failures can be retried.
- Git LFS is required when selected and should remain installed for previously
  hydrated checkouts. Caches are retained rather than automatically pruned.
- Other branches, historical payloads and wiki LFS are outside this contract.

## Alternatives considered

- Offer LFS wherever `lfs_enabled` is true: rejected because GitLab can enable
  the feature without storing any objects.
- Add the flag to every project: rejected because availability would not reflect
  stored objects.
- Use automatic smudging: rejected because explicit transfers give the
  synchronizer control over scope, staging, credentials and failure handling.
- Download all historical objects: rejected because the corpus materializes the
  current default branch and the human explicitly selected that scope.
- Treat absent statistics as zero: rejected because permissions could silently
  remove previously reviewed intent.
