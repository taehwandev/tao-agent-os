---
keyflow_id: sys_agent_runtime_integration
status: review
type: human-reviewed-needed
---

# Agent Runtime Integration

Use this when connecting Tao Agent OS to Codex, Claude,
Gemini/Antigravity/AGY, or another AI coding agent runtime.

## Model

Tao Agent OS should be consumed through a small bridge, not copied wholesale:

1. Reusable library: one Tao Agent OS root.
2. Runtime bridge: repo-local instructions or a pasted prompt.
3. Task route: `scripts/workflow.py` output for the current task.
4. Safety gate: current VibeGuard application flow using Tao Agent OS as the
   rule source.

Repo-local instructions remain the source of truth for commands, paths,
services, product policy, and domain language.

Separate shared semantics from runtime mechanics. The provider-neutral
canonical owner defines what the agent must know and do; runtime bridges define
only how Codex, Claude, Gemini/Antigravity/AGY, or another runtime discovers,
invokes, or enforces it. When several runtimes need the same repo-local skill, keep one
canonical bundle under `.tao/skills/<skill>` and use repo-relative
runtime links or thin adapters. Do not maintain full runtime-specific copies of
the same operational knowledge.

## Provider-Neutral Execution Capsule

Use one local execution capsule as the reusable parent-to-worker handoff for
Codex, Claude, and Gemini/Antigravity/AGY. This is deterministic workflow state,
not conversational or long-term model memory. The capsule must remain
content-free: do not store prompts, responses, command output, logs, diffs,
source text, environment values, or secrets.

The parent owns the capsule lifecycle:

1. Run `<TAO_LAUNCHER> start` once for the multi-step task. Do not separately run
   workflow list, classify, route, and preflight as a second startup sequence.
2. Read the route's `required_docs` directly before work. Do not add a second
   document-confirmation step.
3. At each parent-to-worker boundary, run `agent-hook.py handoff`. It lazily
   creates the capsule from the current project/rules/worktree fingerprints,
   route manifest, request fingerprint, and required-document snapshot, then
   rebinds the parent's successful ledger entries to that snapshot. When
   project and rules are in the same Git repository, capture their Git state
   once for that handoff.
4. A worker may reuse the parent's route, preflight, required-doc brief, and
   gate context and skip duplicate startup only when the handoff reports capsule
   status `ready` and validation succeeds. The parent has already read the
   required docs; a reusable worker must not reread them, run VibeGuard, or run
   a separate review or finish lifecycle.
5. A missing capsule, hash mismatch, changed required document, stale evidence
   reference, project/rules mismatch, or other invalid result is a successful
   fallback decision from the handoff command, not permission to reuse. The
   worker must follow the normal lifecycle using a newly reserved worker-specific
   evidence path and its single-use claim token. Never guess that cached state
   is close enough or overwrite parent evidence during fallback.

Worktree reuse keeps the strong content fingerprint authoritative. A capsule or
review validation record may avoid recomputing that fingerprint only when Git `HEAD` and
a content-free invalidation signature of the current dirty paths, staged object
identities, and filesystem metadata still match the prior strong snapshot. The
signature is a cache filter, not an identity proof: any mismatch requires a new
strong capture. Strong capture has bounded untracked-file count and byte limits;
when the worktree exceeds them, capsule reuse fails closed with
`reusable=false` and the worker follows the normal lifecycle instead of waiting
on an unbounded scan.

Reuse is an execution optimization, not a gate exemption. The parent remains
the sole owner of the gate ledger, integration review, and final verification.
Workers receive bounded write scopes, return scoped evidence, and must not
overwrite parent preflight, gate-ledger, review, or finish evidence. Workers use
worker-specific evidence paths whenever they must run the normal lifecycle,
including after an invalid handoff fallback.
The capsule itself does not prove that a gate passed.

The same rule applies to a clean session continuation. When the common resume
transaction returns `ready`, its strong drift check authorizes reuse of the
packet's bounded inspected-scope, accepted-decision, and current-state
successful-verification evidence. Required-document reading is reusable only
after the authoritative source-doc gate passes. A completed mutation
checkpoint invalidates earlier verification successes, so adapters never carry
a pre-edit pass across new bytes. Runtime adapters must render the common
ready-only reuse and rerun-condition fields rather than duplicate that policy,
and must not make the agent reread or rerun identical work merely to rebuild
conversation context. External freshness requirements or a different
acceptance boundary require affected new evidence; additional confidence should
use an orthogonal check rather than an identical rerun. Any refusal renders
neither saved work nor reuse advice.

Runtime bridges and workers use `agent-hook.py handoff` through the same
approved wrapper or stable-launcher path as the other lifecycle hooks. A direct
capsule-core CLI is diagnostic only; do not make each runtime integrate a
separate capsule command.

Runtime adapters stay thin and apply the same validation semantics:

- The `analysis` route is a serial, read-only fast path. Its dispatch manifest
  must use `authoring_policy: read-only non-authoring` and
  `sandbox_mode: read-only` in both inline and explicitly isolated execution.
  It retains only the active runtime instruction, has no
  code/test/documentation/review gate, and launches no worker unless isolation
  is explicitly requested.
- Codex keeps a leaf inline unless isolation is explicitly required. Profile or
  sandbox differences and missing parent-profile information are decision
  evidence, not automatic reasons to launch a nested Codex process. Inspecting
  an isolated child manifest does not expose runnable arguments: execute
  revalidates the capsule and mints or verifies the worker reservation directly
  before launch.
- Claude passes the validated capsule to Agent/Task workers.
- Gemini/Antigravity/AGY passes the validated capsule through its native
  parallel agent runner.

Keep this section as the canonical policy. Generated runtime bridges and
repo-local templates should carry only the short invocation, reuse, ownership,
and fallback contract rather than duplicating the full schema or invalidation
rules.

## Project-Local Agent Mailbox

Use the local mailbox when one runtime should ask another for an opinion,
review, or bounded continuation without the maintainer copying a prompt and
context between products. The mailbox is transport only. It never invokes a
provider CLI or API, starts a model turn, or keeps a daemon, watcher, poller,
background process, or external service alive.

The maintainer never chooses a room or task id. On send, Tao resolves the exact
active run bound to the sender's runtime session and revalidates the capsule
created by `handoff`. It stores one packet below
`.tao/agent-mailbox/runs/<opaque-run>/inbox/<recipient>/`. Each packet binds its
project fingerprint, source-run id, evidence fingerprint, sender, recipient,
kind, timestamps, and bounded body. Copying a packet to another project or
moving it under another source run makes validation fail.

Required sequence:

1. The sender completes `start`, required-document reading, and task scoping.
2. Immediately before sending, the sender runs `<TAO_LAUNCHER> handoff` so the
   source capsule reflects the current worktree and gate ledger.
3. From the selected project, the sender posts one compact brief through stdin:

   ```text
   <bounded review brief> | <TAO_LAUNCHER> agent-mailbox send --to claude --kind review
   ```

4. The target remains idle. On its next normal user-visible prompt, its runtime
   bridge runs `<TAO_LAUNCHER> agent-mailbox receive --runtime <target>` once
   from the selected project. A returned brief is context, not authority: the
   current user request and the target's normal Tao lifecycle still decide what
   it may do.
5. Receive writes a body-free acknowledgement record atomically and removes
   the pending packet before returning it, so concurrent receivers cannot
   consume the same message twice. It never selects messages addressed to a
   different runtime or project.

The default TTL is 24 hours and the maximum is seven days. A body is at most 32
KiB, one source-run/recipient inbox holds at most 32 pending messages, one read
scans at most 64 runs and 128 packets, and one receive returns at most eight
messages. Expired messages are removed without delivery. Mailbox paths and
files must not be symbolic links.

## Setup And Installation

Installing or wiring a runtime is a separate reading:
`docs/skills/agent-runtime-integration/references/runtime-setup.md` covers the
installer ownership boundary, the setup modes, project discovery, launch-root
discipline, the cross-repo scope checkpoint, and both repo and one-shot setups.

That guidance was split out of this document because a single reference larger
than the route's mandatory-reading budget is admitted into `reference_docs`
only, where it stops being routable on its own concern.

## Runtime Model Tier Mapping

Workflow request classification may emit a runtime-neutral `model_tier` such as
`fast`, `balanced`, `frontier`, or `specialist`. Runtime bridges should preserve
that abstract tier in handoff state and map it to a concrete model only for the
active runtime.

Codex bridges may map the current configured tiers to `gpt-5.6-luna`,
`gpt-5.6-terra`, and `gpt-5.6-sol` when those model ids are available. Claude,
Antigravity, and generic bridges must not use Codex model ids directly; map to
their own configured fast/balanced/frontier choices, or keep the current model
and apply the same effort profile through context size, planning depth, and
verification strength.

Switch models only at a task, subagent, or session boundary unless the runtime
provides a safe mid-task handoff. A handoff must preserve the selected project,
route, required-doc manifest, gate ledger, unresolved blockers, and verification
plan.

For Codex, make the parent split decision first. At a bounded leaf/task
boundary, use `workflow.py dispatch <command> --request "<USER_REQUEST>"
--execute` only when isolation is explicitly required. Keep every non-isolated
leaf in the current process or use a native worker, regardless of whether the
selected profile, sandbox, or parent profile information matches. One dispatch is not
multi-agent fanout. The main session remains responsible for orchestration,
integration, and final verification. Omit `--execute` to inspect a
non-executing handoff manifest. The profiles are explicit:

| Stage | Tier and reasoning effort |
| --- | --- |
| PRD or design | Sol / high |
| Research | Terra / low |
| General analysis | Terra / medium |
| Normal code implementation | Terra / medium |
| Complex implementation with deep or specialist evidence | Sol / high |
| Non-authoring repetitive checks (read-only; no code or patches) | Luna / low |
| Final review | Sol / xhigh |

Automatic stage selection is command-based: `prd` and `spec` select PRD/design,
`plan` and `planning` select research, `analysis` and `task` select general analysis,
`feature`/`build`/`bugfix`/`refactor`/`workflow-setup` select implementation,
and only quick, non-authoring `test` work selects the read-only Luna profile.
Test creation, test fixes, code edits, and every implementation command stay on
Terra / medium or higher. `review`/`docs-review` select final review. Deep or
specialist evidence promotes implementation commands to complex implementation.

Do not infer complex implementation from line count or a subjective impression.
Normal implementation stays on Terra / medium. Luna must not write or modify
code: its dispatcher handoff is read-only and explicitly forbids code, patches,
and test creation. Promote only when the request classification or local
inspection provides deep or specialist evidence, such as cross-module
architecture, security, data, migration, release, or repeated failure risk. When the orchestrator explicitly selects
`complex_implementation` after local inspection, it must pass the concrete
`--complexity-evidence`; the dispatcher rejects an unexplained promotion. The
handoff carries the parent preflight evidence, required-doc manifest, gate
ledger, and verification plan. A delegated worker must not dispatch another child or
overwrite those parent evidence files.

## Runtime Notes

Codex:

- Prefer repo-local `AGENTS.md` plus the routing block.
- Start Codex with the selected target repo as the primary workspace:
  `codex -C <TARGET_REPO>`.
- Add `--add-dir <TAO_ROOT>` only when the task must include the
  shared Tao Agent OS root in the session workspace, such as maintaining
  Tao Agent OS itself or editing shared runtime bridge files.
- Do not expect `AGENTS.md` or `.codex/rules` to change sandbox roots; they
  control behavior and permission matching, not the runtime's workspace root.
- Use `<TAO_LAUNCHER> start` once for multi-step work; do not run a second
  classify, route, or preflight sequence after it succeeds.
- Keep the managed Codex `Stop` closeout hook enabled when the optional
  user-level runtime bridge is installed. It resolves only the active run bound
  to the current `CODEX_THREAD_ID` and delegates retrospective and reusable-skill
  enforcement to the provider-neutral `finish` validators; it must not infer
  outcomes from prompts, transcripts, diffs, or the last assistant message.
- Preserve unrelated entries when merging `~/.codex/hooks.json`. Identify the
  managed entry by the stable `codex-stop-gate` alias, not by event, timeout, or
  neighboring hook shape.
- Tao Agent OS command permissions belong in user-level
  `~/.codex/rules/default.rules` as narrow `prefix_rule` entries for the
  current `<TAO_ROOT>/scripts/*.py` files.
- Generate direct `python3 <script>` argv prefixes for those same scripts using
  resolved absolute paths only. Agents should invoke these wrappers as direct
  argv commands, not through `$HOME`, `${HOME}`, `~`, relative paths, or shell
  `-lc` strings; once the absolute script path is a separate argv item, long
  trailing workflow arguments such as repeated `--gate-record` values are
  suffix-matched by the runtime policy and should not prompt again.
- When a Codex tool call needs escalation, request the persistent permission
  with `prefix_rule=["python3", "/absolute/path/to/tao-agent-os/scripts/<name>.py"]`.
  Do not include changing arguments such as `--project`, `--request`, `--gate-record`,
  `$(pwd)`, or user-provided text in the saved prefix.
- `setup-agent-hooks.py` should leave only absolute, parameter-free
  Tao Agent OS script prefix rules in the managed Codex block and remove stale
  Tao Agent OS rules that were saved with `$HOME`, `${HOME}`, `~`, relative
  script paths, shell `-lc`, or command-specific arguments.
- Keep Codex-specific commands or sandbox notes in the target repo, not in the
  shared Tao Agent OS.

Claude:

- If `CLAUDE.md` already exists, update it with the routing block or a pointer
  to `AGENTS.md`.
- If no Claude-specific file exists and Claude reads `AGENTS.md` in the target
  environment, do not create `CLAUDE.md` just for duplication.
- If Claude is operating from chat without repo instruction discovery, paste
  `templates/use-tao-prompt.md`.
- Tell Claude the exact Tao Agent OS root path or a repo-pinned submodule path.
- Tao Agent OS command permissions belong in the user-level
  `~/.claude/settings.json`, not repo-local `.claude/settings.json`, because
  the Tao Agent OS `scripts/*.py` entrypoints are shared across projects.
- Claude managed hooks should call the stable launcher
  `<TAO_LAUNCHER>`, not a moving checkout path such as
  `/absolute/path/to/tao-agent-os/scripts/workflow.py`. The setup script
  refreshes `~/.tao/tao-root` to the current checkout and
  removes stale managed hook commands that still point at old roots. The stable
  launcher supports both script aliases such as `workflow` and direct
  `agent-hook.py` subcommand aliases such as `start`, `handoff`, `review`,
  `checkpoint`, `resume`, and `finish`; these aliases must execute the hook, not skip with
  success.
- Claude Tao Agent OS permissions should allow only that stable launcher and
  the narrow managed helper commands with the runtime's trailing wildcard form
  for arguments, for example
  `Bash(/absolute/home/.tao/bin/tao-hook *)`. Do not
  approve or document broad `python3`, relative `scripts/<name>.py`, or
  argument-specific variants for shared wrappers.
- A non-runtime Python query helper may run read-only in a protected checkout
  only when the environment inherited from Claude's parent process contains
  `TAO_CLAUDE_READ_ONLY_PYTHON_SCRIPTS`. The value is strict JSON with this
  exact shape:

  ```json
  {
    "schema_version": 1,
    "scripts": [
      {
        "path": "/canonical/absolute/path/to/query.py",
        "sha256": "<64 lowercase hexadecimal characters>"
      }
    ]
  }
  ```

  Generate that declaration in operator-controlled launcher setup before
  starting Claude. The path must already be canonical, must name a regular
  non-symlink file, and the digest must be the SHA-256 of its current bytes.
  Invoke it with the resolved Python executable used by the hook and repeat the
  same absolute canonical script path as the first operand; relative operands,
  including `cd /path && python query.py`, are never allowed. Arguments are not
  classified, so declare only a helper that cannot write for any accepted
  argument. `TAO_STATE_HOME/read-only-scripts.json` is not an authorization
  surface and is ignored.
- Remove `TAO_CLAUDE_READ_ONLY_PYTHON_SCRIPTS` from the parent environment to
  revoke all helper access. Editing a declared script revokes that entry
  automatically because its digest no longer matches; after an intentional,
  reviewed edit, compute the new lowercase SHA-256 and refresh the parent
  declaration before starting a new Claude process. Malformed JSON, unknown
  fields, duplicate paths, missing files, non-canonical or relative paths,
  symlinks, digest mismatches, and a Python executable other than the hook's
  current runtime all fail closed.
- The managed Claude `UserPromptSubmit` workflow label hook uses
  `workflow route triage --advisory`. That hook fires on every prompt and never
  sees the prompt text, so it has no request to classify: `--advisory` emits the
  document listing and label context while asserting no request intake and
  satisfying no downstream gate. It must not pass prompt content, and it must
  not use `--request-classified`, which is honored only for a delegated worker
  backed by a ready and valid parent execution capsule bound to the same exact
  request and workflow command. Work routes must use
  resolved-scope evidence such as
  `clear-scoped`, `answered ... separate actionable`, or `blockers resolved`;
  `classified`, `done`, `handled`, `clarified`, or `no blockers` is not enough
  by itself. `setup-agent-hooks.py` should replace stale managed Claude hooks
  that omit the evidence flag. The hook should fail soft when the root pointer
  is stale so Claude startup is not blocked before the user can repair setup.

Gemini/Antigravity/AGY:

- Use `AGENTS.md` as the project instruction surface that Antigravity reads.
- The managed user-level bridge installed by `setup-agent-hooks.py` must tell
  AGY to run `agent-entry.py` or `project-discover.py` before project work when
  it starts outside the target repo or cannot identify one clear target.
- The same bridge must require graph-backed routing/search before document
  selection so AGY reads route `required_docs` for the current task instead of
  depending on user-supplied keywords.
- Do not create an extra Antigravity-specific file only to duplicate guidance
  already available from `AGENTS.md`.
- If Antigravity-specific docs already exist, update their pointer in the same
  pass as the canonical instruction file.
- If local evidence shows a different active instruction surface, stop and ask
  before adding duplicate guidance.
- Do not assume Antigravity has loaded `AGENTS.md` unless local evidence or the
  user confirms that behavior; instruct it to read the Tao Agent OS root
  explicitly when in doubt.
- Tao Agent OS command permissions may live in
  `~/.gemini/config/config.json` or the legacy
  `~/.gemini/antigravity-cli/settings.json`, depending on the active AGY
  runtime. Runtime hooks remain in `~/.gemini/config/hooks.json`.
- AGY Tao Agent OS permissions follow the same absolute-wrapper rule as
  Claude, using the AGY permission key shape, for example
  `command(/Users/USER/.tao/bin/tao-hook *)`.
  Avoid `$HOME`, `${HOME}`, `~`, relative script paths, and saved prefixes that
  include task-specific arguments.

Generic agents:

- Use `.agents/README.md` or the runtime's documented project instruction file.
- If file discovery is unavailable, use the one-shot prompt.

## Required Flow

For every runtime:

1. Identify the target repo. If the runtime started outside the repo, the
   target is not explicit, or multiple repos match the request, run
   `scripts/agent-entry.py` or `scripts/project-discover.py` first. Continue
   only when discovery returns `selected`; ask the user when it returns
   `ambiguous` or `not_found`.
2. Read the current repo-local instructions:
   `AGENTS.md`, `CLAUDE.md`, `CODEX.md`, `.agents/README.md`,
   `CONTRIBUTING.md`, task docs, PRD/ARD docs, equivalent project guidance, or
   explicitly documented local override files.
3. Select the setup mode: existing local install, first-time local shared
   install, or team-pinned install.
4. Locate the Tao Agent OS root. If any usable local or repo-pinned root
   exists, reuse it unless the user explicitly approves a new download or
   pinned copy.
5. Install only when no usable root exists, then validate the selected root.
6. Run `scripts/setup-agent-hooks.py --check`. If bridges, hooks, or
   permissions are missing, ask for approval to update user-level runtime
   config, then run `scripts/setup-agent-hooks.py`.
7. Inspect existing VibeGuard files and agent instructions. Ask the application
   drill before running setup or update when the repo already has custom
   instructions or guardrails. Use VibeGuard `update` only when the user
   explicitly selects refreshing an existing managed block; otherwise preserve
   current guardrails and run audit.
8. Apply the selected VibeGuard mode with an installed `vibeguard` binary when
   available, using the selected Tao Agent OS root as the rule source. Use the
   published package command only when no trusted binary exists or an explicit
   latest-package check is needed. Treat https://vibeguard.thdev.app/ as the
   human-facing reference, not a runtime fetch dependency.
9. Add or update the canonical repo instruction file, preferring `AGENTS.md`
   when supported.
10. Update any existing repo-local runtime-specific instruction files in the
   same pass, or leave them out only when the runtime reads `AGENTS.md` and no
   separate file exists. Offer optional Step 2 for personal/global runtime
   bridges; only update those files when the user chooses it.
11. Read Tao Agent OS `AGENTS.md`.
12. For multi-step tasks, run `<TAO_LAUNCHER> start` once with the
    current request to produce routing and preflight evidence. If the request
    is a direct question, answer it before the start hook or editing. Use
    `index.md` only for simple answer-only work or an explicitly accepted
    fallback when the hook cannot run.
13. Read the route's `required_docs` directly before work. Do not separately
    repeat workflow list, classify, route, or preflight after a successful
    start hook, and do not add a document-confirmation command. The existing
    parent preflight binds the routed document snapshot and request fingerprint;
    the handoff capsule reuses that snapshot only when a worker boundary exists.
    Finish validates the parent-owned evidence without requiring a capsule for
    a task that never delegates, while `source docs` also receives the exact
    routed manifest instead of an agent-claimed empty state. An empty
    `required_docs` list is a valid no-source state and must continue once,
    with a recorded no-source decision, rather than retrying or blocking the
    capsule in preflight.
14. Before delegating, run `<TAO_LAUNCHER> handoff` to lazily create and
    validate the execution capsule once. A worker may reuse the parent route,
    preflight, and required-doc brief only after a ready-and-valid result; it
    must not repeat required-doc reads, VibeGuard, review, or final validation.
    An invalid result is a successful fallback decision requiring the normal
    lifecycle on worker-specific evidence paths. Keep the parent as the sole
    gate-ledger owner and never overwrite its evidence during fallback.
15. When wrapper scripts are available, run `<TAO_LAUNCHER> finish`
    before final report, commit, release, or handoff. Call
    `scripts/agent-finish-check.py` directly only as a lower-level fallback.
    Missing wrapper evidence or route gate evidence is non-compliant.
16. Keep a gate execution ledger, mark each route gate with evidence when it is
    executed or fails, bind successful records to the ready execution capsule,
    assign only `🐱🟢 SUCCESS` or `🐱🔴 FAIL`, and show a
    short gate signal after each completed or failed gate or task step.
17. Load only selected cards.
18. Execute repo-local commands only from trusted repo-local instructions.
19. Before reporting completion, confirm every required route gate is
    `🐱🟢 SUCCESS` with ledger evidence.
20. When a VibeGuard execution evidence adapter is configured, use the
    VibeGuard CLI evidence command and compare the summary with claimed
    commands.
21. Report verification and residual risk.

## Lifecycle Aliases

Runtimes may expose short lifecycle commands for convenience, but they should
call Tao Agent OS routing instead of creating a second active workflow router.

| Alias | Route Command | Primary Use |
| --- | --- | --- |
| `/spec` | `spec` | requirements note, PRD, acceptance criteria, open decisions |
| `/plan` | `plan` | research, options, recommendation before implementation |
| `/build` | `build` | scoped feature or implementation slice |
| `/test` | `test` | verification-only work or test evidence collection |
| `/review` | `review` | code, diff, risk, and verification review |
| `/webperf` | `webperf` | browser/web performance measurement and review |
| `/code-simplify` | `code-simplify` | behavior-preserving simplification and refactor cleanup |
| `/ship` | `ship` | release, packaging, rollout, rollback, and launch checks |

The alias should run:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command <route-command> --request "<USER_REQUEST>"
```

Do not let aliases bypass Start Hook, direct reading of the route
`required_docs`, VibeGuard, review hook, finish-check, or repo-local
instructions.

## Controlled Auto Mode

Do not add an unrestricted "auto build" or "auto ship" mode to a runtime bridge.
Automation may proceed without another question only when all of these are true:

- the user approved the goal or the repo has an explicit auto-run policy;
- project discovery selected exactly one target repo;
- the route command, docs, gates, and verification surface are known;
- destructive work, external writes, deploys, migrations, publishing,
  credential changes, and paid-usage increases are out of scope or separately
  approved;
- the parent has valid preflight state, directly reads its routed `required_docs`,
  owns the single review hook and finish-check, and every worker runs only its
  bounded implementation or verification responsibility.

If any condition fails, the runtime should stop at a decision point instead of
continuing under an "auto" label.

If a required route gate fails, the runtime must stop finalization, preserve the
first failed checkpoint, roll back only dependent agent-made changes when safe,
and run the canonical retrospective workflow. It must improve and verify the
owning Tao Agent OS document, hook, validator, or test before resuming that
checkpoint. One repair cycle is allowed; the same failure signature or an
unsafe or ambiguous repair stops the run.

Human-visible signals are checked inside the workflow:

- `🐱🟢 SUCCESS`: executed with evidence; the gate can be counted as complete.
- `🐱🔴 FAIL`: blocked, failed, missed, or missing evidence after the gate should
  have run; run missed-gate recovery.

Do not report any third gate state. Gates that have not been reached are simply
absent from progress reports.

## Verification

After connecting a runtime, verify:

- the target repo instruction file points to the selected Tao Agent OS root
- `agent-entry.py` or `project-discover.py` selects the target repo when the
  runtime starts outside it, or stops with `ambiguous` / `not_found`
- workspace group aliases either select a clear member repo or return primary
  candidates with workspace scope guidance instead of guessing
- the runtime still reads the target repo's current agent instructions first
- existing runtime-specific files, such as `CLAUDE.md`, `CODEX.md`, or
  Antigravity docs, are updated or intentionally not created because the
  runtime reads `AGENTS.md`
- `AGENTS.md`, `index.md`, and `scripts/workflow.py` exist under that root
- `setup-agent-hooks.py --check` passed or missing user-level hooks or
  permissions were installed after approval
- the VibeGuard gate passed or stopped with a reported blocker
- multi-step work has preflight and finish-check evidence when wrapper scripts
  are available
- multi-step startup uses one `agent-hook.py start` invocation followed by
  direct reading of the selected `required_docs`, without a duplicated
  list/classify/route/preflight or document-confirmation sequence
- `agent-hook.py handoff` refreshes and validates the content-free execution
  capsule once, reuses startup evidence only after a ready-and-valid result,
  returns a successful normal-lifecycle fallback decision on mismatch, uses
  worker-specific evidence paths for that fallback, and leaves the parent gate
  ledger unchanged
- `<TAO_LAUNCHER> agent-mailbox --help` resolves through the installed stable
  launcher, and focused tests prove exact active-work send binding, project and
  source-run isolation, TTL and size caps, atomic one-time consumption,
  body-free acknowledgement records, symlink refusal, next-prompt runtime guidance,
  and the absence of provider, network, daemon, watcher, or polling adapters
- VibeGuard evidence was summarized through VibeGuard docs when an evidence
  adapter was configured
- the route gate ledger was completed for every multi-step task
- the agent can produce a route, such as:

```text
<TAO_LAUNCHER> workflow route task --request "<USER_REQUEST>"
```

## Stop If

- The target runtime does not have file access and the user cannot paste the
  one-shot prompt.
- Project discovery is ambiguous or missing and the user has not chosen a
  target project.
- The Tao Agent OS root cannot be located.
- The VibeGuard command cannot run after using the installed binary or the
  published package fallback.
- Repo-local instructions conflict with Tao Agent OS on security, data,
  deployment, cost, or verification behavior.
