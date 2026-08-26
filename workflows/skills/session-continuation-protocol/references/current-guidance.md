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

## Decisions

`references/decisions.md` covers the four: when the checkpoint is written,
what drift does, how takeover works, and how the content boundary is
enforced.

## Packet Contract

`references/packet-contract.md` covers the schema, storage, the run and
packet state machine, the discovery and CLI contract, and what a runtime
adapter must provide.

## Retention And Checkout Scope

- A packet is pruned in the same atomic maintenance decision as its run record
  wherever one is taken. It still outlives that record in one case the bound
  makes unavoidable: the run history keeps a fixed number of records, so a
  packet whose record was displaced remains on disk. That packet is withdrawn
  from candidacy and counted rather than listed, and removing it is the
  maintenance below.
- `--list` and `--last` operate only on the currently selected project root and
  checkout. Another Git worktree has different mutable state and is not a
  candidate even when it shares object storage.
- A failed gate remains resumable only at that failed checkpoint and only under
  the existing single repair-cycle rules. Resume does not convert failure to
  success.

### Deleting Run State

The store grows: one directory per run, and in an integrated checkout one of
them can hold a copy of the repository. Clearing it is ordinary maintenance,
but it is destructive and other sessions are working the same checkout, so the
decision has a shape.

**Decide by the registry binding, never by the directory name.** A run's
evidence directory is named by whatever the caller passed, so a name is not a
run id. Matching names classifies a session's own open runs as orphans; on the
checkout this rule was written from, that would have deleted two live runs
belonging to another agent. Read each directory's evidence and ask the registry
which record binds it.

Removable:

- no record binds it -- claiming returns `not_found` and checkpointing
  `unknown_run`, so no session can reach it;
- the record that binds it is settled, `completed` or `cancelled`.

Never removable:

- a record that is open, or `failed` or `reconcile_required` -- both are states
  a run is recovered from, and recovery needs its record and its evidence;
- anything touched inside the registry's shared stale window -- the same age
  the owner policy uses -- whatever the registry says, because a session may be
  between creating its directory and registering the run, and no record exists
  to speak for it yet;
- anything outside the run store: the registry itself, and tracked content such
  as `.tao/skills`, which the state directory's own ignore file keeps.

**Show the decision before taking it.** A dry run names every directory that
will be kept and why, so the caller approves a rule rather than a count.

**Prove it afterwards** by what did not move: the registry file byte-identical,
tracked state intact, every kept directory present, and the current session
still resolving its own run evidence.

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
  then attempt both the fixed packet storage-class marker and canonical packet
  path at every Tao Agent OS-owned sync, export, publish, IPC, telemetry, global-lesson,
  execution-capsule, diagnostic, and artifact boundary. Each attempt must fail
  without rendering packet prose.
- **Claude isolated evidence.** Bind a resumed session to a run-local preflight
  path and prove the edit gate accepts only that exact session/path/generation;
  using the old `.tao/preflight.json` must not unlock it. Bind a parent and
  isolated worker to the same runtime session and prove each resolves only in
  its launcher-owned scope; a malformed or foreign worker hint must fail without
  parent fallback, while two parent-scope matches remain refused. Instrument
  parent discovery so the registry and candidate tree are each traversed once.
- **Read-only discovery.** `--list`, including drift and liveness inspection,
  leaves registry, packet, ledger, and worktree bytes unchanged.
- **Reuse rendering.** A clean resume with completed source-doc reading,
  inspected scope, accepted decisions, and successful verification returns and
  renders each as reusable evidence. A source-doc gate that has not passed is
  marked `not_recorded`. A success followed by mutation is invalidated and is
  not rendered after a clean resume; failed or skipped verification is never
  promoted to success. Every owner, drift, invalid-packet, local-boundary, and
  claim-loss refusal renders neither saved work nor reuse advice.

## Implementation Sequencing

PR #6 (`feat/runtime-fork-backport`) is an open, unmerged prerequisite. Merge it
first; this contract does not redesign its exclusive claims or owner-liveness
rules. Then split implementation so that one runtime's constraint cannot block
the common protocol:

1. common schema/validator, atomic storage, during-work checkpoint commands,
   registry `claim_resume`, drift verification, state machine, discovery,
   retention, and `tao-hook resume --last` / `--list`, with no runtime adapter;
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
- Same-runtime lifecycle closeout is narrower than public continuation. When
  the evidence still binds the exact runtime name and stable session id, a
  later lifecycle hook may atomically replace a proven-dead process owner and
  continue gate/finish work for that same run. This does not expose saved work,
  bypass drift validation, or make `legacy_no_packet` eligible for `--last`.
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
