---
keyflow_id: minimal_workflow_ard
status: review
type: ai-generated
---

# Minimal Workflow Architecture

Accepted direction: replace agent-authored gate completion with effect-scoped
execution and runtime-owned evidence. Requirements: [prd.md](prd.md).
The first slice implements stateless lookup and versioned turn termination.
The local open/verify and commit reuse interfaces remain future work.

## Options

| Option | Decision |
| --- | --- |
| Keep gates and shorten their prose | Reject: agents still manage state and recover from administrative failures |
| Disable every hook | Reject: removes ownership, uncertain-effect and publication protections |
| Reduce lifecycle entrypoints and collect evidence at the action boundary | Accepted: remove ceremony while retaining enforceable safety |

## Boundary owners

| Existing owner | Proposed responsibility |
| --- | --- |
| `scripts/workflow_route.py`, `scripts/workflow_gate_policy.py` | Select an effect profile and needed guidance; read-only work has no mandatory gate list |
| `scripts/agent-hook.py` | Thin compatibility CLI; new open/verify operations delegate to existing policy owners |
| `scripts/agent_run_registry.py`, `scripts/agent_runtime_session.py` | Exact project/session ownership, resumable outcomes and versioned state |
| `scripts/agent_review_hook.py`, `scripts/agent_finish_final_checks.py` | Collect and validate actual scoped checks once, without requiring narrative evidence fields |
| `scripts/codex_stop_gate.py`, `scripts/claude_stop_gate.py` | Permit truthful termination; never ask the agent to complete a ledger just to answer |
| `scripts/support/runtime_bridge.py` and installed adapters | Deliver the minimal contract consistently; stop recommending removed ceremonies |

No new service, watcher, provider process or generic orchestration framework.
Before changing another runtime adapter, inspect its equivalent behavior and
test the same contract; this design's direct stop-hook evidence is Codex-specific.

## Minimal interfaces

- Read-only: no lifecycle open/close. The action boundary still refuses mutation
  without a writable scope and applicable authority. A classification label alone
  does not grant access or disable provider sandbox checks.
- Local `open`: one bounded intent (target, allowed effects, scope, verification
  expectation). Reuse a matching active context instead of creating a second run.
  Return the selected guidance and existing verification that remains valid.
- Local `verify`: collect observed action results, inspect the scoped final diff,
  perform missing relevant checks, and atomically record the outcome. Do not add
  separate source, review, retrospective and finish calls behind new names.
- Commit `ready`: bind exact staged content and reusable verification to one
  readiness receipt. Immediately before commit, validate its inputs have not
  changed. Never reuse a receipt for different staged files or a new target.

These are proposed interface names, not runnable commands. Keep authority
enforcement separate from prose judgments about code quality. For runtimes that
cannot capture a check automatically, accept one bounded structured result from
the approved executor; mark unavailable evidence unknown, never invent success.

## State and termination

Separate task outcome from turn control:

| Outcome | May answer/end turn? | May claim verified or publish? | Resume |
| --- | --- | --- | --- |
| running | Yes, if user stops; record interrupted when writable | No | Exact owner |
| blocked | Yes, with blocker and partial-change status | No | Revalidate blocker and authority |
| interrupted | Yes | No | Reconcile current files and effects |
| verified | Yes | Only within separate action authority and valid inputs | New work invalidates affected evidence |
| cancelled | Yes | No | New run; no implicit rollback |

Blocked/interrupted are retained resumable records, not active stop obligations
and not success. Capture outcomes at existing tool/turn boundaries, not through
a new agent-authored stop ceremony. A failed registry write may leave historical
state unresolved, but must not trap the user in a continuation loop. Next resume
reconciles ownership and bytes before mutation. Unknown external effects always
remain unresolved, even when the turn is permitted to end.

The stop adapter cannot infer the meaning of a final answer from an active run.
It must not scan prose/transcripts to guess completion. Readiness/verification
claims are supported by explicit runtime outcomes; unfinished work is reported as
such without forcing another model turn. Real permission enforcement belongs at
the tool/action boundary, not at the response boundary.

## Evidence and reuse

Reuse existing ignored run storage. Keep a compact, versioned record of owner,
scope, actual input fingerprints, executor result, check kind, outcome and bounded
blocker reason. Do not copy prompts, commands, logs or secrets into metering data.
Do not maintain parallel old/new authoritative ledgers. Old gate files remain
historical evidence; new runs use one versioned record.

Reuse only when all declared check inputs match: files, relevant dependencies,
rules/configuration, tool identity and target as applicable. A check with unknown
inputs cannot be reused automatically. Preserve independent results whose inputs
did not change. One final snapshot comparison prevents mutation during checking
from producing a valid receipt for stale bytes.

### Commit review check reuse

The existing review hook can reuse its machine-produced structure and workflow
validation results on a `commit` or `git_commit` follow-up. No extra agent call
is required. A bounded latest receipt is derived from the successful review
attestation; it is an optimization, not a second authoritative ledger.

The match covers the exact project, HEAD, changed file contents and modes,
review scope, rules and checker inputs, and review limits. Staging identical
working bytes does not itself change those inputs. Partial staging, changed
files, changed rules, missing or malformed provenance, and unsupported review
subjects fall back to ordinary checks. Capture inputs before checking and
compare them afterward before preserving a reusable result.

Authority, prerequisite gates, the current diff and base, safety checks, and
final worktree stability remain current-run checks. Reused results are named
in the current attestation. This does not cache arbitrary test commands or
turn an agent-authored test summary into execution evidence. The proposed
single-call commit readiness interface remains separate future work.

## Migration and falsifying checks

1. Accept PRD/ARD through the product decision boundary before implementing new
   runtime state or API contracts. Retain current authority restrictions.
2. Implement read-only no-run behavior and blocked/interrupted termination together
   with stop-adapter tests. Do not just delete the retrospective gate: bridge,
   registry selection and stop behavior must agree.
3. Add runtime-owned local verification using the existing scoped review/check
   owners. Retire corresponding manual gates from new profiles in the same slice.
4. Add commit receipt reuse with changed-stage, changed-HEAD, concurrent-edit,
   missing-test and unauthorized-target counterexamples.
5. Refresh installed bridges and test the actual launcher after restart. Remove
   compatibility entrypoints only after no supported adapter requires them.

Pin a lifecycle version on each run. Existing legacy runs are not silently
cancelled or marked successful. At explicit resume, reconcile into the new
outcome model while retaining their original evidence; uncertain external effects
block further writes. Rollback selects the previous implementation for new runs
and preserves versioned records. An older reader must refuse unknown versions
with an actionable message, not reinterpret them as active legacy obligations.

Nearest existing test owners: `test_codex_stop_gate`, `test_claude_stop_gate`,
`test_agent_runtime_session`, `test_agent_execution_capsule`,
`test_workflow_required_doc_selection`, and `test_agent_review_validation_state`.
Add budget assertions for zero read-only ceremony and no manual local gate
records, alongside the PRD's authorization and freshness counterexamples.

## Limits

The first slice pins `route.lifecycle_version = 2` on new manifests; a missing
marker means legacy version 1. Compatibility analysis without explicit evidence
returns guidance without creating a run, cache, checkpoint, or timing file.
It still validates its read-only intake. Direct lookups need no compatibility
call. Existing version 1 runs retain their closeout contract; migration of those
runs and automatic local verification are outside this slice.

Runtime adapters differ in event visibility. Establish actual executor evidence
coverage during each slice; do not promise transparent collection everywhere.
Project-specific mandatory workflows remain authoritative until changed at their
owner. Simplifying Tao alone cannot remove a separate project's ticket or module
rules. Avoid importing company-specific policy into this shared redesign.
