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

## Setup Modes

Select one mode before wiring a runtime:

- Existing local install: required by default when Tao Agent OS is already
  present on the machine. Reuse that root and do not clone another copy unless
  the user explicitly approves a new copy after seeing the found path.
- First-time local shared install: clone once to a stable path such as
  `~/.tao-agent-os` when no usable root exists.
- Team-pinned install: use a submodule, vendored dependency, or workspace
  dependency when every teammate and agent must use the same reviewed version.

A usable root contains `AGENTS.md`, `index.md`, and `scripts/workflow.py`.
Validate the selected root with:

```text
<TAO_LAUNCHER> workflow validate
```

Check runtime bridges, hooks, and permission allowlists with:

```text
<TAO_LAUNCHER> setup-agent-hooks --check
```

If bridges, hooks, or permissions are missing, ask for approval to write
user-level runtime config, then run:

```text
<TAO_LAUNCHER> setup-agent-hooks
```

To repair only one runtime without touching other agent settings, pass its
runtime selector. For example, Codex-only setup uses:

```text
<TAO_LAUNCHER> setup-agent-hooks --runtime codex
```

A runtime-scoped check or repair validates and changes that runtime's managed
bridge and permission rules only. In particular, `--runtime codex` must not
run, require, or alter global Graphify setup; use the unscoped setup or the
explicit target Graphify flow when Graphify is in scope.

This setup is global because the Tao Agent OS Python wrappers and graph-backed
document routing are shared by every target repo. Keep it narrow: install or
repair only Tao Agent OS-managed bridge blocks and allow only
Tao Agent OS-managed entrypoints and suffix-aware runtime matchers. Do not
broadly allow `python3`.
For Claude, `setup-agent-hooks.py` installs a stable user-level launcher at
`<TAO_LAUNCHER>` and writes the current checkout to
`~/.tao/tao-root`. Rerun setup after moving or migrating
Tao Agent OS so the pointer is refreshed without changing the Claude hook
command.

Claude's runtime bridge is otherwise advisory: unlike the Codex prefix rule,
prose alone does not stop a file edit when the agent skipped `start`. To make
workflow entry and continuation enforceable, `setup-agent-hooks.py` installs:

- a `SessionStart` continuation hook for `startup|resume|fork`;
- the Claude `PreToolUse` workflow/checkpoint gate for
  `Edit|Write|MultiEdit|NotebookEdit`;
- matching `PostToolUse` and `PostToolUseFailure` continuation hooks; and
- the existing `Stop` finish gate.

The start hook allocates `.tao/runs/<opaque-run-id>/preflight.json` when Claude
supplies a runtime session id. Every later hook uses the common exact-session
resolver and requires runtime name, session id, registry evidence key, and
resume generation to identify that path; `.tao/preflight.json`, freshness
alone, and newest-file selection never unlock editing. `PreToolUse` fails closed
when the required pre-mutation checkpoint cannot be written. The post hooks
clear the pending mutation after success or failure and block the next agentic
step when reconciliation is required. Non-edit tools and directories outside
Tao Agent OS remain outside this gate. Tune the freshness window with
`TAO_CLAUDE_GATE_MAX_AGE_SECONDS` (default 8 hours).

Claude's file tools expose one exact `file_path`, so they can be bracketed
automatically. Arbitrary `Bash` commands do not expose a trustworthy changed
path set. Agents must bracket a shell command, formatter, or generator that may
write with the provider-neutral `checkpoint --checkpoint-kind pre_mutation`
and `post_mutation` commands and the complete bounded path set. Do not parse
command prose to guess ownership or describe Bash as automatically covered.
When executing Tao Agent OS wrapper commands from an agent runtime, replace
`<TAO_ROOT>` with the resolved absolute path. Do not leave `$HOME`,
`${HOME}`, `~`, or a relative path in the executable command.

Spill token metering is an optional local bridge, not a Tao Agent OS
dependency. Tao Agent OS setup does not install token-usage event hooks; those
belong to the Spill installer. If the local Spill setup helper exists,
`setup-agent-hooks.py` may add Tao Agent OS-managed safe workflow label hooks
and runtime env for that bridge. If the helper is absent, the setup removes
only those Tao Agent OS-managed Spill label hooks/env and keeps the Python
wrapper permissions installed.

For Codex, Claude, and Gemini/Antigravity/AGY, `setup-agent-hooks.py` manages a
short user-level bridge block in the runtime's instruction file; `--check` reports it
as missing when the block is absent or stale. The block must tell the runtime
to identify the target project, open the project-root instruction file, route
the current request, use `workflow-doc-surfaces.json` and the local document
graph for document discovery, read the route's `required_docs`, and stop before
routing, editing, testing, committing, or reporting completion when it cannot
confirm the bridge or project-root instruction file. It must also keep setup,
hook, permission, helper, label, and background metering details out of normal
conversation unless the user explicitly asks about that subsystem.

If a usable root is found, runtime setup must stop install selection there and
reuse it. Do not download, clone, vendor, copy, overwrite, or add a second root
unless the user approves this question:

```text
Tao Agent OS already exists locally at <path>. Do you want me to download or
pin a new copy anyway, or should I reuse the existing root?
```

## Project Discovery Entry

When a runtime starts from a personal directory such as `~`, or when the target
repo is not explicit in the current request, resolve the project before reading
project docs or running task commands. Use the local entry helpers:

```text
<TAO_LAUNCHER> project-discover --request "<USER_REQUEST>" --cwd "<CURRENT_DIRECTORY>"
<TAO_LAUNCHER> agent-entry --runtime <codex|claude|antigravity|generic> --request "<USER_REQUEST>" --cwd "<CURRENT_DIRECTORY>"
```

`project-discover.py` returns one of three states:

- `selected`: a single target project is safe to use; open its instruction
  files before project work.
- `ambiguous`: multiple candidates have comparable evidence; ask the user to
  choose one before reading project docs, editing, testing, committing, or
  reporting completion.
- `not_found`: no usable project was found; ask for the target path before
  project work.

`agent-entry.py` wraps the same discovery result with the Tao Agent OS root,
workflow script, preflight script, finish-check script, selected project
instruction files, workspace scope guidance, runtime launch guidance, and
next-step checklist. User-level runtime bridges should call it when the current
working directory might not be the target project.

Project discovery uses safe local evidence only: explicit paths in the request,
the current working directory, common project markers, repo-local instruction
files, configured search roots, and an optional local registry. It does not
scan broad home directories by default; pass `--search-root` for a known parent
or `--include-default-search-roots` only when the user accepts that broader
search cost and ambiguity risk. It must not use prompt guessing as a substitute
for a selected project. If the result is ambiguous or missing, stop and ask.

Optional local project registry:

```json
{
  "projects": [
    {
      "root": "~/Downloads/nunu-os-main",
      "aliases": ["nunu", "nunu-os"]
    }
  ],
  "workspace_groups": [
    {
      "name": "product-x",
      "aliases": ["product-x"],
      "members": [
        {
          "role": "app",
          "root": "~/GitHub/product-x-app",
          "aliases": ["app", "desktop"]
        },
        {
          "role": "web",
          "root": "~/GitHub/product-x-web",
          "aliases": ["web"]
        }
      ]
    }
  ],
  "search_roots": ["~/Documents", "~/Downloads"]
}
```

Store that file at `~/.tao/projects.json`, or pass a specific path
with `--registry`. The registry is local machine state and may contain personal
paths; do not commit it to target repos. This is separate from global
retrospective lessons, which must remain reusable and path-free.

Use `workspace_groups` when a product alias can mean several repos, such as an
app shell, web surface, shared API, or docs repo. If only the group alias
matches the request, discovery should not guess a single repo. It should return
the primary candidates and require a target decision. If a member alias also
matches, such as `web` or `desktop`, that member can become the selected
primary repo.

## Runtime Launch Root Discipline

Project instructions and runtime launch roots solve different problems.
`AGENTS.md`, `CLAUDE.md`, `CODEX.md`, and `.agents/README.md` tell the agent
what behavior to follow. They do not grant filesystem write scope. When a
runtime starts from `~`, a workspace parent, or a different repo, first run
`agent-entry.py`; when it returns `selected`, start or relaunch the runtime with
the selected target project as the primary workspace.

For Codex, use the selected repo as `-C`:

```text
codex -C <TARGET_REPO>
```

When the current task may also edit or run shared Tao Agent OS files, add the
selected Tao Agent OS root explicitly:

```text
codex -C <TARGET_REPO> --add-dir <TAO_ROOT>
```

Use `--add-dir` only for additional roots that belong in the current session's
workspace. Prefer one selected target repo over broad parent folders such as
`~/GitHub` when the target is known. Do not use unrestricted filesystem modes
as the default fix for missing workspace roots.

`agent-entry.py --runtime codex` includes these launch commands in its
`runtime_launch` section after project discovery succeeds. User-level runtime
bridges may show this section to the operator or use it as a relaunch hint, but
they must still stop on `ambiguous` or `not_found`.

## Cross-Repo Scope Checkpoint

For multi-repo products, distinguish the primary repo from secondary repos:

- Primary repo: the repo whose user path or acceptance result defines success
  for the current task.
- Secondary repo: a repo that may need to be read or changed because it owns a
  web route, app bridge, shared contract, API schema, configuration, docs, or
  other source of truth.

Start with the primary repo when the request is clear. During orientation, stop
for a workspace scope checkpoint before writing to a secondary repo. The
checkpoint must state:

```text
starting primary:
new source of truth:
secondary repo:
mode: single-repo | primary-led secondary read | primary-led secondary write | multi-session
write scope:
verification:
session model:
```

Use these modes:

- `single-repo`: only the primary repo is changed and verified.
- `primary-led secondary read`: the primary repo remains the only write target;
  the secondary repo is inspected to confirm contracts or behavior.
- `primary-led secondary write`: the primary repo owns acceptance, but a small
  secondary repo change is needed. Use one session with the primary as `-C` and
  the secondary as an added workspace only when the write scope is small and
  clearly bounded.
- `multi-session`: both repos need meaningful implementation, verification, or
  commits. Use separate sessions and a lead agent or lead checklist for the
  shared contract, ordering, verification, and commit split.

Do not silently broaden from one repo to another because investigation found a
related file. If the secondary change is more than a small bounded contract,
route, bridge, config, or docs update, prefer `multi-session`.

When wrapper finish evidence is available and a secondary repo was written,
record one of these checkpoints through the gate hook before finish:

```text
agent-hook.py gate --gate-name "workspace scope checkpoint" --status SUCCESS --gate-evidence "<checkpoint evidence>"
agent-hook.py gate --gate-name "scope expansion checkpoint" --status SUCCESS --gate-evidence "<checkpoint evidence>"
agent-hook.py gate --gate-name "cross-repo scope checkpoint" --status SUCCESS --gate-evidence "<checkpoint evidence>"
```

The finish-check policy validates that the evidence names the starting primary
repo, secondary/source-of-truth repo, chosen mode, and cross-repo verification.

## Long-Lived Repo Setup

For repos that will keep using Tao Agent OS, add a short routing block to the
instruction file each agent runtime reads:

- Codex-style runtimes: `AGENTS.md`.
- Claude-style runtimes: `CLAUDE.md`.
- Codex-specific local docs: `CODEX.md` when the repo already uses it.
- Gemini/Antigravity/AGY: `AGENTS.md`.
- Generic agents: the project instruction file the runtime actually reads, or
  `.agents/README.md` when the repo uses a shared agent folder.
- Personal or global runtime docs: treat these as optional Step 2 bridge work.
  Update them only when the user chooses the stronger future-behavior setup.
  Examples include `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`,
  `~/.antigravity`, `~/.antigravitycli`, and `~/.antigravity-ide`.

Prefer one canonical instruction file, usually `AGENTS.md`, when all active
runtimes read it. When `CLAUDE.md`, `CODEX.md`, `.agents/README.md`, or
Antigravity CLI docs already exist, update them in the same application pass so
they point to the selected Tao Agent OS root or back to `AGENTS.md`. Do not
create a separate runtime-specific file only to duplicate guidance that the
runtime already reads from `AGENTS.md`.

Every runtime bridge must explicitly tell the agent to read the current target
project's own instructions first. Do not rely on implicit discovery. State the
runtime-specific entrypoint directly: Codex-style agents should read the current
project's `AGENTS.md`, Claude should read the current project's `CLAUDE.md`
when present, Codex-specific setups should read `CODEX.md` when present, and
Gemini/Antigravity/AGY should read the current project's `AGENTS.md`.
Then tell the agent to follow Tao Agent OS as shared guidance only after those
local instructions.

After the start hook and required-doc reading, runtime bridges must also tell
the parent agent to consume `parallel_execution.delegation_policy`. When
the active runtime exposes workers and the multi-agent collaboration skill finds
at least two meaningful disjoint slices with a stable contract, integration
owner, and focused verification, the parent delegates automatically without
waiting for explicit user multi-agent wording. Otherwise it records the
concrete serial reason. At each parent-to-worker boundary, run `agent-hook.py
handoff` to refresh and validate the shared execution capsule before a worker
reuses parent startup evidence.
Keep eligibility and capsule details in their canonical shared skills; the
bridge is only the invocation pointer. Map eligible execution to the runtime's
native primitive: Codex subagents/parallel workers, Claude Agent/Task workers,
or the Gemini/AGY Antigravity parallel runner.

Use `templates/repo-agents-routing.md` as the source block. Keep the block
short and point to:

```text
<TAO_ROOT>/AGENTS.md
<TAO_ROOT>/index.md
<TAO_ROOT>/scripts/agent-entry.py
<TAO_ROOT>/scripts/project-discover.py
<TAO_LAUNCHER>
<TAO_ROOT>/scripts/workflow.py
<TAO_ROOT>/scripts/setup-agent-hooks.py
<TAO_ROOT>/scripts/agent-preflight.py
<TAO_ROOT>/scripts/agent-finish-check.py
```

For committed repo-local instruction files, keep the root reference portable.
Use `${TAO_HOME}` when each machine can set the variable, or a
repo-relative pinned path such as `.agents/tao-agent-os` when Tao Agent OS is
kept with the target repo. Do not commit personal absolute paths such as
`/Users/.../tao-agent-os`; keep them in shell environment setup, one-shot
prompts, or uncommitted user-level runtime bridges only.

Do not paste the full Tao Agent OS library into runtime-specific files.

For Graphify specifically, follow
`docs/skills/graphify-project-integration/SKILL.md`: the canonical project
bundle lives at `.tao/skills/graphify`, while only the Graphify
discovery paths below `.codex`, `.claude`, and `.agents` are repo-relative
links or genuinely runtime-specific hooks, rules, workflows, and registration.
Other project-local knowledge under those directories remains independently
owned project input and must not be hidden by a blanket runtime-directory rule.

## One-Shot Prompt Setup

Use one-shot prompting when:

- the target repo is not wired yet
- the agent runtime does not automatically load repo instruction files
- you are using a web chat or temporary session
- you want Claude, Gemini/Antigravity/AGY, or another agent to follow
  Tao Agent OS for one task without changing repo files

Paste `templates/use-tao-prompt.md` into the agent, replacing the
target repo, task, Tao Agent OS root, and VibeGuard docs placeholders.

The prompt explicitly tells the runtime to read `AGENTS.md` and `index.md`,
because not every agent automatically discovers Codex-style `AGENTS.md` files.

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
