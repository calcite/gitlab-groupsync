---
id: TASK-004
title: Verify work-item hierarchy GraphQL query against a live GitLab instance
status: Done
assignee:
  - '@opencode'
created_date: '2026-09-20 11:08'
updated_date: '2026-11-05 15:21'
labels: []
dependencies: []
references:
  - specs/gitlab_reference_sync_spec.md
  - docs/live-evidence/gitlab-19.5.3/hierarchy-15-response.json
  - docs/live-evidence/gitlab-19.5.3/hierarchy-16-response.json
  - tests/test_discovery.py
documentation:
  - docs/LIVE_TESTING.md
  - docs/CODE_REVIEW_2026-09-20.html
priority: high
type: spike
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
This spike investigated whether GitLabClient.work_item_hierarchy could safely query namespace(fullPath: $path) with a project full path, rather than silently returning no hierarchy. Ordinary sync success alone was insufficient evidence because hierarchy lookup can degrade to a limitation.

The human approved using the existing https://gitext.alps.cz instance and the known zero-iot/lambda_api issue 15 -> child 16 pair, replacing the original disposable-instance and single-item-with-both-parent-and-child setup. Human-run doctor output recorded GitLab 19.5.3. The human then executed the documented read-only query for both IIDs, retained the exact response bodies in temp/hierarchy-15-response.json and temp/hierarchy-16-response.json, supplied the responses, and independently confirmed in GitLab that issue 16 is the child of issue 15.

Both responses return data.namespace.workItem.widgets with the expected hierarchy and no GraphQL errors. Issue 15 returns child IID 16/global ID 4013; issue 16 returns parent IID 15/global ID 3816. Both have hasNextPage:false. The current query works on this tested server and pair; no alternative query or product-code change is needed. Durable response copies are recorded under docs/live-evidence/gitlab-19.5.3 and replayed through the existing adapter in a regression test. Reproduction and observed coverage are recorded in docs/LIVE_TESTING.md and docs/CAPABILITIES.md. No server content or server-side fixtures were created or modified. This evidence does not establish every GitLab version, work-item type, or live multi-page child behavior; the edition is unreported and was not an additional closure prerequisite.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A human operator runs the targeted query read-only against the explicitly approved existing GitLab instance; server version 19.5.3 is recorded from human-run doctor output.
- [x] #2 Verbatim GraphQL responses for zero-iot/lambda_api issues 15 and 16 are retained, and the human confirms the known relationship (15 is the parent of 16).
- [x] #3 The result states whether the current query shape returns hierarchy, returns null, or errors.
- [x] #4 If the current query shape does not work, a working shape is identified and recorded; otherwise record that no alternative is needed.
- [x] #5 Test fixture payloads match the shape the live server actually returns.
- [x] #6 docs/CAPABILITIES.md records the tested server version and observed hierarchy coverage, replacing the current fixture-only claim.
- [x] #7 docs/LIVE_TESTING.md carries the reproduction steps used.
- [x] #8 If live results require a product code change, a separately approved implementation task is linked; otherwise record that no implementation follow-up is needed.
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 Exact GitLab server version recorded in docs/CAPABILITIES.md
- [x] #2 All queries run were read-only
- [x] #3 Executed by a human tester against the explicitly approved existing GitLab instance and known parent/child pair; fixture-only evidence is not accepted.
<!-- DOD:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Record the explicit approval of the existing instance and known issue pair and update the canonical task. 2. Document and provide an exact human-run read-only query for both issue IIDs, using existing token/configuration and retaining verbatim response files. 3. After the human runs the query and confirms the relationship, inspect the saved responses and compare the schema with the adapter fixtures. 4. Record the evidence, verify criteria, and close under the existing instruction to close accepted related work if no further confirmation or implementation is required.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Settled scope: human-authorized existing instance and parent/child pair replace the original disposable/single-item setup. GitLab version 19.5.3 is evidenced by human-run doctor output. The human ran the exact adapter query for zero-iot/lambda_api IIDs 15 and 16 and confirmed the relationship in the GitLab UI.

Evidence: original response bodies remain untouched at temp/hierarchy-15-response.json and temp/hierarchy-16-response.json. Durable JSON copies are at docs/live-evidence/gitlab-19.5.3/hierarchy-15-response.json and hierarchy-16-response.json, with only a terminal newline added. Byte comparison verified this exact relationship between originals and durable copies. Both envelopes contain data.namespace.workItem.widgets, including empty objects for other widget types; hierarchy nodes expose id, iid, title and webUrl. Issue 15: null parent and child IID 16/global ID gid://gitlab/WorkItem/4013. Issue 16: parent IID 15/global ID gid://gitlab/WorkItem/3816 and no children. Both child connections have hasNextPage:false; issue 15 has endCursor MQ despite no next page. There are no GraphQL errors. The current namespace/project-path query returns hierarchy correctly on GitLab 19.5.3; no alternative or product-code follow-up is needed.

Fixture comparison: added tests/test_discovery.py::test_gitlab_19_5_3_recorded_hierarchy_responses to replay both durable captured envelopes using MockTransport through the existing GitLabClient.work_item_hierarchy adapter. The test verifies both directions, no hierarchy limitations, and exactly two requests without spurious pagination from a non-null endCursor. Existing synthetic pagination/error tests remain in place. The documented human query was already syntax-checked and compared with the actual adapter query after whitespace normalization.

Checks: uv run pytest -q tests/test_discovery.py tests/test_documentation.py: 60 passed. uv run ruff check ., uv run ruff format --check ., uv run mypy gitlab_groupsync and git diff --check passed. A read-only evidence script verified the preserved bodies, expected relationship, absence of errors and hasNextPage:false. No agent live requests were needed. README, capability report, live-testing reproduction/result and acceptance matrix now record the completed targeted validation.

Known limits: edition remains unreported; no live multi-page child case or licensed group wiki was exercised; no cross-version compatibility claim. The earlier manifest local conflicts and doctor warnings for server-disabled wikis are independent of this successful query validation. No remaining implementation work, new follow-up task or ADR is required. Human requested closure of accepted related work and supplied the final relationship confirmation.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-11-05 10:29
---
Confirmed that LFS fetching and the entire system work against the GitLab instance, and requested related tasks be closed or remaining confirmations requested. This confirmation did not specify the exact GitLab version, a targeted hierarchy query response, or a change to the disposable-instance requirement.
---

author: Human
created: 2026-11-05 10:36
---
Supplied doctor output identifying GitLab 19.5.3, Git 2.47.3 and Git LFS 3.6.1. Configuration, TLS verification, authentication and root visibility passed; discovery reported 7 groups and 68 projects. Doctor reported 11 selected project wikis unavailable. No edition, explicit approval of the alternate hierarchy test setup, or raw targeted GraphQL response was supplied.
---

author: Human
created: 2026-11-05 10:41
---
Explicitly approved using the existing GitLab instance and the known zero-iot/lambda_api issue 15 -> child 16 relationship for the final human-run read-only hierarchy check, replacing the original disposable-instance test setup.
---

author: Agent
created: 2026-11-05 10:43
---
Prepared the exact read-only query and human-run capture command in docs/LIVE_TESTING.md. Existing GitLab 19.5.3 and the known parent/child pair are now the approved test setup. Awaiting the two saved response files and human confirmation of the relationship before final closure.
---

author: Human
created: 2026-11-05 15:20
---
Ran the approved read-only hierarchy query and supplied the saved responses for zero-iot/lambda_api issues 15 and 16. The responses return child IID 16 for issue 15 and parent IID 15 for issue 16, without GraphQL errors; both child connections have hasNextPage:false. Independently confirmed in GitLab that issue 16 is the child of issue 15.
---

author: Agent
created: 2026-11-05 15:21
---
Validated both saved response bodies, preserved durable copies, replayed them successfully through the existing adapter, and recorded the human UI confirmation. All acceptance criteria and DoD items are satisfied under the approved test setup. Closed as Done under the prior human instruction to close accepted related work; no further confirmation or implementation follow-up is needed.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Human-verified the current namespace(project-path)/workItem hierarchy query against GitLab 19.5.3 on the explicitly approved existing instance and known zero-iot/lambda_api issue 15 -> child 16 pair. Both raw responses return the expected relationship without errors or additional child pages, and the human independently confirmed the relationship in GitLab. The original suspected always-null query behavior was not reproduced; no alternative query or product-code fix is needed.

Preserved durable JSON response copies, added offline adapter replay coverage for the exact live shapes, and updated README, capability evidence, reproduction/result documentation and acceptance mapping. Verification: 60 discovery/documentation tests pass; Ruff lint/format, mypy, evidence byte/shape checks and git diff --check pass. All live operations were human-run read-only queries; no server mutations occurred.

Limits: observed GitLab version is 19.5.3; edition unreported, live multi-page hierarchy and licensed group wikis not tested. No follow-up task or ADR created. Closed under the human instruction to close accepted related work after the supplied final relationship confirmation.
<!-- SECTION:FINAL_SUMMARY:END -->
