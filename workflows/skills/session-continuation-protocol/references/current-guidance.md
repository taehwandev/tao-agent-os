---
keyflow_id: sys_session_continuation_protocol_guidance
status: review
type: human-reviewed-needed
---

# Session Continuation Protocol Guidance

This card specifies the contract. It does not implement it. Implementation is
expected to follow in a later change, and the sequencing at the end of this
document says which part lands where.

A runtime session can end without warning. The conversation is usually
recoverable by the runtime itself, but the work state is not: what the task was,
what was decided, what changed, what verification passed, and what remains. Left
to each runtime, that gap gets filled by as many resume semantics as there are
IDEs. This contract fills it once.

## Ownership Boundary

The shared library owns:

- the packet schema and its version
- atomic storage at `<TARGET_REPO>/.tao/runs/<run-id>/continuation.json`
- discovery of unfinished packets for a checkout
- HEAD, worktree, and required-doc drift verification
- takeover of a run whose owner is gone
- computing the first unfinished checkpoint
- `resume --last` and `resume --list`
- the safety boundary that keeps request content bounded and local

A runtime adapter owns only:

- calling the shared checkpoint command with content its agent already has
- invoking the shared resume command at session start
- surfacing the result to its own conversation

Anything else in an adapter is duplicated logic that will drift.

## Record Separation

```text
execution-capsule.json  -> trust, routing, required-doc and gate binding
continuation.json       -> bounded project-local work summary and latest drift snapshot
```

The packet may carry one one-way digest reference to the current content-free
preflight/capsule binding and the minimum strong state needed to detect bytes
changing after its latest checkpoint. Those values can only invalidate resume.
They cannot authorize route reuse, prove a gate, or replace the parent ledger.
The capsule never stores a continuation path, digest, schema id, generation, or
semantic field. Changing or deleting a packet must not change capsule bytes or
its binding fingerprint.

## Decision Summary

| Decision | One-line reason | Failure mode avoided |
| --- | --- | --- |
| Write initial, pre/post-mutation, and lifecycle checkpoints; Stop is optional | correctness cannot depend on an exit path that may never run | `kill -9` leaves no useful state or a gate-only packet hides hours of edits |
| Refuse every HEAD/worktree/rules/required-doc drift | decisions are valid only against the bytes that produced them | stale reasoning is silently reused as current |
| Reuse `agent_run_owner` and the registry claim transaction | owner death has one meaning system-wide | two sessions steal one run under divergent timeout rules |
| Enforce a closed, bounded local-only schema and outbound deny class | prose instructions cannot prevent dumps or exports | `notes` becomes a transcript and a generic exporter uploads it |

## Decision 1: When The Checkpoint Is Written

**Decision.** Checkpoint during work, at every durable semantic or mutation
boundary. A Stop hook is an optional final flush and never a correctness
dependency.

The common checkpoint writer is invoked at these points:

1. **Initial checkpoint:** after `start`, source-doc reading, and scoping have
   produced a usable objective, before the first mutating tool call.
2. **Before mutation:** immediately before each file-mutating tool call or
   explicitly bounded mutation batch. Record `mutation_pending`, the allowed
   path set, the mutation kind enum, and the current strong project/rules state.
3. **After mutation:** after that tool or batch succeeds. Refresh the strong
   project/rules state, compare actual changed paths with the declared bounded
   set, update changed scope and semantic work summary, then clear
   `mutation_pending`. An undeclared changed path fails the checkpoint.
4. **Material decision:** after each accepted, rejected, or superseded decision
   that changes remaining work, even when no file changed.
5. **Lifecycle transition:** after each successful `gate`, `gate-batch`,
   verification record, `review`, failure transition, and `finish`.
6. **Best-effort Stop:** a runtime Stop hook may request one final rewrite, but
   failure or absence of that hook cannot reduce the guarantees above.

One runtime adapter may coalesce adjacent mutations only when the shared
command receives the complete bounded path set before the batch starts. It may
not turn an unbounded agent session into one batch. Shell commands, formatters,
generators, notebooks, and runtime-native write tools all use the same boundary.
A mutating tool must not run until the pre-mutation rewrite succeeds.

**Reasoning.** A shutdown-time write assumes a shutdown that runs. A gate-only
write has a different version of the same defect: a session may perform hours
of edits before the next gate. Pre/post mutation checkpoints bound that gap
without pretending that every thought or terminal byte is durable. The
`mutation_pending` write also makes an interrupted tool distinguishable from an
idle agent.

**Worst-case loss.** Unrecorded reasoning since the last semantic checkpoint
and the result of at most one in-flight mutation boundary can be lost. If the
process dies before the tool writes bytes, the pending record's pre-mutation
state still matches; resume may atomically clear it and restart that same
checkpoint. If it dies after bytes change but before the post-mutation
checkpoint, the packet remains atomically intact but worktree verification
fails and resume enters `reconcile_required`. The protocol never calls those
uncheckpointed bytes verified progress.

The mutation loss bound is structural; uncheckpointed reasoning has no time
bound. Runtime wiring should therefore write a material-decision checkpoint
promptly rather than wait for the next gate.

**Failure mode avoided.** Stop-only and gate-only designs both report an older
state as current after the process dies; the latter merely makes the loss window
less obvious.

## Decision 2: What Drift Does

**Decision.** Refuse the resume. Name what moved, and direct the caller to a
fresh `start` or explicit reconciliation. Do not warn and continue, and do not
offer a `--force` bypass in version 1.

**Reasoning.** A continuation packet is a set of conclusions — this was decided,
this was verified, this remains. Every one of those conclusions was reached
against specific bytes. Resuming onto different bytes silently reuses reasoning
whose premises have changed, which is worse than starting over because it looks
like progress. This repository already fails closed in the same situation: a
stale context snapshot meeting `review` or `finish` is rejected rather than
tolerated, and the read-only lifecycle fails closed when the worktree moved
under a non-mutating claim.

**Scope of the check.** Compare four things, and report which failed:

| Signal | Source | Meaning of a mismatch |
| --- | --- | --- |
| HEAD | `git rev-parse HEAD` | the branch moved; commits landed or were rewritten |
| project worktree | content fingerprint, per `git_states_for_paths` | project bytes differ |
| rules worktree | content fingerprint, per `git_states_for_paths` | shared guidance bytes differ |
| required docs | per-path hashes from the route snapshot | the guidance the plan was made under changed |

Identity is judged by content, not by cache metadata. A file rewritten with
identical bytes is not drift, and treating it as drift makes ordinary editor
behavior look like tampering.

There is no empty-scope exception. Even a packet with no changed files may hold
a decision derived from the old HEAD or old required docs. The safe recovery is
to carry the bounded objective into a fresh `start`, recalculate the route and
required-doc manifest, and explicitly reconcile any retained changed bytes.

On mismatch the common command returns `drift_refused`, names only the changed
signal and repo-relative affected paths, and records the registry run state as
`reconcile_required`. The last valid packet remains byte-for-byte unchanged. It
does not mark any gate successful, compute a resumable checkpoint, or inject
packet prose into a runtime conversation.

**Failure mode avoided.** Warning-and-continue silently reuses conclusions whose
premises moved and makes stale reasoning look current.

## Decision 3: How Takeover Works

**Decision.** Reuse `scripts/agent_run_owner.py` directly and perform resume
claiming through the same registry transaction boundary as exclusive start
claims. Do not define a second rule.

**Reasoning.** That module already answers the question this protocol needs
answered, and answers it with the distinction that matters:

- `owner_death_is_proven(owner)` requires a POSIX host and a recorded pid before
  consulting liveness. Proof of death releases a claim immediately, at any age.
- `owner_is_gone(owner)` folds absent evidence into "gone", which is correct
  behind a timestamp window and catastrophic as an instant trigger.
- `LIVE_OWNER_GRACE_MULTIPLIER` extends the window for a live owner without
  removing it, so nothing holds a path forever.

Continuation takeover is the same question in different words: may this session
adopt a run another session started? Reimplementing it would create two answers
to one question, and the two would diverge on the first edge case. A packet
carries no owner field of its own; ownership is a property of the run record it
belongs to.

The implementation must add one atomic `claim_resume` operation rather than
call the current low-level `resume_run()` directly. The current helper only
changes `failed` or `paused` to `running`; it does not prove owner death, install
the new process owner, verify packet binding, or protect drift verification
with a generation. It is therefore not the public continuation primitive.

Observed, not merely argued: revive a run whose owner is a reaped pid and
`resume_run` returns it to `running` with that dead owner still installed.
`owner_death_is_proven` stays true on the revived record, so the next sweep
fails it again at once and the resume achieves nothing. Installing the resuming
process as the new owner is the part that makes a resume durable, and it is
exactly what the low-level helper omits.

`claim_resume` uses the registry lock and a monotonic `resume_generation`:

1. resolve the exact run and packet and reject an invalid binding;
2. apply `owner_death_is_proven`, `owner_is_gone`, and
   `LIVE_OWNER_GRACE_MULTIPLIER` exactly as the existing stale sweep does;
3. refuse a live or still-within-window unproven owner;
4. reserve the run for the new process as `resuming`, with a fresh owner and
   incremented generation;
5. capture bounded strong HEAD/worktree/required-doc state;
6. compare-and-swap the same owner, generation, HEAD, and worktree invalidation
   signature; on clean state transition to `running`, otherwise transition to
   `reconcile_required`.

The two-phase generation check prevents two resumptions from both winning while
avoiding an unbounded filesystem scan under the registry lock. If the
generation or owner changes between capture and commit, the attempt loses and
must not retry silently.

Every checkpoint rewrite performs the same owner/generation compare-and-swap.
An old owner that remained alive past the grace ceiling cannot overwrite a
newer's packet. `resuming` is an active claim state and is swept by the same
age-aware owner policy, so a claimant killed during validation cannot strand the
run.

**Consequence for discovery.** A packet whose run has a live owner is listed but
not resumable. `resume --last` targets the newest unfinished packet for the
current checkout; if that exact packet is live, unproven, drifted, or invalid,
the command refuses. It never skips to an older task.

**Failure mode avoided.** A second takeover rule or a bare state flip can steal
a live run, resurrect stale evidence, or let two sessions believe they own the
same continuation.

## Decision 4: How The Content Boundary Is Enforced

**Decision.** Make both properties checkable rather than instructed. A
prohibition an implementation can violate silently is not a boundary.

### Checkable Project-Local, Never-Sync Boundary

Version 1 makes this a Tao-owned boundary with four independently testable
controls:

1. **Canonical containment.** Resolve the project root and packet parent without
   following a packet or run-directory symlink. The only accepted path is
   `<TARGET_REPO>/.tao/runs/<run-id>/continuation.json`, where `<run-id>` is the
   exact opaque registry id. Reject alternate names, `..`, absolute path
   fragments, symlinked parents, hard links, and any path outside the selected
   project.
2. **Git-local precondition.** In a Git workspace, the writer and resume reader
   must prove the exact path is ignored by Git before accepting the packet. A
   tracked or merely untracked-but-not-ignored packet is `local_boundary_failed`,
   not a warning. In a supported non-Git workspace, the equivalent repo-local
   state policy must explicitly classify `.tao/runs/` as local-only.
3. **Outbound deny rule.** Every Tao-owned sync, export, publish, IPC,
   telemetry, global-lesson, execution-capsule, diagnostic, and artifact
   collection boundary rejects both the packet schema id and paths under
   `.tao/runs/*/continuation.json`. Absence from an allowlist is necessary but
   not sufficient; a negative test must attempt each outbound class and observe
   rejection.
4. **Private local persistence.** Create the run directory with owner-only
   permissions where the host supports them, write a mode `0600` temporary file
   in that directory, `fsync` the file, atomically replace the target, and
   `fsync` the directory. A read rejects non-regular files, unexpected link
   counts, insecure modes on POSIX, and files larger than the schema byte cap.

`storage_class` is a fixed schema value,
`project_local_never_sync`, so boundary checks are inspectable. It is a label,
not proof; the path, Git, outbound, and filesystem checks provide the proof.

Tao cannot promise that unrelated software with arbitrary filesystem access
will never read or upload a local file. The enforceable promise is narrower and
explicit: no Tao-owned path writes the packet outside its canonical local
location, admits it to Git, or sends it through a Tao-owned outbound boundary.

### Structurally Bounded Content

The schema and common writer, not runtime prose, enforce minimization:

- `additionalProperties: false` at the root and every nested object;
- a maximum UTF-8 encoded packet size of 24 KiB;
- a maximum nesting depth of 5 and maximum aggregate prose payload of 4 KiB;
- no generic `summary`, `notes`, `context`, `metadata`, `payload`, `extensions`,
  or arbitrary key/value field;
- no prompt, response, message, transcript, log, command line, command output,
  diff, source text, environment value, URL with credentials, or secret field;
- all prose is single-line NFC-normalized UTF-8 without NUL, C0/C1 controls,
  tabs, line breaks, or bidi override/isolate characters; it is rejected rather
  than truncated and limited by item count, character count, and aggregate
  bytes;
- paths are normalized repo-relative POSIX paths, never absolute paths, and
  never point into `.git`, `.tao`, another repository, or a rules root outside
  the selected project;
- identifiers are bounded safe slugs or exact catalog/ledger names;
- verification stores a safe check category and an evidence hash/reference,
  never the invoked command or its output;
- a local secret validator rejects known credential forms, private-key
  delimiters, credential-bearing URLs, JWT-like triples, and high-confidence
  token formats before the atomic write.

Validation errors return a JSON pointer and stable rule id only. They never echo
the rejected value, and a failed rewrite leaves the previous valid packet
unchanged.

Schema and pattern validation cannot prove that a 280-character sentence
contains no sensitive business fact. That residual risk is why the packet is
local-only and why prose fields stay few and short. The design does not make the
false claim that a JSON schema can understand every secret.

**Failure mode avoided.** Without both the outbound boundary and a closed,
bounded schema, a harmless-looking `notes` field can become a transcript dump
that a later generic state exporter uploads.

## Packet Schema

Version `1`. Unknown fields and unknown enum values are invalid. Every maximum
is inclusive.

### Root

| Field | Type and bound | Purpose |
| --- | --- | --- |
| `schema_version` | integer, exactly `1` | reader compatibility |
| `storage_class` | enum, exactly `project_local_never_sync` | outbound deny classification |
| `run_id` | 32 lowercase hex characters | exact registry record and directory |
| `generation` | integer, `0..2^53-1` | atomic rewrite and resume CAS |
| `phase` | enum | `scoped`, `acting`, `verifying`, `reviewing`, `blocked`, `reconcile_required`, `done` |
| `binding` | closed object | one-way reference to content-free trust state |
| `drift` | closed object | latest strong project/rules state and required-doc digest |
| `work` | closed object | bounded semantic continuation content |
| `checkpoint` | closed object | pending mutation and last completed lifecycle point |
| `updated_at` | RFC 3339 UTC timestamp | snapshot time |

There is no `owner`, `holder`, `session_id`, or process field. The run registry
owns liveness and exclusive claims.

### `binding`

| Field | Type and bound |
| --- | --- |
| `kind` | enum: `preflight_snapshot` or `execution_capsule` |
| `filename` | run-directory basename, at most 80 safe characters |
| `file_sha256` | lowercase sha256 |
| `binding_sha256` | lowercase sha256 |

The common implementation resolves the current route, request fingerprint,
required-doc manifest, and gate order from this content-free authority. The
packet does not duplicate those fields.

### `drift`

| Field | Type and bound |
| --- | --- |
| `project` | existing strong Git or directory state object |
| `rules` | existing strong Git or directory state object |
| `required_docs_sha256` | lowercase sha256 over the ordered trust-record snapshot |

Use the existing `git_states_for_paths` strong state. The required-doc digest is
only an invalidation cache; the content-free trust record retains the actual
path/hash/size records and remains authoritative. Do not invent a weaker
fingerprint.

A normal checkpoint never rebases the trust record or required-doc digest to
current bytes. A required document changed during the run remains drift until a
fresh `start`, or the existing validated documentation/repair receipt protocol,
creates a new authoritative binding. This prevents the writer from blessing its
own stale guidance.

### `work`

| Field | Type and bound |
| --- | --- |
| `objective` | single-line text, `1..280` characters |
| `non_goals` | at most 4 single-line text items, each `1..160` characters |
| `decisions` | at most 12 closed `{id, status, text}` records |
| `changed_scope` | at most 64 normalized relative path records |
| `inspected_scope` | at most 64 normalized relative path records |
| `verification` | at most 32 closed verification records |
| `remaining_work` | at most 12 closed `{checkpoint, action}` records |
| `blockers` | at most 4 single-line text items, each `1..280` characters |

A decision `id` is a safe slug of at most 40 characters; `status` is
`accepted`, `rejected`, or `superseded`; `text` is single-line and at most 280
characters. A remaining-work `checkpoint` is an exact route gate name or safe
slug of at most 64 characters; `action` is single-line and at most 280
characters.

Changed and inspected scope records contain only `{path, role}`. `role` is
`modified`, `created`, `deleted`, `renamed`, or `inspected`; rename records use
closed `{from, to, role}` instead. They contain no diff or source bytes.

A verification record contains:

| Field | Type |
| --- | --- |
| `id` | safe slug, at most 40 characters |
| `kind` | enum: `unit`, `integration`, `compile`, `lint`, `workflow_validate`, `vibeguard`, `graph`, `review`, `manual` |
| `result` | enum: `success`, `fail`, `skipped` |
| `evidence_sha256` | lowercase sha256 or `null` |
| `completed_at` | RFC 3339 UTC timestamp or `null` |

There is deliberately no command string or output field.

### `checkpoint`

| Field | Type and bound |
| --- | --- |
| `last_completed` | exact gate name or safe slug, or `null` |
| `first_unfinished` | exact gate name or safe slug, or `null` |
| `mutation_pending` | closed pending-mutation record or `null` |

The pending-mutation record contains `kind` from
`create|update|move|delete|generate|format`, at most 64 normalized relative
paths, the pre-mutation project/rules state hashes, and `started_at`. It contains
no requested edit text, tool arguments, command, or output.

`first_unfinished` is a cached display value. The shared resume implementation
must recompute it from the current route's ordered required gates and the
parent-owned ledger, then require equality. Packet prose never determines
checkpoint authority.

The computation is deterministic:

1. load the exact ordered gate manifest from the bound trust record;
2. for each gate, read the latest ledger entry bound to that same trust record;
3. return the first gate with no entry or latest status `FAIL`;
4. preserve the existing first-failed repair checkpoint even when later,
   dependent evidence exists;
5. if every gate is `SUCCESS` but the lifecycle finish record is absent, return
   `finish`;
6. return `null` only when finish is successful and the registry run is
   `completed`.

Advisory `remaining_work` may explain the checkpoint but cannot move it.

## Storage

Path: `<TARGET_REPO>/.tao/runs/<run-id>/continuation.json`.

The run-id directory is the existing isolated-run convention, so a packet is
automatically scoped to one run and cannot collide with a concurrent session.

The common writer validates the complete object before touching the target,
serializes canonical JSON, enforces the 24 KiB limit, writes a unique mode
`0600` temporary file in the same directory, flushes it, and atomically
replaces the target. On platforms that support it, flush the directory entry as
well. Never write in place. A failure before replacement leaves the previous
valid generation byte-for-byte intact.

A packet is rewritten in full at each checkpoint. It is a snapshot, not a log;
append-only history belongs in the gate ledger, which already has it.

Readers validate containment, file type, mode, size, schema, generation, run
binding, and packet hash before returning any semantic field. Invalid packets
are listed as invalid by opaque run id; their prose is not rendered.

## Run And Packet State Machine

Keep claim state and semantic state separate:

- the run registry owns exclusive evidence-path claims, owner liveness, resume
  generation, and terminal run state;
- the continuation packet owns bounded semantic phase, changed scope,
  verification summary, and checkpoint display state;
- the execution capsule owns trust/routing/gate reuse and is never updated from
  packet prose.

Required transitions:

| Event | Registry | Packet | Result |
| --- | --- | --- | --- |
| initial checkpoint | `running`, current owner | `scoped` | resume candidate exists |
| pre-mutation checkpoint | `running`, current owner | `acting`, `mutation_pending` set | interruption is detectable |
| post-mutation checkpoint | `running`, current owner | `acting`, pending cleared, state refreshed | bytes and summary agree |
| verification/review | `running`, current owner | `verifying` / `reviewing` | result recorded without command output |
| live-owner resume attempt | unchanged | unchanged | `live_owner_refused` |
| dead/stale owner claim | `resuming`, new owner, generation + 1 | unchanged during capture | one claimant owns validation |
| clean resume validation | `running`, new owner | phase preserved; an unchanged pending mutation is atomically cleared | `ready` with first unfinished checkpoint |
| drift or changed pending mutation | `reconcile_required`, new owner | last valid packet unchanged | no automatic resume |
| finish | `completed` | `done`, no unfinished checkpoint | omitted from candidates |
| cancel | `cancelled` | unchanged or local tombstone | omitted from candidates |

A recorded failed gate is not erased. When drift is clean, it is the first
unfinished checkpoint and the resumed session re-enters the existing
retrospective/repair contract with its current repair-cycle count. A terminal or
unsafe failure remains blocked.

## Discovery And CLI Contract

The logical CLI surface is:

```text
tao resume --list
tao resume --last
```

The installed stable launcher may expose these as aliases, but both call the
same common implementation. A runtime adapter does not parse the filesystem.

`tao resume --list` is read-only. It enumerates canonical packets for the
current selected checkout only and reports:

- opaque run id and route command;
- bounded objective and updated time;
- recomputed first unfinished checkpoint;
- packet validity;
- `clean`, `head_drift`, `worktree_drift`, `required_doc_drift`, or
  `pending_clean` / `pending_changed`;
- owner state.

Holder state is one of:

| State | Meaning | Resumable |
| --- | --- | --- |
| `live` | recorded owner is alive inside its grace contract | no |
| `dead_proven` | recorded owner existed and death is proven | yes |
| `unproven_wait` | no checkable owner evidence and timestamp window remains | no |
| `unproven_expired` | the bounded timestamp fallback expired | yes |

Completed and cancelled runs are not unfinished candidates and never appear as
`free`.

`tao resume --last` selects the newest unfinished packet for this checkout,
then attempts `claim_resume`. It never skips a blocked newest packet to resume
an older task. On success it returns a closed machine-readable result containing
the opaque run id, canonical evidence locator, route command, bounded work
object, recomputed checkpoint, new generation, and `ready`. On refusal it
returns no semantic work object.

Stable result codes:

| Result | Meaning | State change |
| --- | --- | --- |
| `ready` | exact newest packet claimed and drift-clean | run becomes `running` |
| `not_found` | no unfinished packet in this checkout | none |
| `live_owner_refused` | existing owner still holds the run | none |
| `owner_unproven_wait` | timestamp fallback has not expired | none |
| `drift_refused` | HEAD, worktree, rules, required docs, or pending-mutation state mismatch | `reconcile_required` |
| `invalid_packet` | containment, schema, binding, or integrity failure | none |
| `local_boundary_failed` | ignored/local-only or filesystem boundary is not proven | none |
| `claim_lost` | owner or generation changed during validation | none |

Human output may add repair guidance, but JSON output uses only these result
codes and bounded fields. Exit status is zero only for `ready` and a successful
`--list`; every refusal is nonzero.

## Runtime Adapter Requirements

An adapter supplies three pieces of wiring and nothing else:

1. **Initial and semantic checkpoint invocation.** Supply only the bounded
   `work` fields its agent already knows. The common command validates prose and
   derives every fingerprint, path role, route field, gate state, and
   generation.
2. **Mutation hook wiring.** Call the common pre-mutation command with a bounded
   path set and mutation enum, then the post-mutation command after success.
3. **Session-start invocation.** Call the common resume command. Inject a work
   brief into the conversation only when the common result is `ready`.

Adapters must not: define schema, choose the storage path, implement drift
checks, decide takeover, select a different packet, weaken result codes, read
packet JSON directly, or render an invalid packet's prose.

Runtime-native conversation continuation remains separate. Claude, Codex, or
another runtime may restore its own conversation, but Tao's packet is the
authority for project work state and may be used without the old conversation.

Known per-runtime constraint: `scripts/claude_pretool_gate.py` resolves evidence
at exactly one hardcoded path, `.tao/preflight.json`: `evidence_mtime`,
`deny_reason`, and `recorded_session_id` all construct
`root / STATE_DIR / PREFLIGHT_NAME`. It cannot see a run started with an
isolated `--evidence` path.

The later Claude adapter must replace that selection with a common, read-only
active-session binding resolver. The resolver returns one already-claimed
evidence path for the exact runtime session and resume generation; it does not
scan for the newest file and the Claude gate does not learn takeover or drift
policy. This is a thin-adapter repair, not a Claude-specific resume design.

## Retention And Checkout Scope

- A packet is pruned in the same atomic maintenance decision as its run record.
  It never intentionally outlives the record that owns liveness.
- `--list` and `--last` operate only on the currently selected project root and
  checkout. Another Git worktree has different mutable state and is not a
  candidate even when it shares object storage.
- A failed gate remains resumable only at that failed checkpoint and only under
  the existing single repair-cycle rules. Resume does not convert failure to
  success.

## Verification

Every implementation stage carries its own negative controls. Two are
non-negotiable, because they are the reason this feature exists:

- **Resume after `kill -9`.** Start a run, write an initial or post-mutation
  checkpoint, kill the owner without a shutdown path, and resume from the first
  unfinished checkpoint. Negative control: disable the during-work writer and
  prove the candidate disappears or remains older.
- **Refusal after worktree drift.** Write a checkpoint, change tracked,
  untracked, staged, deleted, and renamed bytes one case at a time, and attempt
  resume. Negative control: disable strong drift comparison and prove the test
  incorrectly becomes `ready`.
- **Interrupted mutation.** Kill after the pre-mutation checkpoint but before
  bytes change; resume must clear the pending record and restart the same
  checkpoint. Kill after bytes change but before post-mutation; the result must
  be `reconcile_required`, never `ready`.
- **Owner controls.** A live owner and an unproven owner inside the fallback
  window are refused; proven death releases immediately; unproven ownership
  releases only after the shared bound; even a still-live-looking owner releases
  at the existing far grace ceiling. Mutating any one owner rule must make a
  control fail.
- **Concurrent claim.** Two resume attempts for one generation produce exactly
  one owner; the loser returns `claim_lost`.
- **Generation and capture races.** A previous-generation owner cannot write a
  late checkpoint; worktree mutation between strong capture and resume CAS
  prevents `ready`; a killed `resuming` owner is recoverable under the shared
  age-aware policy.
- **Required-doc and HEAD drift.** Each independently refuses, including when
  changed scope and verification are empty. A normal checkpoint cannot rebase
  changed required docs without a fresh start or validated receipt.
- **Atomic write.** Terminate between temporary-file flush and rename; the old
  packet remains valid and no partial target is readable.
- **Schema boundary.** Newline prose, a 281-character item, a 13th decision, a
  4-KiB-plus aggregate prose payload, a 24-KiB-plus packet, unknown field,
  transcript/log/command-output field, secret-shaped value, absolute path, path
  traversal, and symlinked run directory are each rejected.
- **Never-sync boundary.** Make the exact packet path tracked or not ignored,
  and attempt every Tao-owned export, sync, IPC, telemetry, capsule, lesson,
  and publish boundary. Each attempt must fail without rendering packet prose.
- **Claude isolated evidence.** Bind a resumed session to a run-local preflight
  path and prove the edit gate accepts only that exact session/path/generation;
  using the old `.tao/preflight.json` must not unlock it.
- **Read-only discovery.** `--list`, including drift and liveness inspection,
  leaves registry, packet, ledger, and worktree bytes unchanged.

## Implementation Sequencing

PR #6 (`feat/runtime-fork-backport`) is an open, unmerged prerequisite. Merge it
first; this contract does not redesign its exclusive claims or owner-liveness
rules. Then split implementation so that one runtime's constraint cannot block
the common protocol:

1. common schema/validator, atomic storage, during-work checkpoint commands,
   registry `claim_resume`, drift verification, state machine, discovery,
   retention, and `tao resume --last` / `--list`, with no runtime adapter;
2. the Claude adapter alone, including exact active-session evidence resolution
   for run-local preflight paths;
3. Codex and AGY adapters, each thin wiring over the same commands.

Each stage ships its own negative controls. A stage that adds capability without
a control proving the capability can fail has not been verified.

## Migration And Compatibility

- Do not synthesize continuation content from transcripts, logs, shell history,
  command output, prompts, responses, or global lessons.
- Existing packet-less registry entries may appear in `--list` as
  `legacy_no_packet` by opaque run id, but `--last` never resumes them. Recovery
  is a fresh `start`.
- Registry schema migration must add the resume generation and new transient
  states without converting a live legacy run to free. Unknown or malformed
  owner evidence retains the same bounded timestamp fallback from PR #6.
- The existing `resume_run()` state flip remains internal compatibility code
  until callers migrate; the public resume command never uses it without the
  new owner/binding/drift transaction.
- Existing default `.tao/preflight.json` runs remain readable when their packet
  binds that exact evidence. New isolated runs use their run-local locator. No
  adapter may guess between them by modification time.
- A future packet schema version requires an explicit reader migration. Newer
  packets fail closed; older valid packets are migrated in memory, validated,
  and atomically rewritten only after a successful claim.

## Stop If

- The current run is not eligible under the exact age-aware PR #6 owner policy;
  this includes a live owner inside its shared grace ceiling and unproven
  ownership inside the bounded fallback window.
- HEAD, worktree, rules, required-doc, pending-mutation, or packet binding
  verification fails.
- `schema_version` exceeds the reading implementation.
- The canonical local-only path, ignored-state, filesystem, or outbound deny
  boundary cannot be proven.
- A free-text field exceeds its cap; reject rather than truncate.
