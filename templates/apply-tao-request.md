---
keyflow_id: sys_apply_tao_request_template
status: review
type: human-reviewed-needed
---

# Apply Tao Agent OS Request

Paste this into an AI coding agent when you want it to connect a project to
Tao Agent OS.

Use `templates/use-tao-prompt.md` instead when you only want one task
to follow Tao Agent OS without changing repo-local instruction files.

## Step 1: Required Application Prompt

```text
Step 1 - Apply Tao Agent OS to this project:
https://github.com/taehwandev/tao-agent-os

Tao Agent OS stable launcher:
<TAO_LAUNCHER>

Resolve that placeholder to the installed launcher's absolute path. Do not
invoke an internal runtime Python entrypoint directly.

Before changing anything, open and read this project's current agent instructions first:
AGENTS.md, CLAUDE.md, CODEX.md, .agents/README.md, CONTRIBUTING.md, task docs,
PRD/ARD docs, equivalent project docs, or explicitly documented local override
files.
Do not rely on implicit runtime discovery: Codex-style agents must explicitly
read the current project's AGENTS.md, Claude must explicitly read CLAUDE.md
when present, Antigravity agents must explicitly read the current project's
AGENTS.md, and generic agents must explicitly read the project instruction
document they are configured to load.
Do not claim the file was read unless you actually opened it.
If the target project is not explicit or the runtime starts outside the target,
run the Tao Agent OS entry helper before reading project docs:

<TAO_LAUNCHER> agent-entry --request "<USER_REQUEST>" --cwd "<CURRENT_DIRECTORY>" --runtime <RUNTIME>

Continue only when it returns `selected`. If it returns `ambiguous` or
`not_found`, ask me for the target project instead of guessing.

Use an existing local Tao Agent OS install if one is available. Check an
explicit path from me first, then TAO_HOME, then common local clones
such as ~/.tao-agent-os, ~/git/tao-agent-os, or ~/GitHub/tao-agent-os.

If any usable local or repo-pinned Tao Agent OS root exists, stop install
selection there and reuse it. Do not download, clone, vendor, copy, overwrite,
or add a second Tao Agent OS root unless I explicitly approve after you ask:
"Tao Agent OS already exists locally at <path>. Do you want me to download or
pin a new copy anyway, or should I reuse the existing root?"

Select one setup mode and tell me which one you selected before editing:

- Existing local install: if a usable install exists, link this repo to that
  copy. Do not clone, vendor, or copy a second copy.
- First-time local shared install: if no usable install exists, ask before
  cloning once to ~/.tao-agent-os.
- Team-pinned install: ask before adding Tao Agent OS as a repo-pinned
  submodule, vendored dependency, or workspace dependency.

A usable Tao Agent OS root must contain AGENTS.md, index.md, and
<TAO_LAUNCHER> workflow. Validate it with:

<TAO_LAUNCHER> workflow validate

Check user-level runtime bridges, hooks, and permission allowlists:

<TAO_LAUNCHER> setup-agent-hooks --check

If the check reports missing bridges, hooks, or permissions, ask for approval
to update user-level runtime config, then run:

<TAO_LAUNCHER> setup-agent-hooks

This setup is global by design. It allows only Tao Agent OS-managed
entrypoints with suffix-aware runtime matchers. It must not broadly allow
`python3`.
For Codex, update `~/.codex/rules/default.rules` with the resolved absolute
stable launcher argv prefix only. Do not use `$HOME`, `${HOME}`, `~`, relative
paths, or shell `-lc` wrappers around the launcher: those forms can be treated
as shell expansion or a single shell string before the runtime permission
matcher sees the trusted command. For Claude Code, update
`~/.claude/settings.json` so managed hooks
call `<TAO_LAUNCHER>`, and refresh
`~/.tao/tao-root` to the selected Tao Agent OS checkout so
moves or migrations do not leave Claude pointing at a stale checkout-local
command. For
AGY/Antigravity, support both
`~/.gemini/config/config.json` and
`~/.gemini/antigravity-cli/settings.json`; hooks remain in
`~/.gemini/config/hooks.json`.

Do not install token-usage event hooks from Tao Agent OS. Spill token metering
is optional and belongs to the separate Spill installer. If the local Spill
setup helper exists, Tao Agent OS setup may add a safe workflow label bridge.
If the helper is absent, remove only Tao Agent OS-managed Spill label hooks/env
and keep the normal Tao Agent OS stable launcher permissions.

VibeGuard is required. After selecting the Tao Agent OS root, apply VibeGuard
with the selected Tao Agent OS root as the rule source.

Before changing files, inspect this repo's current agent instructions,
.vibeguard.json, VIBEGUARD.md, and any managed VibeGuard block.

If this repo already has instructions or guardrails, ask me this application
drill before running setup or update:

1. Tao Agent OS link style: add a short pointer, merge into the current
   instruction file, or pin a repo-local copy?
2. VibeGuard handling: audit only with current guardrails, refresh the managed
   block with update, or first-time setup?
3. Scope: apply now and continue my original task, or prepare instructions only?

If I choose audit-only:

npx --yes @taehwandev/vibeguard audit . --rules <TAO_ROOT>

If I explicitly choose to refresh the managed VibeGuard block:

npx --yes @taehwandev/vibeguard update . --rules <TAO_ROOT>
npx --yes @taehwandev/vibeguard audit . --fix --rules <TAO_ROOT>
npx --yes @taehwandev/vibeguard audit . --rules <TAO_ROOT>

If this repo has never used VibeGuard and I choose first-time setup:

npx --yes @taehwandev/vibeguard setup . --rules <TAO_ROOT>
npx --yes @taehwandev/vibeguard audit . --fix --rules <TAO_ROOT>
npx --yes @taehwandev/vibeguard audit . --rules <TAO_ROOT>

For full VibeGuard usage, use https://vibeguard.thdev.app/ as a human
reference. Do not block only because your browsing/fetch tool cannot read that
site. Continue with the package command shape above, and use
`npx --yes @taehwandev/vibeguard --help` if you need to confirm the CLI.

If VibeGuard cannot run, stop and tell me the blocker.

Update the repo-local agent instructions, such as AGENTS.md, CLAUDE.md,
CODEX.md, .agents/README.md, or an explicitly documented local override file,
with a short routing block. Preserve existing project rules. Keep repo-specific
commands, paths, services, product policy, and domain language in this repo.

When writing committed repo-local instruction files, do not commit my personal
absolute path such as /Users/.../tao-agent-os. Use ${TAO_HOME} for a
shared local install, or a repo-relative pinned path such as
.agents/tao-agent-os for a team-pinned install. Full local paths are allowed
only in shell environment setup, one-shot prompts, or uncommitted user-level
runtime bridges. If an existing committed instruction file contains a personal
absolute path, replace it with a portable reference before reporting success.

Prefer AGENTS.md as the canonical instruction file when the active runtimes read
it. If repo-local Claude, Codex, Antigravity CLI, or other runtime instruction
files are present, update their Tao Agent OS pointer in the same pass or point
them back to AGENTS.md. Do not create a separate runtime-specific file only to
duplicate guidance when the active runtime already reads AGENTS.md.

For any multi-step setup or follow-up task, run `<TAO_LAUNCHER> start` once with
`--request "<USER_REQUEST>"` before selecting task documents, editing,
reviewing, committing, or reporting completion. It performs workflow routing
and preflight; do not separately repeat workflow list, classify, route, or
preflight after it succeeds. Direct `<TAO_LAUNCHER> workflow route` and
`<TAO_LAUNCHER> agent-preflight` calls are lower-level diagnostic or compatibility
fallbacks only. If the request is a direct
question, answer it before routing or editing. If the direct question asks how
to start app, product, or feature work, answer with PRD -> ARD ->
implementation gates before lower-level coding steps. If the task proceeds into
code, use the `product` route unless an existing PRD/ARD or repo-local
instruction makes the slice clearly trivial. If the workflow router cannot run,
stop and report the blocker before continuing. Show a gate signal after each
completed or failed gate or task step:

Gate signal: 🐱🟢 SUCCESS | gate: <gate> | evidence: <evidence> | next: <next gate>

Completion requires every required gate to be 🐱🟢 SUCCESS. 🐱🔴 FAIL means the
gate was blocked, failed, missed, or lacks evidence and must use missed-gate
recovery. Do not report any third gate state.

When the wrapper scripts are available, use the single start hook before
editing, reviewing, committing, or reporting completion:

Before executing wrapper commands, replace `<TAO_ROOT>` with the
resolved absolute path; do not leave `$HOME`, `${HOME}`, `~`, or a relative path
in the executable command.

<TAO_LAUNCHER> start --project . --rules <TAO_ROOT> --command <COMMAND> --request "<USER_REQUEST>" [--platform <PLATFORM>] [--concern <CONCERN>]

Read every route `required_docs` entry directly after start and before editing
or reviewing. Use the route's review hook after meaningful edits.

Before final report, commit, release, or handoff, record any remaining manual
gate evidence, then run the read-only finish check:

<TAO_LAUNCHER> gate-batch --project . --rules <TAO_ROOT> --gate-record '[{"gate":"<gate>","status":"SUCCESS","evidence":"<evidence>"}]'
<TAO_LAUNCHER> finish --project . --rules <TAO_ROOT>

Call `<TAO_LAUNCHER> workflow route`, `<TAO_LAUNCHER> agent-preflight`, or `<TAO_LAUNCHER> agent-finish-check`
directly only as lower-level diagnostic or compatibility fallbacks when the
corresponding hook is unavailable; never run them as a second lifecycle.

The wrappers write local evidence under .tao/. Missing wrapper
evidence or missing gate evidence is non-compliant even if the final files look
correct. If final VibeGuard is Needs review, report it explicitly and pass
--allow-vibeguard-review with a reason only when that review state is
acceptable. If --request-classified is used, include classification evidence;
that flag is honored only for a delegated worker backed by a ready and valid
parent execution capsule, and every other caller passes --request with the real
user request and lets the classifier run. If the route is a work route, that
evidence must say clear-scoped, answered with a
separate actionable request, or blockers resolved; classified/done/handled is
not enough, and clarified/no blockers is too generic by itself. If the request
asks for Grill-Me or classification returns grill_me true, missing Grill-Me
protocol or `/grilling` session evidence is 🐱🔴 FAIL.

After connecting it, verify that the referenced Tao Agent OS AGENTS.md and
index.md files exist, confirm the VibeGuard gate is passing, then continue with
my original task.
```

## Step 2: Optional User-Level Bridge Prompt

```text
Optional Step 2 - Register a user-level runtime bridge on this machine.

Use this only if I choose the optional setup for better future agent behavior.
Preserve existing personal instructions. Add or update a short managed block; do
not replace unrelated user content.

Also run the Tao Agent OS runtime setup check:

<TAO_LAUNCHER> setup-agent-hooks --check

If bridges, hooks, or permissions are missing, ask for approval to update
user-level runtime config and then run:

<TAO_LAUNCHER> setup-agent-hooks

Keep the permission allowlist narrow: allow only Tao Agent OS-managed
entrypoints by suffix-aware runtime matcher, not broad `python3`. For Claude
managed hooks, prefer `<TAO_LAUNCHER>` plus the refreshed root pointer
over a moving checkout-local command.
The setup command should install or repair the managed bridge block for Codex,
Claude, and Gemini/Antigravity/AGY when those runtimes are present.

Update the active user-level file for the runtime I choose:
Codex -> ~/.codex/AGENTS.md
Claude -> ~/.claude/CLAUDE.md
Gemini/Antigravity/AGY -> ~/.antigravity/AGENTS.md
Antigravity SDK/IDE variants -> check ~/.antigravity-ide for the instruction
file the active runtime loads.

The bridge must force this behavior:
- Start every task by identifying the current project root.
- If the runtime starts from ~ or another non-project directory, resolve the
  target with `<TAO_LAUNCHER> agent-entry` or `<TAO_LAUNCHER> project-discover` before project work.
- If discovery is `ambiguous` or `not_found`, ask me for the target project
  instead of proceeding.
- Before project work, open the project-root instruction file for the active runtime.
- Codex reads AGENTS.md.
- Claude reads CLAUDE.md.
- Antigravity reads AGENTS.md.
- Do not claim an instruction file was read unless you actually opened it.
- For multi-step work, run `<TAO_LAUNCHER> start` once with my current request;
  it performs Tao Agent OS workflow routing and preflight. Do not separately
  repeat workflow list, classify, route, or preflight after it succeeds.
- Read every route `required_docs` entry directly after start and before editing
  or reviewing. Keep the route's review and finish hooks in the lifecycle.
- Treat direct `<TAO_LAUNCHER> workflow route`, `<TAO_LAUNCHER> agent-preflight`, and
  `<TAO_LAUNCHER> agent-finish-check` calls as lower-level diagnostic or compatibility
  fallbacks only; never run them as a second lifecycle.
- Do not wait for me to name document keywords. Infer the work surface from the
  request, platform, concern, and touched files, then read the route
  `required_docs` before editing or reviewing.
- Use `workflow-doc-surfaces.json` and the local document graph as
  routing/search inputs. Treat graph neighbors as `reference_docs` unless the
  route promotes them to `required_docs`.
- If routing/search misses a clearly relevant platform, concern, or document
  surface, stop and report the gap instead of proceeding from memory.
- If the active runtime is Antigravity and this bridge or the project-root
  AGENTS.md cannot be confirmed, stop before routing, editing, testing,
  committing, or reporting completion and ask for bridge repair.
- Do not mention setup, hook, permission, helper, label, or background metering
  details in normal conversation unless I explicitly ask about that subsystem.
- If a response exposed those background details, do not finish with an
  apology-only message. Repair the action path or stop with the specific
  blocker.
- If I ask a direct question, answer it before routing, editing, or running commands.
- If I ask how to start app, product, or feature work, include PRD -> ARD ->
  implementation before lower-level coding steps.
- If my request is ambiguous and the answer changes behavior, scope, safety, or
  external state, ask before working.
- For multi-step tasks, require Tao Agent OS start and finish hook evidence
  when those wrapper scripts are available; missing wrapper or gate evidence is
  non-compliant.

Optional local project registry for this machine:
~/.tao/projects.json

{
  "projects": [
    {"root": "~/Downloads/nunu-os-main", "aliases": ["nunu", "nunu-os"]}
  ],
  "search_roots": ["~/Documents", "~/Downloads"]
}

Keep this registry local; do not commit personal paths into target repos.
```

For a team-pinned install, add this sentence:

```text
Prefer a repo-pinned submodule or vendored dependency so every teammate and
agent uses the same reviewed Tao Agent OS version.
```
