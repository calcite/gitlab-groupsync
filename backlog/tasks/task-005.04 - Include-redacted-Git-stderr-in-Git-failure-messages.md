---
id: TASK-005.04
title: Include redacted Git stderr in Git failure messages
status: Review
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-09-20 12:08'
labels: []
dependencies: []
parent_task_id: TASK-005
type: enhancement
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Review of TASK-001 found that `GitRunner.run` raises `GitSyncError("Git operation failed (fetch)")` and discards the subprocess stderr entirely. An operator reading logs, `gl-groupsync status`, or a resource last_error cannot distinguish an authentication rejection from a missing branch, a host-key problem, or a network failure, so every Git fault looks the same. Specification section 8 asks for logs that identify the resource and an actionable error while redacting credentials, which means redacting the detail rather than discarding it. The redaction path already exists for successful output.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A failed Git command raises an error that includes the stderr of that command
- [x] #2 Token material is redacted from any included stderr and stdout
- [x] #3 The message still identifies the resource and which Git operation failed
- [x] #4 A test asserts that a token value never appears in a raised message or recorded last_error
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Redact captured Git stdout/stderr before evaluating failures and include nonempty streams in GitSyncError.
2. Identify the actual Git subcommand after global options and pass logical resource keys through synchronizer calls.
3. Preserve detailed errors when marking an existing checkout inconsistent and pass wiki identity to remote-head failures.
4. Add direct redaction assertions and an orchestration test proving persisted last_error contains resource/operation/detail but no token.
5. Run focused Git/orchestrator tests and static checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
GitRunner now redacts both captured streams before return-code handling, reports the actual subcommand after -C, and includes nonempty stdout/stderr plus the logical resource key. Existing-checkout inconsistency errors retain the underlying detail.
Validation: 32 Git/orchestrator tests passed, including direct stdout/stderr token redaction and persisted last_error/manifest assertions; focused Ruff and format checks passed.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Made failed Git operations actionable without leaking configured tokens. Errors now identify resource and operation, include redacted subprocess output, survive checkout wrapping, and are verified through persisted status metadata.
<!-- SECTION:FINAL_SUMMARY:END -->
