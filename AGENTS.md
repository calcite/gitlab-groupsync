## Backlog.md workflow

Backlog.md is the authoritative record of active and completed development work.

Tasks are living work records. Their initial descriptions and acceptance criteria may be incomplete and may evolve during implementation as the human and agent investigate the problem.

### General rules

1. Before beginning substantial work, identify the relevant Backlog task and read it in full.
2. Do not treat the initial task specification as immutable.
3. Keep the task synchronized with the current shared understanding throughout the development session.
4. Do not require the human to operate the Backlog CLI. Perform all necessary Backlog operations yourself.
5. Use Backlog.md tasks, comments, plans, notes, and final summaries.
6. Do not use Backlog.md decisions. Record durable architectural decisions as ADRs under `docs/adr/`.
7. Only the human may accept a task as complete.

### Comments

Use task comments as a concise chronological record of material human-agent discussion.

Add comments on behalf of both participants when the conversation produces information that would be useful in a future session, including:

* clarification of ambiguous requirements;
* answers to implementation questions;
* requested changes in behavior or scope;
* alternatives considered and rejected;
* explicit human approvals or objections;
* reasons for changing the implementation direction;
* unresolved questions that affect further work.

When recording comments:

* Attribute each comment clearly as `Human` or `Agent`.
* A comment attributed to `Human` must faithfully summarize something the human explicitly said or confirmed.
* Do not invent, extrapolate, or strengthen the human's position.
* Preserve important qualifications and uncertainty.
* Prefer concise summaries over verbatim transcripts.
* Do not record routine conversation, acknowledgements, minor corrections, or raw chat history.
* Group closely related discussion into one comment when appropriate.
* Record comments during the session when a material clarification occurs, rather than trying to reconstruct the entire conversation at the end.

Example:

> **Agent:** The existing importer permits identical entries from different source files. Should duplicate detection apply globally or only within one import?

> **Human:** Duplicate detection should apply only within one import process. Identical entries from separate imports are allowed.

Comments provide the historical trail, but they are not the canonical specification.

### Updating the canonical task

After a question is settled, update the relevant canonical part of the task:

* update the description when the intended behavior or scope changes;
* update acceptance criteria when testable requirements are clarified;
* update the implementation plan when the technical approach changes;
* update dependencies when newly discovered work blocks the task.

A future agent should be able to understand the current requirements without reconstructing them from comments.

Preserve the original intent where useful, but make the current description and acceptance criteria accurately represent the latest agreed behavior.

When requirements remain uncertain, state the uncertainty explicitly rather than silently selecting an interpretation.

### Notes

Use task notes as durable working memory for implementation-related knowledge discovered during the task.

Appropriate notes include:

* relevant existing code and where it is located;
* observed current behavior;
* investigation results;
* technical constraints;
* external API or library behavior relevant to the task;
* failed approaches and why they failed;
* commands useful for reproducing or verifying behavior;
* migration or compatibility concerns;
* assumptions that still require verification;
* risks and known limitations;
* useful context for continuing the task in another agent session.

Notes should contain distilled conclusions and evidence, not private reasoning or an exhaustive activity log.

Good note:

> Duplicate detection cannot use a database unique constraint because users may approve otherwise identical rows. Implement it in `ImportValidationService`, scoped by `ImportProcess.id`.

Bad note:

> I opened several files, thought about using a constraint, changed my mind, and then considered a service.

Keep notes current:

* correct notes that are proven wrong;
* remove or clearly mark obsolete information;
* preserve failed approaches only when knowing about them prevents repeated work;
* distinguish confirmed facts from assumptions.

### ADRs

Do not create or use Backlog.md decision records.

Create an ADR under `docs/adr/` when a decision:

* affects multiple tasks or components;
* defines a long-lived architectural rule;
* changes an important data model, interface, dependency, or deployment approach;
* involves meaningful alternatives and trade-offs;
* is likely to matter after the current task is completed.

Use the next available ADR number and the repository's ADR template.

A task should link to relevant ADRs, for example:

> Architectural context: `docs/adr/0012-store-monetary-values-as-integers.md`

Task-specific choices that have no wider architectural significance should remain in the task comments, notes, or implementation plan.

### Scope discovered during implementation

Do not silently expand a task.

When additional work is discovered:

* incorporate it into the active task only when it is small, necessary to satisfy the agreed acceptance criteria, and does not materially broaden the scope;
* otherwise create a separate Backlog task;
* link the new task from the active task;
* state whether it blocks the active task or is follow-up work.

### Session checkpoints

Update the Backlog task at natural checkpoints:

1. after initial investigation;
2. after a material requirement clarification;
3. after a significant change in implementation approach;
4. before ending a session with unfinished work;
5. before requesting human review.

Before ending an unfinished session, ensure that another agent can continue from the task without requiring access to the previous chat.

At minimum, record:

* the current state of implementation;
* settled requirements;
* remaining open questions;
* relevant findings;
* the next concrete action;
* commands or tests needed to continue.

### Completion

Before moving a task to human review:

1. Re-read the complete task.
2. Ensure the description and acceptance criteria reflect the final agreed scope.
3. Ensure all material session decisions are represented in the canonical task, comments, notes, or an ADR.
4. Update acceptance-criteria checkboxes based on verified behavior.
5. Add a final summary containing:

   * what changed;
   * important implementation choices;
   * tests and checks performed;
   * known limitations;
   * follow-up tasks;
   * ADRs created or referenced.
6. Move the task to the review state, not directly to accepted or complete.
7. Leave final acceptance to the human.

<!-- BACKLOG.MD GUIDELINES START -->
<!-- backlog.md-instructions-version: 1.52.0 -->
<CRITICAL_INSTRUCTION>

## Backlog.md Workflow

This project uses Backlog.md for task and project management.

**At the beginning of each conversation in this project, run `backlog instructions overview` before answering or taking action. Re-read it only if you have not read it yet in the current conversation.**

Use the overview to decide whether to search, read, create, or update Backlog tasks.

Before task lifecycle actions, read the matching detailed guide:
- `backlog instructions task-creation` before creating or splitting tasks
- `backlog instructions task-execution` before planning, changing status or assignee, adding a plan or implementation notes, or implementing task work
- `backlog instructions task-finalization` before checking acceptance criteria, writing final summaries, or moving tasks to terminal statuses

Use `backlog <command> --help` before running unfamiliar commands. Help shows options, fields, and examples.

Do not edit Backlog task, draft, document, decision, or milestone markdown files directly. Use the `backlog` CLI so metadata, relationships, and history stay consistent.

</CRITICAL_INSTRUCTION>
<!-- BACKLOG.MD GUIDELINES END -->
