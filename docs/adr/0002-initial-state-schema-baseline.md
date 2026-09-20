# ADR 0002: Initial state schema baseline

- Status: Accepted
- Date: 2026-09-20

## Context

Before the first release, the internal SQLite schema accumulated several incremental versions and migration branches as features were developed. No released destination can contain those intermediate layouts, so retaining their upgrades would make unsupported development schemas part of the permanent compatibility contract.

## Decision

The complete SQLite layout shipped by the first release is schema version 1. It is the baseline for all future state migrations.

Writable state opening creates the full baseline only when `PRAGMA user_version` is zero, opens version 1 without schema mutation, and rejects versions newer than the application supports. Read-only state opening requires the exact supported version. Future released schema changes must increment the version and provide migration from every still-supported released version, beginning with baseline 1.

Pre-release databases previously numbered 2 through 5 are not supported. They must be removed and recreated by synchronization before upgrading to the first release.

## Consequences

- The first public compatibility boundary is explicit and minimal.
- Production code and tests do not carry speculative upgrades for schemas that were never released.
- Future schema changes must preserve and test migration from version 1 while it remains supported.
- Developers with a pre-release destination must recreate it; retained pre-release state is not silently interpreted as the released baseline.

## Alternatives considered

- Keep version 5 and delete older migration branches: rejected because it preserves pre-release numbering as the first public contract and leaves ambiguous handling for lower versions.
- Keep every pre-release migration: rejected because no released destination requires them and each branch expands the permanent maintenance and testing surface.
