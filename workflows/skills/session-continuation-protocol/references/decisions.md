---
keyflow_id: sys_session_continuation_decisions
status: review
type: human-reviewed-needed
---

# Session Continuation Decisions

Use when asking why the continuation protocol behaves as it does: when a
checkpoint is written, what drift does, how takeover works, and how the
content boundary is enforced. For what an implementer must build, use
`references/packet-contract.md`; for the ownership boundary, retention, and
verification, `references/current-guidance.md`.

## Decision Summary

| Decision | One-line reason | Failure mode avoided |
| --- | --- | --- |
| Write initial, pre/post-mutation, and lifecycle checkpoints; Stop is optional | correctness cannot depend on an exit path that may never run | `kill -9` leaves no useful state or a gate-only packet hides hours of edits |
| Refuse every HEAD/worktree/rules/required-doc drift | decisions are valid only against the bytes that produced them | stale reasoning is silently reused as current |
| Surface reusable inspected scope and current-state verification on `ready` | a clean drift check proves the saved premises still match, while post-mutation invalidation prevents an older pass from crossing an edit | a resumed agent rereads the same docs, repeats the same analysis, and reruns the same tests only to rebuild context |
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
   `mutation_pending`. An undeclared changed path fails the checkpoint. The
   close rejects any caller-supplied `work.verification` field and clears
   inherited verification; fresh checks belong to a later lifecycle checkpoint.
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

**What that blocking is for, and where it stops.** Holding the tool back is how
a mutation is kept from running against a checkpoint that would misdescribe it.
That reasoning needs a checkpoint capable of being wrong. Where none can be
written at all, blocking protects nothing and costs the session the editor it
would take to fix the cause, so these are skips and not refusals:

| Case | Why no checkpoint exists |
| --- | --- |
| storage the packet cannot legally live in | the state root is not yet Git-ignored, so the write is correctly refused |
| the adapter module is missing | a broken install, not a policy violation |
| the edit is outside the project | changed scope is project-local by definition |
| an open pending whose bytes never moved | its tool did not run; supersede it, and refuse only once bytes have moved |

This is the rule the lifecycle already follows when it reports `checkpoint:
skipped; no packet is reachable` and continues. An adapter that is stricter at
the tool boundary than the protocol is at its own gates is not being safe. The
first four rows were each shipped as a hard denial of every subsequent edit;
the last one meant a single declined permission prompt ended a session's
ability to edit anything.

Whoever opens the run establishes the storage precondition, rather than leaving
the first writer to discover it is absent. `start` creates the state root
already ignored, and leaves an existing ignore file alone.

The post-mutation side never blocks. It runs after the bytes landed, so a
refusal there cannot prevent the write; it only reports a mutation that
succeeded as failed. An unclosed bracket is already handled without blocking
anything: the pending record survives, worktree verification fails against it,
and resume enters reconciliation.

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
not resumable. `resume --last` targets one unfinished packet for the current
checkout -- the newest, or the one `--run-id` names -- and if that exact packet
is live, unproven, drifted, or invalid, the command refuses. It never skips to
an older task. Naming the packet chooses the candidate only; the owner and
generation checks still decide whether the claim is allowed, so naming another
session's live run is refused rather than granted.

**Failure mode avoided.** A second takeover rule or a bare state flip can steal
a live run, resurrect stale evidence, or let two sessions believe they own the
same continuation.

## Decision 4: How The Content Boundary Is Enforced

**Decision.** Make both properties checkable rather than instructed. A
prohibition an implementation can violate silently is not a boundary.

### Checkable Project-Local, Never-Sync Boundary

Version 1 makes this a Tao Agent OS-owned boundary with four independently testable
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
3. **Outbound deny rule.** Every Tao Agent OS-owned sync, export, publish, IPC,
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

Tao Agent OS cannot promise that unrelated software with arbitrary filesystem access
will never read or upload a local file. The enforceable promise is narrower and
explicit: no Tao Agent OS-owned path writes the packet outside its canonical local
location, admits it to Git, or sends it through a Tao Agent OS-owned outbound boundary.

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

