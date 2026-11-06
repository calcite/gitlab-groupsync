# Specification Acceptance Test Matrix

This audit maps every numbered scenario in section 11 of
`specs/gitlab_reference_sync_spec.md` to automated evidence. Automated tests use
API fixtures and temporary local Git repositories. Human-confirmed operational
and targeted hierarchy-query evidence from 2026-11-05 against GitLab 19.5.3 is
recorded in `CAPABILITIES.md`; the captured hierarchy envelopes are replayed by
`tests/test_discovery.py::test_gitlab_19_5_3_recorded_hierarchy_responses`.
Licensed group-wiki coverage remains fixture-only and not live-tested.

| # | Automated evidence |
| --- | --- |
| 1 | `tests/test_discovery.py::test_cli_discovery_uses_real_http_pagination_and_refreshes`, `test_shared_inclusion_and_archived_exclusion_parameters`; projectless groups in `tests/test_orchestrator.py::test_root_nested_projectless_group_wikis_and_project_continue_after_failure`. |
| 2 | `tests/test_discovery.py::test_refresh_preserves_settings_selections_and_is_deterministic`, `test_failed_page_leaves_configuration_byte_identical`, `test_refresh_root_replacement_incomplete_and_invalid_files`, and CLI discovery tests cover same-file stable-ID selection merge, defaults, removal after completeness, root protection, ordering, atomicity, and secret/override exclusion. |
| 3 | `tests/test_discovery.py::test_inventory_diff_all_categories_and_incomplete_rejection`; `tests/test_orchestrator.py::test_drift_success_manifest_metadata_and_independent_wiki_failure`, `test_no_selected_components_no_project_requests_and_no_drift_exit_zero`, and `test_catalog_group_absent_from_live_makes_no_request`. |
| 4 | `tests/test_git_sync.py::test_real_initial_incremental_noop_delete_rename_and_force_push` uses real repositories and detached force-safe fetches. |
| 5 | `tests/test_orchestrator.py::test_empty_disabled_inaccessible_transient_and_local_conflict_states`, `test_drift_success_manifest_metadata_and_independent_wiki_failure`; `tests/test_git_sync.py::test_remote_head_empty_wiki_branch_and_local_conflicts`. |
| 6 | `tests/test_orchestrator.py::test_no_selected_components_no_project_requests_and_no_drift_exit_zero`, `test_root_nested_projectless_group_wikis_and_project_continue_after_failure`; group-wiki API/export fixtures in `tests/test_group_wikis.py`. |
| 7 | `tests/test_reconcile.py::test_project_rename_disappearance_reappearance_and_path_reuse`, `test_group_payload_rename_preserves_descendant_and_component_round_trip`, and `test_interrupted_relocation_recovers_without_reclone`; unmanaged collision suites. |
| 8 | `tests/test_discovery.py::test_failed_page_leaves_configuration_byte_identical`; `tests/test_orchestrator.py::test_setup_discovery_identity_project_details_and_path_failures` plus reconciliation completeness boundaries. |
| 9 | `tests/test_work_items.py::test_issue_task_metadata_threads_relationships_and_deterministic_no_rewrite`; `tests/test_discovery.py::test_work_item_rest_endpoints_and_graphql_hierarchy_pagination`. |
| 10 | `tests/test_work_items.py::test_full_refresh_repairs_deleted_note_partial_stays_due_and_full_only_quarantine` uses unchanged parent timestamps and repairs edited/deleted conversation content. |
| 11 | `tests/test_work_items.py::test_later_discussion_failure_retains_content_queues_retry_and_advances_safely`; API pagination failure cases in `tests/test_discovery.py`. |
| 12 | `tests/test_work_items.py::test_issue_task_metadata_threads_relationships_and_deterministic_no_rewrite`, `test_interrupted_publication_recovers_from_complete_raw_snapshot`, and partial-full checkpoint assertions. |
| 13 | `tests/test_work_items.py::test_full_refresh_repairs_deleted_note_partial_stays_due_and_full_only_quarantine`. |
| 14 | Local modifications, checkout/clone/publication failure and timeout in `tests/test_git_sync.py`; publication recovery in work-item/group-wiki tests; contention/process death in `tests/test_state.py`; repeated auth and bounded retry behavior in `tests/test_discovery.py`. |
| 15 | Token/remote/askpass redaction and TLS/custom CA in `tests/test_git_sync.py`, `tests/test_discovery.py`, and `tests/test_gitlab_groupsync.py`; traversal/symlink/unmanaged cases in Git, group-wiki, reconcile, state, and work-item suites; invalid configuration exit tests in `tests/test_gitlab_groupsync.py`. |
| 16 | Deterministic unchanged Markdown/raw timestamps in `tests/test_work_items.py::test_issue_task_metadata_threads_relationships_and_deterministic_no_rewrite`; raw snapshots outside `content/`; checked-in sample and generated search-guide contracts in `tests/test_documentation.py`. |

The release gate additionally runs the configured 100% coverage suite, Ruff
lint/format checks, mypy, tox, lock validation, package build, clean wheel
installation, installed `gl-groupsync --help`, and package-data inspection.

## Optional Git LFS

`tests/test_lfs.py` covers statistics evidence and unknown/malformed responses,
conditional fields, stable-ID defaults and preservation, config compatibility,
atomic discovery failures, real exact-commit hydration, unchanged-revision
enablement, incremental updates, stopping downloads, local conflicts, missing
objects and retry, and missing executable behavior. Selected-only executable
checks are in `tests/test_diagnostics.py`; repository-only selection and retained
success/failure isolation are in `tests/test_orchestrator.py`.
