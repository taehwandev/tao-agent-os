---
keyflow_id: sys_executable_evidence_gate
status: review
type: human-reviewed-needed
---

# Executable Evidence Gate

Use this when a wrapper command, an evidence path, or a runtime permission
prefix is what the task turns on: which wrapper runs at each lifecycle step,
what each one writes, where its evidence lives, and the exact permission-entry
shape each runtime needs so an approval is not asked for again on the next
argument.

The rules that decide whether to run the lifecycle at all stay in the root
`AGENTS.md`. What moved here is the mechanics behind them, which the start
hook's own output already restates for the route in hand -- the copyable
commands, the required hooks, and the fields each gate wants. Read this when a
permission prompt repeats, an evidence path is in question, or a wrapper has to
be installed or wired; not before every task.

For multi-step tasks, use the executable wrappers when they are available. The
single start hook creates routing and preflight evidence with the current target
project and selected Tao Agent OS rule source before editing, reviewing,
committing, or reporting completion:

When executing wrapper commands from an agent runtime, replace
`<TAO_ROOT>` with the resolved absolute path first. Do not leave
`$HOME`, `${HOME}`, `~`, or a relative path in the executable command; those
forms can bypass narrow permission-prefix matching and cause repeated approval
prompts. Always register and request command permissions using the parameter-free
script path prefix (e.g., `python3 /absolute/path/to/script.py` or `node /absolute/path/to/script.mjs`)
instead of the full command with changing arguments. If a permission is saved
with arguments, any change to those arguments (e.g., different project paths or
options) will fail prefix matching and trigger repeated prompts.
For Codex `exec_command` escalations, set `prefix_rule` to only the executable
and resolved wrapper path, such as
`["/Users/USER/.tao/bin/tao-hook"]`; never
include `--project`, `--request`, `--gate-record`, `$(pwd)`, `$HOME`, or other runtime
arguments in the saved prefix. AGY (Antigravity) permission allowlists must follow the same
shape with only an absolute wrapper command plus a trailing argument wildcard.
Specifically, for any command, AGY requires registering three concurrent entries
to handle all parameter variations without prompts: `command(executable)`,
`command(executable:*)`, and `command(executable *)`. When implementing new
internal entrypoints under `scripts/`, ensure `<TAO_LAUNCHER> setup-agent-hooks` (via
`permission_entries.py`) automatically generates and updates these wildcard
combinations in settings.json and config.json. Claude managed user-level
hooks must use the stable launcher installed by `<TAO_LAUNCHER> setup-agent-hooks` at
`<TAO_LAUNCHER>`; setup refreshes
`~/.tao/tao-root` after moves or migrations so the Claude
hook command does not point at a stale checkout path.

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command <command> --request "<USER_REQUEST>" --intent-envelope "<JSON_OR_PATH>" [--approval-record "<JSON_OR_PATH>"] --runtime-session-id "<OPAQUE_SESSION_ID>" [--platform <platform>] [--concern <concern>]
```

Omit `--evidence` unless a run genuinely needs a path of its own: start then
mints `<TARGET_REPO>/.tao/runs/<32-hex-run-id>/preflight.json`, and only a run
directory named by that opaque id can hold a continuation packet. That packet
starts out holding the route name and nothing else; `tao-hook checkpoint
--work-stdin` is what puts the objective, non-goals, decisions, changed and
inspected scope, verification, remaining work and blockers into it, which are
the fields a resumed session is handed. Record one after reading the required
docs and scoping the task, and refresh it at each material decision -- without
it a resume recovers the route and the drift state but nothing about the work. Naming the
directory yourself with anything else -- a date, a branch, a description --
costs the run every checkpoint and makes `tao-hook resume` unable to continue
it, so start refuses that name rather than losing the packets quietly.

Keep `--output`, `--evidence`, and every custom evidence path inside
`<TARGET_REPO>/.tao/`. For temporary worktrees, use a project-local path
such as `<TARGET_REPO>/.tao/runs/<32-hex-run-id>/preflight.json`; a sibling
temporary directory is outside the execution-capsule trust boundary and will
make the finish check fail even when every route gate passed. The start hook
rejects an explicit `--evidence` path outside the target project's
`.tao/` root so a run cannot begin with a capsule that review, finish, and
handoff must later reject.

`start --evidence <...>/preflight.json` writes the lifecycle evidence that
`gate`, `review`, and `finish` must all read. `start --output <...>/start.json`
writes only the start hook result wrapper. Never name an `--output` file
`preflight.json` or pass it to later lifecycle hooks. When a custom run
directory is used, pass both options with distinct filenames and reuse the
exact `--evidence` path through the complete lifecycle.

After start, read the route's `required_docs` in order before editing or
reviewing. This remains a direct agent responsibility: there is no separate
document-confirmation hook or standalone receipt command. Preflight records the
required-document snapshot, route fingerprint, and request fingerprint in its
parent evidence. The `source docs` finish gate validates that parent snapshot
alongside the direct-reading takeaway. The execution capsule is created only at
the handoff boundary and reuses the snapshot. The route manifest remains the
single source for required-document selection, and `reference_docs` remain
on-demand context. An empty `required_docs` manifest is a valid document-free
route state: record the no-source decision and continue without polling or
forcing the execution capsule back to preflight. Call `<TAO_LAUNCHER> agent-preflight` directly only as a lower-level
diagnostic or compatibility fallback when the start hook is unavailable, and do
not run both for the same startup.

A fresh start may replace a prior context snapshot whose request, route, or
required-document hashes are stale. This is normal stale-state refresh, not a
repair cycle. The agent must then read the current `required_docs`, and the new
snapshot becomes the finish boundary. Missing, malformed, or unavailable
required documents remain a hard failure and must not be replaced silently.

When the shared rules root may have changed during a long-running task, such as
after concurrent runtime maintenance or a repository sync, compare the current
required-document hashes with `execution_snapshot.required_docs` before calling
`review` or `finish`. On drift, do not run those hooks against the stale
snapshot. Run `start` again with the exact same request and evidence paths,
read every changed required document, and re-record any gate or review evidence
affected by the new guidance. This proactive refresh is not a repair cycle. If
a required hook has already reported the drift as `FAIL`, use the normal single
retrospective repair cycle; a fresh start alone must not erase that failure. If
the repair intentionally edits required documents, reread their current bytes
and run `repair-verify` against each changed required document and the actual
failed checkpoint first. Then record one new `documentation` `SUCCESS` entry
per drifted document with `decision=updated`, that exact route-relative
required-doc path as `target`, and the verified receipt path and checkpoint as
`repair_evidence` and `resume_checkpoint`. Recording only the repair target
does not rebind other drifted required docs. A route that already requires the
`documentation` gate does not need repair fields for its normal task artifact.
The bound final-byte documentation receipt remains the source-doc snapshot
exception; off-route evidence may mint it only from the failed checkpoint's
validated structural repair receipt.

For work-producing tasks, do not wait until final reporting to think about
documentation. Treat `documentation impact` as a pre-code/pre-edit checkpoint:
select the artifact class first, name the affected doc path or doc class, choose
`updated`, `created`, `unchanged`, or `not applicable`, and state why the
changed behavior, workflow policy, public contract, operator action, or
acceptance criteria does or does not require a doc update. Artifact classes can
include PRD/spec/ARD, ADR/RFC, module README, API contract, runbook, migration
note, release note, test plan, skill/platform/workflow card, repo
`AGENTS.md`, or another source-of-truth class that fits the work. Do not treat
PRD as the only documentation shape. `Not applicable` or `no docs` is valid
only when the evidence states a no-durable-doc reason such as answer-only,
purely local, mechanical, no public contract, no operator action, or no
acceptance criteria. `Unchanged` is never a self-granted default: it is valid
only when the evidence names the concrete existing doc path (for example
`app/README.md`, not just a doc class), proves that doc was actually
opened/inspected/read this task, and states why the already-read doc already
covers the change. A bare coverage assertion without the inspection proof, or
without a named doc path, fails the gate. The `documentation` gate must always
run and carry non-empty evidence — it cannot be skipped or left blank — and it
must prove the actual update, or the grounded unchanged decision. Skipping
documentation (a not-applicable/no-docs/skipped decision on the `documentation`
gate) is never self-approved by the agent, and a no-durable-doc reason alone is
not sufficient: when you believe docs should genuinely not be written, ask the
user "문서를 스킵할까요? / Should I skip the doc?", get explicit approval, and
record that approval in the evidence — otherwise write the doc. The full,
updatable gate contract and the exception process are the source of truth in
`workflows/skills/documentation-update/SKILL.md`; add new exceptions there rather
than self-judging, and load that card in Grill-Me or self-review to check the
current work before completion.

Before finish on every route, run the required lightweight `retrospective
check`: inspect the skills actually loaded and applied, then record
the exact fields `skills_checked`, `outcome`, and `observation`. `outcome` is
`no_reusable_gap`, `reusable_gap`, or `no_skill_used`; `observation` is
`not_needed` or `recorded`. Pair `no_reusable_gap` and `no_skill_used` with
`not_needed`, and pair `reusable_gap` with `recorded`. The check is required
finish evidence. If there is no reusable gap, do not create a ceremonial
observation record. If there is one, the `skill-feedback` hook records a
content-free observation for a skill actually used, then the same closeout
must draft, review, stage, edit, and verify the canonical skill document.
Canonical guidance changes only through the verified maintenance recorder;
missing storage, tokens, reviewers, or maintenance capacity keeps finish
pending rather than silently dropping the update. Unrelated historical
candidates do not block this one. Default review
to one capable agent and use additional reviewers only when impact and available
budget justify them. The detailed decision and privacy rules are owned by
`workflows/skills/retrospective-learning/SKILL.md`.

Before final report, commit, release, or handoff, record every remaining route
gate with explicit structured status, then run the read-only finish hook:

Treat a successful review as an intermediate checkpoint, not finish readiness:
record `retrospective check`, then every remaining closeout gate including the
user-facing `handoff`, and only then invoke the finish hook.

Treat the exact `Route: ... gates=[...]` list returned by the current `start`
run as the completion checklist. Never reuse a gate list from another run,
route, or example; immediately before `finish`, compare the current ledger with
that exact list and record every missing gate through `gate` or `gate-batch`.

`<TAO_LAUNCHER> handoff` refreshes the optional parent-to-worker execution
capsule only. It does not record the route's user-facing `handoff` gate. Record
that gate explicitly with `gate` or `gate-batch` and concrete final handoff
evidence before `finish`; do not invoke the worker handoff hook merely to satisfy
the route gate.

For structured `ambiguity check` evidence, record `blocker_status`,
`assumptions`, and `decision`; only `none` or `resolved` plus `proceed` may
pass. For structured `alignment brief` evidence, record
`shared_understanding`, `possible_differences`, `assumptions`, and
`checkpoint=user_visible_before_edits`. Existing finish-valid prose remains
compatible. The canonical decision rules live in
`workflows/skills/ambiguity-gate/SKILL.md`.

```text
<TAO_LAUNCHER> gate-batch --project <TARGET_REPO> --rules <TAO_ROOT> --gate-record '[{"gate":"orient","status":"SUCCESS","evidence":"<evidence>"},{"gate":"scope","status":"SUCCESS","evidence":"<evidence>"},{"gate":"act","status":"SUCCESS","evidence":"<evidence>"},{"gate":"verify","status":"SUCCESS","evidence":"<evidence>"},{"gate":"report","status":"SUCCESS","evidence":"<evidence>"}]'
<TAO_LAUNCHER> finish --project <TARGET_REPO> --rules <TAO_ROOT>
```

Structured gate fields must be passed in the record's `fields` object; putting
JSON-shaped text inside `evidence` does not populate them. For example:

```json
{"gate":"retrospective check","status":"SUCCESS","evidence":"closeout checked","fields":{"skills_checked":"graphify","outcome":"no_reusable_gap","observation":"not_needed"}}
```

`finish` must not create or override gate evidence. A later structured `FAIL`
for a gate invalidates an earlier `SUCCESS` until a later verified `SUCCESS` is
recorded through `gate` or `gate-batch`.

Call `<TAO_LAUNCHER> agent-finish-check` directly only as a lower-level diagnostic or
compatibility fallback when the finish hook is unavailable.

The wrappers write local JSON evidence under `<TARGET_REPO>/.tao/`.
The gate ledger is `<TARGET_REPO>/.tao/gate-evidence.json` for the
default `preflight.json`; custom preflight evidence files use
`<preflight-stem>-gate-evidence.json` so concurrent or delegated runs do not
overwrite one another.
That directory is local runtime evidence and should usually be gitignored.
Generated runtime caches and copied local skill caches also belong under the
ignored `<TARGET_REPO>/.tao/` boundary. Workflow document validation must
exclude that boundary, and review-time checks must not create legacy sibling
state directories that appear as source changes.
The wrappers may also read or write safe cross-agent lessons under
`~/.tao/`. That user-global store is for content-free lesson metadata
only: missed gate slugs, failure types, root-cause categories, next actions, and
promotion status. It must not contain prompts, responses, commands, file paths,
repo names, branch names, diffs, logs, source content, environment values,
secrets, or project-specific display names.

Missing preflight evidence, missing finish-check evidence, or missing gate
evidence is non-compliant even when the final code or documentation appears
correct. `<TAO_LAUNCHER> agent-preflight --request-classified` must include
`--classification-evidence`; otherwise request intake is treated as skipped.
Evidence alone is not sufficient: the flag is honored only when a ready and
valid parent execution capsule backs it, and the requestless form is rejected.
Otherwise the classifier runs on `--request` as for any other caller.
For required gates, a skip, not-applicable, unable-to-run, deferred, or
follow-up reason is not completion unless that gate explicitly allows that
outcome and the evidence names the allowed reason. Evidence that names an
unresolved, must-fix, should-fix, blocking, or deferred issue must fail the gate
instead of passing with a note; use missed-gate recovery and retrospective
learning to fix the process.
If route classification or stored request text says `grill_me: true`, legacy
`question_drill: true`, or explicitly asks for Grill-Me, `<TAO_LAUNCHER> agent-finish-check`
must receive Grill-Me protocol evidence such as
`grill-me if needed=</grilling session/output evidence>`. Legacy
`question drill if needed=<evidence>` or `ask blockers=<evidence>` is accepted
only when the evidence still names the Grill-Me protocol, skill, or
`/grilling` session and output.
Missing Grill-Me evidence is `🐱🔴 FAIL` and sets
`retrospective_required: true`.

If the wrappers are unavailable, the fallback is still strict: run the
workflow router, `git status --short --untracked-files=all`, VibeGuard before
work, VibeGuard again before finishing, and report each required gate with
concrete evidence. Do not claim wrapper evidence exists unless the wrapper was
actually run.

When `<TAO_LAUNCHER> agent-finish-check` marks `retrospective_required`, run the
canonical retrospective repair cycle before reporting completion. Improve and
verify the owning Tao Agent OS guidance, hook, validator, or test, apply safe
scoped fixes, then resume at `first_failed_checkpoint`. Stop instead of
continuing when the same failure recurs after repair, the repair is unsafe or
ambiguous, source ownership is uncertain, verification fails, or the single
repair cycle is exhausted.

Do not merge this failure path with successful-task skill feedback. Required
hook or gate failure remains blocking and must use the repair-and-resume
contract. Skill feedback is a separate path: a reusable-gap observation starts
the same-closeout draft/review/stage/maintenance sequence, which is owed
closeout work rather than a repair cycle.
Neither one is answered with `repair-verify`.

VibeGuard `Needs review` is not completion unless the agent explicitly reports
the review state and passes `--allow-vibeguard-review "<reason>"` to every
required lifecycle hook that evaluates that state, including both `review` and
`finish`. Route-generated review commands must advertise this optional argument.
`🐱🔴 FAIL`, command failure, or missing VibeGuard output remains a blocker.
Human-visible finish-check output must include only `🐱🟢 SUCCESS` and
`🐱🔴 FAIL`; the machine-readable JSON keeps the same stable `SUCCESS` and
`FAIL` values.
