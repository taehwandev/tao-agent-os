---
keyflow_id: sys_session_continuation_packet_contract
status: review
type: human-reviewed-needed
---

# Session Continuation Packet Contract

Use when writing or reading a continuation packet: its schema, where it is
stored, the run and packet state machine, the discovery and CLI contract,
and what a runtime adapter must provide. For why these choices were made,
use `references/decisions.md`.

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

This card originally called the run-id directory an existing convention. It was
not: `register_run` minted an opaque id unrelated to the evidence path, so no
real run could satisfy the writer's containment check and the whole protocol
would have shipped inert. A run started with evidence at
`<TARGET_REPO>/.tao/runs/<32-hex>/preflight.json` now *adopts* that directory
name as its run id, which costs nothing because the name is already an opaque
per-lifecycle token, and makes the packet reachable from the trust record it
binds to. Any other evidence path keeps a minted id and simply has no packet;
the lifecycle says so rather than failing.

Saying so was not enough. 45 of 48 run directories in the reference checkout
were named readably -- by date, by task -- so every one of those runs recorded
no checkpoint and none of them could be resumed, while each hook reported the
skip in a sentence that named the wrong cause. A caller who creates
`.tao/runs/<name>/` has asked for a per-run directory, so `start` now refuses a
name that is not a 32-hex run id and says how to get one. The refusal is
narrowed to that shape: the default `.tao/preflight.json` and worker paths under
`.tao/workers/` still have no packet by design, and later hooks never refuse, so
a run already begun under an unbindable name can still review and finish. An id already present in the registry
is never adopted a second time, since two records sharing one opaque id would
make "the run" ambiguous for every later lookup.

A start does not always begin a run. When the runtime session already owns
one, the evidence resolver adopts it, and an `initial` checkpoint is refused
whenever a valid packet exists -- which for an adopted run is always. Because
the refusal is non-blocking, the start reported success while the packet stayed
bound to the HEAD of the earlier start, and a later `resume` called that
`head_drift` and rendered none of the saved work. An adopted run is the same run
continuing, so its start writes a `lifecycle` refresh instead, carrying no work:
the objective a start would write is the route enum, and overwriting a recorded
one with that would lose exactly what the refresh preserves.

Because the directory is per-lifecycle, a packet is scoped to one run and
cannot collide with a concurrent session.

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
| newer same-session parent start, after claim promotion | older exact active run instance becomes `cancelled`; terminal, rebound, or newly adopted run stays unchanged | unchanged | old leaked parent claim is omitted without overwriting a newer result |
| finish | `completed` | `done`, no unfinished checkpoint | omitted from candidates |
| cancel | `cancelled` | unchanged or local tombstone | omitted from candidates |

A recorded failed gate is not erased. When drift is clean, it is the first
unfinished checkpoint and the resumed session re-enters the existing
retrospective/repair contract with its current repair-cycle count. A terminal or
unsafe failure remains blocked.

### Fresh Evidence Reuse

A `ready` resume is also a positive reuse decision. The common result must
derive a content-free reuse summary from the already validated packet and state
that recorded inspected scope, accepted decisions, and current-state successful
verification remain reusable. Required-document reading is reusable only when
the authoritative `source docs` gate already passed; otherwise the summary
marks it `not_recorded` (or `not_applicable` when the route has no required
documents). Runtime adapters must surface that summary instead of showing only
the objective and remaining work.

Reuse means "do not repeat work merely to reconstruct context." It does not
turn historical evidence into a permanent pass. Every successful verification
record is invalidated by the next completed mutation checkpoint; a later check
must explicitly repopulate it against the new bytes. A `post_mutation` work
update containing `verification`, including an empty list, is rejected rather
than silently discarded; the caller closes the mutation first and records a
later completed check separately. Rerun or replace affected evidence when
required docs or HEAD drift, an external system has its own freshness
requirement, or the remaining acceptance boundary requires a different check.
A request for additional confidence should prefer an orthogonal check or
negative control over an identical test-suite run against identical bytes.

The reuse summary contains only bounded counts, safe ids and enums already
accepted by the continuation schema. It never adds commands, output, prompts,
responses, logs, diffs, or inferred verification. A refusal returns neither the
work object nor reuse advice, so no adapter can accidentally render stale saved
work after drift.

## Discovery And CLI Contract

The logical CLI surface is:

```text
tao-hook checkpoint --checkpoint-kind <initial|pre_mutation|post_mutation|decision|lifecycle|stop>
  [--phase <phase>] [--last-completed <checkpoint>]
  [--mutation-kind <enum> --mutation-path <relative-path> ...]
  [--work-stdin]
tao-hook resume --list
tao-hook resume --last [--run-id <run-id>]
tao-hook cancel --evidence <SOURCE_PREFLIGHT> \
  --replacement-evidence <COMPLETED_LINKED_WORKTREE_PREFLIGHT>
```

The installed stable launcher may expose these as aliases, but all call the
same common implementation. A runtime adapter does not parse the filesystem.

The `start` hook now says this in its own output whenever the run has a
reachable packet. It had to: this command was named only here, in a reference a
work route does not require, so a lifecycle followed faithfully produced packets
whose `objective` was the route enum and whose every other field was empty --
bound correctly, and useless to resume.

What it prints is the whole command, including `--checkpoint-kind`, and the
work object's shape read from the validator: which fields are arrays, how many
entries each takes, and what an entry looks like. The command occupies its own
line, uses the installed launcher's absolute path, and shell-quotes the concrete
project, rules, and run-evidence paths. `work.json` is the only caller-provided
input, through the visible stdin redirection. Explanatory words and path
placeholders never appear inside the command line, so it can be copied without
editing. Naming the fields was not enough, and neither was naming their enums --
following the earlier wording still failed twice, once on the missing required
flag and once on `non_goals` being an array rather than a line. A test now takes
the command out of a real start's output and executes that complete line
unchanged.

`--work-stdin` accepts one partial closed `work` object on stdin. It never
accepts work prose as command-line arguments, so semantic state does not move
into shell history or process listings. Unknown fields, including `prompt`,
`transcript`, `summary`, `notes`, `command`, and `log`, are refused without
echoing their values. `pre_mutation` is strict: the command fails unless the
caller supplies an exact run-local evidence binding, mutation enum, and bounded
relative path set. Lifecycle callers may still use their separate best-effort
wrapper after their own gate outcome is already decided.

`tao-hook resume --list` is read-only. It enumerates canonical packets for the
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

A packet is a candidate only while the registry still records its run. The
registry keeps a bounded run history, and a packet can outlive the record
pruned from under it, but a claim compares an owner and a generation that are
then gone: claiming returns `not_found` and checkpointing returns
`unknown_run`. The bound drops settled records before open ones, so this is
the state of runs finished long ago rather than of work still in progress.
Listing such a packet as `free` offers work nobody can take and pays a drift
verification to offer it, which is what makes an old checkout's listing slow.
They are reported as a count of packets whose run the registry no longer
records -- withdrawn from candidacy, not hidden, because a packet that exists
and can never be resumed is retention debt worth seeing.

`tao-hook resume --last` selects the newest unfinished packet for this checkout,
then attempts `claim_resume`. It never skips a blocked packet to resume an older
task. `--run-id` names the candidate instead, which is what a checkout worked by
several concurrent sessions needs: the newest slot there belongs to whichever
session wrote last, so a returning session almost never finds its own work in
it, and refusing to substitute -- correct on its own -- otherwise leaves that
session no way to reach its run at all. A named run that is not an unfinished
candidate is `not_found`; it never falls through to the newest. `--run-id` is
rejected with `--list`, which reports every unfinished run and filters nothing.
On success it returns a closed machine-readable result containing
the opaque run id, canonical evidence locator, route command, bounded work
object, recomputed checkpoint, new generation, a ready-only content-free reuse
summary, and `ready`. Human output reports required-document status, reusable
inspected scope, accepted-decision ids, and current-state
successful-verification ids so an agent does not repeat them to rebuild context.
On refusal it returns no semantic work object or reuse advice.

An adapter resuming automatically at session start names its own run rather
than taking the newest. The runtime session binding identifies it, and a
restart keeps the session id, so the run bound to that session is the work it
left behind. Where no run is bound, the only unfinished packet is still not a
guess, but several are: the adapter then claims nothing and reports the opaque
ids so the caller can name one. Automatic resume is the same substitution
hazard as `--last`, arriving without anyone asking, and the owner check does
not cover it -- that check refuses a live owner, while two sessions that both
stopped leave two free packets.

Concurrent sessions sharing one checkout still share one worktree. Another
session's uncommitted bytes drift every packet in it, and resume answers that
with `drift_refused` and reconciliation rather than resuming across a state the
packet never recorded. Targeting decides whose run is examined, not whether the
bytes moved; genuinely parallel work belongs in separate worktrees, which have
their own mutable state and are never candidates for each other.

Stable result codes:

| Result | Meaning | State change |
| --- | --- | --- |
| `ready` | exact targeted packet claimed and drift-clean | run becomes `running` |
| `not_found` | no unfinished packet in this checkout, or the named run is not one | none |
| `live_owner_refused` | existing owner still holds the run | none |
| `owner_unproven_wait` | timestamp fallback has not expired | none |
| `drift_refused` | HEAD, worktree, rules, required docs, or pending-mutation state mismatch | `reconcile_required` |
| `invalid_packet` | containment, schema, binding, or integrity failure | none |
| `local_boundary_failed` | ignored/local-only or filesystem boundary is not proven | none |
| `claim_lost` | owner or generation changed during validation | none |

Human output may add repair guidance, but JSON output uses only these result
codes and bounded fields. Exit status is zero only for `ready` and a successful
`--list`; every refusal is nonzero.

`cancel` is the narrow transferred-work terminal path from the transition table,
not a gate bypass. It accepts only a clean main checkout whose exact request,
runtime session, route, rules root, and Git common directory match a completed
linked-worktree run. It preserves the source ledger and continuation packet,
writes a content-free receipt, and moves only the source registry entry to
`cancelled`. Dirty, unrelated, incomplete, unowned, malformed, or already
terminal sources fail without changing either run.

## Runtime Adapter Requirements

An adapter supplies three pieces of wiring and nothing else:

1. **Initial and semantic checkpoint invocation.** Supply only the bounded
   `work` fields its agent already knows. The common command validates prose and
   derives every fingerprint, path role, route field, gate state, and
   generation.
2. **Mutation hook wiring.** Call the common pre-mutation command with a bounded
   path set and mutation enum, then the post-mutation command after success.
3. **Session-start invocation.** Call the common resume command. Inject a work
   brief into the conversation only when the common result is `ready`. Include
   the common reuse decision, required-document status, bounded inspected
   scope, accepted-decision ids, and current-state successful-verification ids
   so the resumed agent continues from evidence instead of recreating it.

Adapters must not: define schema, choose the storage path, implement drift
checks, decide takeover, select a different packet, weaken result codes, read
packet JSON directly, or render an invalid packet's prose.

Runtime-native conversation continuation remains separate. Claude, Codex, or
another runtime may restore its own conversation, but Tao Agent OS's packet is the
authority for project work state and may be used without the old conversation.

The Claude adapter uses the common read-only active-session resolver. A start
without explicit evidence allocates one
`.tao/runs/<opaque-run-id>/preflight.json` path and every later hook resolves
that same path only when runtime name, session id, registry evidence key, and
resume generation agree. An isolated worker resolves only the exact
launcher-issued `TAO_WORKER_EVIDENCE` path and never falls back to parent
evidence. A caller without that binding traverses the worker subtree only to
account for active worker registry keys, excludes its files from parent
matching, and requires exactly one parent-scope match, so a legitimate parent
and worker do not turn each other into ambiguity. Multiple parent-scope matches fail closed,
and a malformed, foreign, or unregistered worker binding fails without parent
fallback. Discovery takes one registry snapshot and one bounded state-tree
traversal with explicit parent/worker scope classification; it never scans once
per active run or selects the newest file. `SessionStart` calls the common
resume transaction and injects work prose only for `ready`;
drift and owner refusals render no saved work. `PreToolUse` brackets
`Edit|Write|MultiEdit|NotebookEdit` before execution, and `PostToolUse` plus
`PostToolUseFailure` close the same mutation after the tool outcome.

Once a new parent start is fully promoted to `running`, it may settle older
active parent claims bound to the same runtime session so a leaked custom
evidence path does not make the exact-session resolver permanently ambiguous.
This is a registry compare-and-set, not a generic terminal transition: the
evidence key, run id, run-instance start time, active state, and captured resume
generation must still match under the registry lock. A concurrently completed,
failed, cancelled, reconcile-required, rebound, or newly adopted run is
preserved and is not reported as settled. Other runtime sessions and isolated
workers remain outside this supersession.

Claude does not expose a trustworthy changed-path set for arbitrary `Bash`
commands. A shell command, formatter, or generator that may write files must
therefore call the common `pre_mutation` checkpoint explicitly with its bounded
paths before execution and the common `post_mutation` checkpoint afterward.
The adapter must not guess paths from command text or claim automatic coverage
it cannot enforce.
