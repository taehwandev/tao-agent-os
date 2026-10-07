---
keyflow_id: sys_project_memory_consolidation_spec
status: draft
type: ai-generated
---

# Project Memory Consolidation Technical Specification

## Problem

`<TAO_LAUNCHER> project-memory` stores agent-written, source-attributed records
under `~/.tao/project-memory/<repository-id>/` (`scripts/agent_project_memory.py`).
Records leave recall only when they reach their `--review-on` date, or when an
agent replaces or retires them. Nothing reviews the store as a whole. As
captures accumulate, the following problems go unnoticed:

- the same fact is captured twice under one scope, and each copy competes for
  the three recall slots (`MAX_RECALL_ITEMS`);
- records nearing their review date expire silently. Nobody decides whether to
  renew them with a new date or let them lapse;
- two live records that share a source disagree, and recall shows both;
- an interrupted `capture --replaces` leaves the replaced record live on disk.
  Recall already hides that record, but the store still holds it.

Periodic memory "dreaming" designs, such as Cognition's Agent Memory Repo,
address this with a background agent. The agent merges duplicates, drops
outdated entries, resolves contradictions against sources, and mines sessions
for new patterns. Tao adopts the review half of that idea. It rejects session
mining, a resident agent, and git sync for the reasons in Non-Goals.

## Goals

1. A deterministic, read-only `consolidate` report that lists the records
   needing a decision, with a reason for each.
2. Decisions are applied only through the existing mutations: `capture
   --replaces` and `retire`. No new write path exists, so the store's
   validation and commit-point rules stay unchanged.
3. Claude Code, Codex and Antigravity (AGY) behave identically, because all
   three reach the store through the same stable launcher.
4. A bounded, content-free notice at `start` replaces any scheduler.

## Non-Goals

- **Session or transcript mining.** Tao never reads transcripts, logs or
  shell history to derive memory. A new record still comes only from an
  explicit agent `capture`, grounded in current-session evidence.
- **Automatic merge, retire or contradiction resolution.** Deciding which
  record is right requires checking its `source`. That is agent judgment
  against live evidence, not something a heuristic can settle.
- **Cross-machine or git sync.** The store stays user-local, as `AGENTS.md`
  requires ("do not sync it"). Changing that is a separate policy decision.
- **Cloud schedules.** A cloud routine cannot reach the user-local store, and
  a local daemon adds recurring infrastructure. The `start` notice covers the
  need.
- **Claude auto-memory** (`~/.claude/projects/<project>/memory/`). It is
  Claude-only and outside Tao. Facts every runtime needs belong in
  project-memory.

## Runtime Parity

| Runtime | Reaches the store through | Sees the start notice |
| --- | --- | --- |
| Claude Code | stable launcher via hooks and the runtime bridge | yes, from `start` output |
| Codex | stable launcher via hooks and the runtime bridge | yes, from `start` output |
| AGY | stable launcher via the `~/.antigravity/AGENTS.md` bridge (no hooks) | yes, when the bridge-driven `start` runs |

`consolidate` adds no runtime-specific code. AGY has no hooks, so it gets the
notice only when its bridge-driven `start` runs. That is the same condition it
already needs to get recall.

## Command

```text
<TAO_LAUNCHER> project-memory --project <PATH> consolidate [--within-days N]
```

The command is read-only and prints one JSON object. Each finding carries
record ids, a `reason`, and the fields an agent needs to decide. It includes
the bodies, since the report goes to the agent and never into lessons,
metering or continuation packets.

| Finding | Rule | Expected agent action |
| --- | --- | --- |
| `expired` | status recallable and `review_on <= today` | renew with `capture --replaces` and a new date after rechecking `source`, or `retire` |
| `expiring` | `today < review_on <= today + N` (default 14) | same as `expired`, ahead of time |
| `duplicate_groups` | live records whose scopes match, or where one scope is `all`, and whose normalized bodies have a token Jaccard of at least 0.8 | write one merged record with `capture --replaces <one>`, then `retire` the others |
| `shared_source_groups` | two or more live records with the same normalized `source` | open the source; keep, merge or retire the records that disagree with it |
| `unfinished_replacements` | a live record whose id appears in another live record's `replaces` | `retire <id>`, which finishes the interrupted replacement |
| `unreadable` | a count of `*.json` files that `_read` rejects | report only; never print their contents |

Normalization lowercases the text, folds runs of whitespace, and strips
punctuation. Plain token sets keep the heuristic stdlib-only and
deterministic. A false positive costs the agent one look. A false negative
leaves the store as it is today.

Exit status is 0 whether or not the report has findings. Invalid arguments and
store errors keep the existing `parser.exit(2, ...)` convention.

## Start Notice

`agent-hook.py` already calls `recall_lines` during `start`. Next to that call,
`start` appends at most one line when any finding is non-empty:

```text
Project memory upkeep: expired=1 expiring=2 duplicates=1 shared_source=0 unfinished=0 -> <TAO_LAUNCHER> project-memory --project <PATH> consolidate
```

The line holds counts only and never record content. It is advisory and creates
no gate, so a run that ignores it still finishes. The notice reuses the record
scan that recall already performs, keeping its cost at one directory read per
`start`.

## Ownership And Placement

- A new `agent_project_memory_consolidate` module beside the store script owns
  the finding rules.
  It is a pure function over validated records plus a summary-line renderer.
  Allowed imports: stdlib and `agent_project_memory` (for `_read`/`_store`,
  which become public as `read_record`/`store_dir`). Forbidden: any hook,
  ledger or metering module.
- `scripts/agent_project_memory.py` keeps the store and CLI. It adds the
  `consolidate` subparser and delegates to the new module. The file has 254
  lines, so the logic stays out of it.
- `scripts/agent-hook.py` adds the one-line notice next to the existing
  `project_memory_recall_lines` call through a module-level helper. That keeps
  the `start` handler from growing toward the 120-line block limit.
- The launcher alias table needs no change, because `project-memory` already
  maps to `agent_project_memory.py`.

## Documentation Updates On Implementation

- `AGENTS.md` "Automatic Project Memory": one sentence naming `consolidate`
  and the start notice.
- `common/skills/local-tools/references/current-guidance.md`: the
  project-memory paragraph gains the consolidate command and its finding
  table reference.
- Promote this spec's `status` from `draft` to `review` when the code lands.

## Verification

- A new subject test for the `agent_project_memory_consolidate` module covers
  each finding rule.
  Fixtures are written into a temporary `TAO_STATE_HOME`, including:
  - a replaced-but-live record;
  - scope `all` pairing with a route scope;
  - a below-threshold near-duplicate, which must not be reported.
- `tests/test_agent_project_memory.py` checks that `consolidate` is read-only:
  store bytes are identical before and after.
- A start-hook test checks that the notice appears only when a finding exists
  and contains no record body.
- A manual check runs `consolidate` through the stable launcher once from each
  runtime and confirms the three reports are identical for one repository.

## Open Questions

- Whether records should carry an optional `captured_by` runtime field
  (`claude`, `codex`, `antigravity`). That would make cross-runtime
  disagreement visible in `shared_source_groups`. It changes the record schema
  outside the digest and should be decided before implementation.
- Whether `expiring` should default to 14 days or follow the median review
  horizon of the store.
