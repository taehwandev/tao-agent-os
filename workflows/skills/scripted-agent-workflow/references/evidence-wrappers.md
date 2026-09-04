---
keyflow_id: sys_scripted_agent_workflow_wrappers
status: stable
type: human-reviewed-needed
---

# Executable Evidence Wrappers

The wrapper commands a scripted route runs, and what each one writes. The route
and gate contract they serve -- the default script, the automatic gates, the
output contract -- is
`workflows/skills/scripted-agent-workflow/references/current-guidance.md`.

When available, use the wrapper scripts to make the route and gate ledger
auditable instead of relying on memory.

The route output also contains a `Required Hooks` section. Treat it as the
workflow's executable checklist:

- `start` runs preflight before edits, reviews, commits, or completion reports.
- `review` runs after meaningful edits and before finish, commit, release, or
  handoff when the route marks it required.
- `finish` runs before final report, commit, release, or handoff and verifies
  route gate evidence.

Before editing, reviewing, committing, or reporting completion:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --command <command> --request "<USER_REQUEST>" --intent-envelope "<JSON_OR_PATH>" [--approval-record "<JSON_OR_PATH>"] --runtime-session-id "<OPAQUE_SESSION_ID>" [--platform <platform>] [--concern <concern>]
```

The route may promote additional `required_docs` from the root
`workflow-doc-surfaces.json` map when semantic request intent or a verified
owner path shows a specific work surface. Rules may match route command,
selected platform, semantic request text, and explicit `--surface-path` values.
Path-like request references and paths from
`git status --short --untracked-files=all` remain `surface_candidates`; they do
not promote path guidance until bounded repository evidence proves the owner.
UI-capable platform
work must be covered as a matrix, not as a one-off Android rule: Android
Compose, Application desktop UI, Flutter widgets, iOS SwiftUI/UIKit, KMP
Compose, Swift design-system UI, and Web React UI should each promote the
matching UI, state, structure, review, visual verification, and performance
guidance. Literal framework-name shortcuts are test fixtures rather than policy
keys. This surface routing is for document selection only: it does not
replace request classification, command/profile selection, repo-local
instructions, or the requirement to read every routed `required_docs` entry
before edits.

Code-work routes place `work surface resolution` before `source docs`. Record a
structured `resolved` result with the owner, anchors, repository evidence chain,
verified surface paths, evidence-backed concerns, one to four search hops, and
the nearest falsifying verification. A direct local owner may use one hop.
`ambiguous` and `not_found` are terminal failed-gate results: report what was
checked, ask for one behavior-distinguishing clue, and stop before task-specific
reading or edits. Screenshots are first-class anchors, not a separate routing
branch, and sensitive visual contents must not be persisted in route metadata.

The route/search layer uses the repository-pinned Wikimap source for
deterministic, incremental section retrieval over Tao Agent OS guidance. It
runs only `update --no-map` and `search --json`; do not wire Wikimap install,
hook, migration, semantic-note, source-editing, or Graphify-import commands into
the workflow. The ignored `.wikimap/` SQLite index is disposable. The pinned
source checksum is verified by the local adapter; provenance and license are
covered by the vendor manifest and integration tests. The previous in-process
scorer remains a reported recovery path when Wikimap cannot run.

Wikimap candidates are natural-language seed documents, not automatic policy.
Explicit task facets and `workflow-doc-surfaces.json` continue to select
deterministic required guidance. The local document graph, derived from
Markdown links, canonical skill-bundle entrypoints, and surface document sets,
expands the combined seeds into connected skill entrypoints, detailed
references, and explicit dependencies. Treat Wikimap seeds and ordinary graph
links as `reference_docs` so broad surfaces do not overload required reading.
Promote a result to `required_docs` only through deterministic route policy or
an explicit required relation such as frontmatter `requires_docs`.

Natural-language document discovery belongs in the routing/search layer, not in
the hook body. Hooks do not select or read documents for the agent. The
existing `source docs` gate validates evidence that the routed required docs
were read directly and applied. The router and `workflow.py query` carry
retrieval through Wikimap, then apply reusable policy facets such
as cleanup, review, verification, UI feature work, skill docs, or document
routing and use the local document graph to add connected candidates. Target
projects continue to use Graphify for code symbols, architecture, and
relationships; Wikimap does not replace the project graph or its readiness
gate.

Wikimap completion is explicit: `no_matches` is a terminal no-source result,
while `invalid_manifest` names route paths that are actually missing. Neither
state may enter an unbounded discovery retry loop. The first continues with
deterministic guidance; the second stops for a source or routing repair.

The command includes task-specific arguments, but persistent runtime permission
prefixes must not. For Codex escalation, request only
`["python3", "/absolute/path/to/tao-agent-os/scripts/agent-hook.py"]` as the
saved `prefix_rule`; for Claude and AGY, allow only the equivalent absolute
wrapper command plus the runtime's trailing argument wildcard. Never save
`--project`, `--request`, `--gate-record`, `$HOME`, `$(pwd)`, or user text in the
permission prefix.

`agent-hook.py start` runs the preflight logic in-process and writes the same
preflight evidence. Calling `agent-preflight.py` directly is acceptable only as
a lower-level wrapper path when the start hook is unavailable.

After preflight, read every route `required_docs` entry directly before edits or
review. There is no separate document-confirmation command, receipt artifact,
or standalone document-reading gate. The existing execution capsule records the
preflight fingerprint, route fingerprint, and hashes of that required-doc set;
the `source docs` finish gate validates this binding without reintroducing a
read hook. Its structured record is populated with the exact routed
`required_docs` manifest, not an agent-supplied count or empty-manifest claim;
finish rejects an empty claim for a non-empty route. Record the direct reading
and applied takeaway in finish evidence.
`reference_docs` remain on-demand context. An empty `required_docs` list is a
valid document-free route state; record the no-source decision and continue
once rather than retrying discovery or holding the capsule in preflight.
When the task intentionally updates one of its own `required_docs`, the final
structured `documentation` record must use `decision=updated` and name that
exact route-relative path as `target`. Finish preserves the original capsule
snapshot and permits only that declared path to differ; an undeclared required
document change still fails the source-doc binding instead of creating a
finish/handoff deadlock.
When more than one routed required doc changes, record one `documentation`
`SUCCESS` entry per exact path. Do not combine required-doc paths in one
`target` string; the gate hook rejects that shape before finish.

Before invoking the review hook, compare the current ledger with the gates that
precede `review hook` in the active route. When any prerequisite gate is
missing, `FAIL`, or structurally incomplete, the hook rejects the invocation
before review begins. This rejection must not record a failed review checkpoint,
start a repair cycle, or request a repair receipt; record the current facts
through `gate` or `gate-batch`, then rerun the same review hook. Only a review
that starts after all prerequisites are complete can enter failure repair. Gates
that follow `review hook`, such as `retrospective check` and `report`, remain
closeout work and are not review prerequisites.

Treat a package-role boundary as an evidence requirement even when the task did
not create a new folder. When the reviewed package contains multiple roles,
write `--structure-review-evidence` with all five literal labels:
`owner: ...; allowed imports: ...; forbidden imports: ...; callers/tests: ...;
verification: ...`. “No new package boundary” or a general structure summary
does not replace any field.

Before invoking the finish hook, compare the current ledger with the complete
route gate list. If the route ends in `handoff`, record that gate as a
`SUCCESS` readiness checkpoint after verification, review, and retrospective
work are complete. This route gate means the final handoff target, artifacts,
and blocker state are ready; it is distinct from `agent-hook.py handoff`, which
only prepares a parent-to-worker execution capsule. Because finish validates
every route gate, waiting until after finish to record this readiness creates a
finish/handoff deadlock and is not a valid ordering.

Immediately before every `finish` invocation, read the current route gate list
and the current ledger together. Do not infer closeout readiness from a
successful review alone. When `handoff` is the final route gate, record its
user-facing readiness evidence in the ledger first, then invoke `finish`.

Treat a successful review as an intermediate checkpoint, not finish readiness:
record `retrospective check`, then every remaining closeout gate including the
user-facing `handoff`, and only then invoke the finish hook.

Before final report, commit, release, or handoff:

```text
python3 <TAO_ROOT>/scripts/agent-hook.py finish --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE>
```

Do not wait until finish to write all gate evidence by hand. The only gate-state
writers are the `gate` and `gate-batch` hooks, which require an explicit
`SUCCESS` or `FAIL` status. The default path is a structured gate ledger at
`<TARGET_REPO>/.tao/gate-evidence.json`, bound to the current
preflight evidence hash, route fingerprint, and stable execution-capsule
fingerprint (the preflight, route, and required-document snapshot). Custom preflight evidence files
use `<preflight-stem>-gate-evidence.json` so parallel jobs do not overwrite one
another's ledger. `agent-hook.py finish` is read-only: it accepts no inline gate
evidence and never infers state from prose or mutates the ledger while it
validates completion. Removed inline input receives a migration error directing
the caller to `gate` or `gate-batch` first.

The `start` and `review` hooks record their own successful gate evidence in the
ledger. `review hook` is a hook-owned gate: generic `gate` and `gate-batch`
input must reject it regardless of the caller-supplied `source` value. The
review command additionally writes an atomic run-local review attestation bound
to the current run id, preflight hash, route fingerprint, complete worktree
fingerprint, exact review pathspec, and changed-path count. Finish must validate
that attestation and its ledger binding before accepting `review hook`; a
missing, copied, stale, or scope-mismatched attestation makes the gate missing.
Finish must revalidate the attestation after all final checks and immediately
before it reports completion. Its earlier validation only establishes that the
final checks may start; bytes changed while those checks run must fail closed.
This does not prohibit a legitimate pathspec review of an explicitly owned
slice—the exact scope is attested and may not later be widened by prose.
When `--output` is requested, keep lifecycle result files under the current
project's `.tao` root. The wrapper probes the requested parent before running
the hook, including compatibility callers that still choose another explicit
result location, so a workspace that is not writable is an immediate invocation
refusal instead of a completed review followed by a persistence traceback. Omit
`--output` when the separate diagnostic result file is not needed; the preflight,
gate ledger, attestation, and timing records remain the lifecycle evidence.
For gates that only the active agent can prove, batch every simultaneously-ready
record from the same lifecycle phase instead of spawning one shell process per
gate. Each `gate` or `gate-batch` invocation also rewrites one strong
continuation checkpoint, including current Git drift state. One phase batch
therefore preserves the same gate evidence and resumability while avoiding
repeated process startup and checkpoint scans. Do not batch evidence that is not
yet true, cross a dependency or review boundary just to reduce calls, or keep
retrying a batch after the validation-recovery rule above says to isolate the
failing gate:

```text
python3 <TAO_ROOT>/scripts/agent-hook.py gate-batch --project <TARGET_REPO> --rules <TAO_ROOT> --evidence <RUN_EVIDENCE> --gate-record '[{"gate":"cycle contract","fields":{"cycle_type":"workflow_setup","input_scope":"<safe-source-scope>","allowed_changes":"<safe-scope>","forbidden_changes":"<safe-boundary>","acceptance_criteria":"<safe-criteria>","verification":"<check>","stop_condition":"<condition>","checkpoint":"<handoff-or-next-cycle>"}},{"gate":"agentic run state","fields":{"state":"scoped","transition":"scoped -> acting","evidence":"<gate-or-command>","checkpoint":"<resume-or-handoff>","blockers":"<none-or-current-blocker>"}},{"gate":"boundary plan","fields":{"scope":"<owned-scope>","verification":"<nearest-check>"}}]'
```

Every mutating ledger path revalidates the run claim the registry holds for the
evidence file being written. Registry claim validation and ledger mutation must
share one atomic transaction. The global lock order is
`project-state -> run-registry -> gate-ledger`; all append, reset, resync, and
capsule-bind paths use
that same order. A second unlocked claim check narrows a race but is not atomic
evidence that the claim still exists when the ledger changes. The project is
derived from that file's own `.tao`
root, never from a preflight field, so a caller cannot redirect the check at a
registry that holds no claim. Writability is wider than liveness: a run that a
failed finish left `failed`, or that a repair cycle parked at
`reconcile_required`, stays writable precisely so its owner can record the
missing gate facts and rerun finish, while `completed` and `cancelled` are
closed because a settled run must not gain new evidence. When launcher-anchored
owner evidence exists, only that same process owner may append, reset, resync,
or capsule-bind the ledger; another live session is refused before it can
replace a later `FAIL` with its own `SUCCESS`. A run recording no owner keeps
its compatibility path only inside the registry's shared stale window, since
recency is the sole identity left. New top-level starts without an explicit
evidence path allocate a
run-local `.tao/runs/<opaque>/preflight.json` even when the runtime exposes no
session id, so independent ledgers are physically separated by default.
An ownership or worker-boundary refusal happens before ledger mutation. The
`gate` and `gate-batch` hooks report it as `fix_invocation_and_rerun`; no
checkpoint failed, so the caller must correct its evidence or run ownership and
must not enter `repair-verify` for that rejection.

Use this ledger to capture what happened, not to craft magic validator prose.
Finish rejects a required ledger record whose capsule fingerprint does not
match the current validated capsule. This applies to every required gate, not
only `source docs`. Ledger order is authoritative per checkpoint: a later
`FAIL` invalidates an earlier `SUCCESS`, and only a later verified `SUCCESS`
restores that gate. A later incomplete `SUCCESS` cannot fall back to an older
complete record.
If a structured entry is missing required fields, finish-check should fail and
the recovery is to complete or record the missing gate fact, not to add a vague
sentence. Use `agent-hook.py gate` for a single immediate gate and
`agent-hook.py gate-batch` for a bounded set. Keep the evidence machine-clear
instead of relying on equivalent prose or alternate key spellings. Use the
Graphify readiness fields exactly as `cli`, `skill_doc`, `runtime_links`,
`runtime_ownership`, `project_integration`, `graph`, and `query_smoke`, with
every value exactly `success`; keep
descriptive facts in separate gate evidence rather than keyword-parsing the
status. For `source docs`, say which
source-of-truth class was searched and opened before implementation and how it
affected the decision. For `documentation`, include the literal decision
(`updated`, `created`, `unchanged`, or `not applicable`), the doc path or class,
and the durable-contract reason. Add or improve structured ledger fields when
the same semantic evidence repeatedly fails manual parsing; do not keep
retrying paraphrases.

For explicit `commit` or `git_commit` routes, dirty-path surface documents stay
in `reference_docs` by default. The commit workflow's small required set and
freshness checks are sufficient unless an explicit concern, repo-local policy,
or review finding escalates a surface. This prevents an already-implemented
diff from reopening the full implementation reading and verification lifecycle.

For structured `gate-batch` records, use the field names consumed by the
ledger synthesizer. Parallel `multi-agent split decision` records require
`mode`, `reason`, `owned_scope`, `forbidden_scope`, `contract`, `acceptance`,
`integration_owner`, and `verification`; do not rename `contract` to
`contract_brief` or `acceptance` to `acceptance_checks`. `side-effect audit`
requires `scope` and `result`. A successful record-write message proves only
that the ledger entry was stored; finish-check remains the authority on whether
its fields satisfy the gate contract.

Gate and gate-batch hooks validate structured `SUCCESS` fields before writing
the ledger. Parallel multi-agent validation returns the base and parallel-only
missing fields together, rejects alias keys, and validates the structured
delegation plan before worker execution. Existing incomplete ledgers remain a
finish failure, but finish reports their full missing-field set at once so the
single repair cycle does not uncover a second hidden layer.

A later complete record for the same gate is a valid correction for a legacy
incomplete ledger entry. Once merge selects that complete replacement, it must
clear the older missing-field diagnostic; obsolete omissions must not consume
the repair cycle after the gate has actually been corrected.

Structured evidence synthesis preserves the original evidence note alongside
the canonical fields for `source docs`, `documentation impact`, and
`documentation`. This prevents an inspected/read or coverage explanation from
being lost when the ledger renders fields into validator text. Collaboration
validators treat equivalent Korean and English terms (for example `병렬` /
`parallel`, `워커` / `worker`, `소유 범위` / `owned scope`, and `검증` /
`verification`) the same way, while explicit negation such as `워커 불필요` or
`병렬 안 함` remains a serial decision and does not create a false delegation
plan requirement.

`agent-hook.py finish` runs the finish-check logic in-process. Calling
`agent-finish-check.py` directly is acceptable only as a lower-level wrapper path
when the finish hook is unavailable.

`agent-preflight.py` records the route manifest, current git status, and
VibeGuard audit result in `<TARGET_REPO>/.tao/preflight.json`.
It also records a content-free summary of accepted and promoted global lessons
from `~/.tao/` when that local store exists.
When `--request-classified` is used, it must also record
`--classification-evidence`; otherwise request intake is treated as skipped.
That evidence alone does not honor the flag: a ready and valid parent execution
capsule must back it, or the classifier evaluates `--request` as usual.
For work routes, that evidence must include a resolved-scope signal rather than
a generic `classified`, `done`, `handled`, `clarified`, or `no blockers`
marker.
`agent-finish-check.py` requires evidence for every route gate. It reuses a
current successful review's workflow validation and scoped `git diff --check`
result; otherwise it runs those checks itself. Read-only work against a path
outside Git skips the structurally unavailable diff check, while a writing task
outside Git still fails closed. It uses the task-local VibeGuard audit cache
when both the target project git state and Tao Agent OS rules git state are
unchanged. Failed VibeGuard invocations must not be cached; rerun the tool after
transient failures. Finish-check writes
`<TARGET_REPO>/.tao/finish.json`.
It also writes `gate_signals`, `missed_gates`, and
`retrospective_required`. When `retrospective_required` is true, it writes a
safe lesson candidate under `~/.tao/lessons/inbox/` when permitted.
If the route classification or stored request text requires Grill-Me, the finish
check must receive Grill-Me protocol evidence through a gate such as
`grill-me if needed=</grilling session/output evidence>`. Legacy
`question drill if needed=<evidence>` is accepted only when it still names the
Grill-Me protocol, skill, or `/grilling` session and output. Missing Grill-Me
evidence is a `🐱🔴 FAIL` signal and blocks completion until missed-gate
recovery and retrospective learning run.
Human-visible wrapper output uses only `🐱🟢 SUCCESS` and `🐱🔴 FAIL`.

Treat missing wrapper evidence as non-compliant. If the wrappers are unavailable,
the agent must still run the same underlying checks manually and report the
fallback explicitly. VibeGuard `Needs review` cannot be called complete unless
the state is reported and an explicit `--allow-vibeguard-review` reason is
recorded. Command failure, `🐱🔴 FAIL`, missing route evidence, or missing
VibeGuard output remains a blocker.
