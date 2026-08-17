---
keyflow_id: sys_e2d59ab64adc
status: stable
type: ai-generated
---

# Tao Agent OS

Tao Agent OS is a reusable guidance and runtime layer for AI coding agents. It gives agents a compact set of operating rules, workflow paths, review criteria, platform guidance, product-pattern checks, and executable lifecycle evidence that can be linked from any software project.

Use it when you want repo-local instructions to stay small while still giving an agent enough shared engineering discipline to plan, edit, review, test, and handoff work reliably.

Repository:

```text
https://github.com/taehwandev/tao-agent-os
```

## Who It Is For

- Teams that use AI coding agents across multiple repositories.
- Solo builders who want consistent agent behavior from project to project.
- Maintainers who want reusable review, safety, architecture, and workflow guidance without copying long prompt files into every repo.
- Tooling authors who need a source library of agent-readable engineering practices.

## What This Is

- A provider-neutral agent operating layer: shared guidance plus lifecycle state, routing, evidence, scheduling, and recovery primitives.
- A source of shared agent instructions, not a replacement for repo-local rules.
- A selective-loading system: agents should read only the cards relevant to the current task.
- A thin runtime boundary: project rules and product policy remain owned by the target repository, while Tao Agent OS owns reusable execution discipline.
- A public, reusable project. No local machine path, private workspace, product name, or personal environment is required.

## What This Is Not

- It is not a beginner product UI.
- It is not a secret scanner, package manager, or safety CLI.
- It is not a place for repo-specific commands, internal paths, credentials, private architecture, role matrices, product policy, or domain language.
- It is not meant to be copied wholesale into every project.

VibeGuard is the required safety gate for applying and maintaining Tao Agent OS. Agents should apply VibeGuard with the published package command and pass the selected Tao Agent OS root as the rule source. The VibeGuard site is the human-facing reference, not a runtime dependency; do not block only because an agent browsing/fetch tool cannot read the site.

Website:

```text
https://tao.thdev.app/
```

Latest release: [Tao Agent OS v26.07.6](https://github.com/taehwandev/tao-agent-os/releases/tag/v26.07.6)

The website includes the current copy-and-paste prompts, application modes, and release link. Use it as the human-facing entry point; this README remains the portable source for installation and repository integration.

Korean update guide: docs/ko/update-tao.md

## Website Deployment Versioning

The public website is a continuously deployed static site. Do not bump a public release version for every `main` merge. Track every deployed revision instead.

- Release unit: continuous deployment from `main`.
- Deployment source: GitHub Pages legacy source, `main` branch, `/docs` path.
- Latest public release: [Tao Agent OS v26.07.6](https://github.com/taehwandev/tao-agent-os/releases/tag/v26.07.6). Use a tag or release note only when a maintainer intentionally groups changes into a public Tao Agent OS release.
- Source revision: the exact Git commit SHA deployed by GitHub Pages.
- Deployment id: the GitHub Pages build id for that Pages build.
- Artifact: the `/docs` tree at the deployed commit. There is no separate package artifact unless a future workflow creates one.
- Rollback path: revert or fix forward on `main`, then let Pages rebuild from `/docs`.

Verification commands:

```bash
gh api repos/taehwandev/tao-agent-os/pages \
  --jq '{status, cname, https_enforced, build_type, source}'
gh api repos/taehwandev/tao-agent-os/pages/builds/latest \
  --jq '{status, commit, created_at, updated_at, duration, error}'
curl -I https://tao.thdev.app/
```

The website versioning contract follows `common/skills/web-deployment-versioning/SKILL.md`: every production deploy must be traceable, but the public release version changes only for a meaningful release unit.

## Quick Start

Choose one setup path first. Existing local or repo-pinned roots are the default. If any usable Tao Agent OS root already exists, do not download, clone, vendor, or copy another one unless the user explicitly approves a new copy after being told which root was found.

### Path A: Existing Local Install

Use this when Tao Agent OS is already on the machine.

1. Locate the existing root. Prefer an explicit path from the user, then `TAO_HOME`, then common local locations such as `~/.tao-agent-os`, `~/tao-agent-os`, `~/git/tao-agent-os`, or `~/GitHub/tao-agent-os`.
2. Verify that the root contains `AGENTS.md`, `index.md`, and the lifecycle scripts. The installed launcher is the preferred execution path: `<TAO_LAUNCHER>`.
3. Point the target repo to that root. Do not clone, vendor, or copy another Tao Agent OS checkout.

If a usable root is found but the agent believes a fresh download is needed, it must ask first:

```text
Tao Agent OS already exists locally at <path>. Do you want me to download or
pin a new copy anyway, or should I reuse the existing root?
```

```bash
export TAO_HOME="/path/to/existing/tao-agent-os"
<TAO_LAUNCHER> workflow validate
```

### Path B: First-Time Local Shared Install

Use this when no usable local or repo-pinned copy exists and the user wants one shared install for multiple personal repos.

```bash
export TAO_HOME="$HOME/.tao-agent-os"
git clone https://github.com/taehwandev/tao-agent-os.git "$TAO_HOME"
<TAO_LAUNCHER> workflow validate
```

### Path C: Team-Pinned Install

Use this when every teammate and agent must use the same reviewed version. Add Tao Agent OS as a submodule, vendored dependency, or workspace dependency only after the repo owner approves the pinned location and update policy.

```bash
git submodule add https://github.com/taehwandev/tao-agent-os.git .agents/tao-agent-os
<TAO_LAUNCHER> workflow validate
```

### Updating An Existing Install

Use Git as the update mechanism. For a personal or shared local checkout, update the selected Tao Agent OS root between tasks:

```bash
cd "${TAO_HOME}"
git pull --ff-only
<TAO_LAUNCHER> workflow validate
npx --yes @taehwandev/vibeguard audit . --rules .
```

Target repos that link to this root do not need their own copied update. The next agent task should read the current files from the selected Tao Agent OS root. Do not auto-pull during an active task; update intentionally between tasks so the workflow rules do not change mid-run.

For a team-pinned submodule, update the pinned commit through the target repo's normal review flow:

```bash
cd <target-repo>
git submodule update --remote .agents/tao-agent-os
<TAO_LAUNCHER> workflow validate
git add .agents/tao-agent-os
```

Public site: `https://tao.thdev.app/#update`

### Connect The Target Repo

After choosing the root, add a short pointer to the target repo's canonical agent instruction file. Prefer `AGENTS.md` when the active runtimes read it. If existing runtime-specific files such as `CLAUDE.md`, `CODEX.md`, `.agents/README.md`, Antigravity CLI docs, or explicitly documented local override files are present, update their Tao Agent OS pointer in the same pass or point them back to `AGENTS.md`. Do not create extra runtime-specific files only to duplicate the same routing block.

Keep committed repo-local instructions portable. Do not write a personal absolute path such as `/Users/.../tao-agent-os` into files that will be shared through Git. Use `${TAO_HOME}` for a shared local install, or a repo-relative path such as `.agents/tao-agent-os` for a repo-pinned install. Personal full paths belong only in shell environment setup, one-shot prompts, or uncommitted user-level runtime bridges.

When starting an agent from `~`, a workspace parent, or another repo, resolve the target first:

```bash
<TAO_LAUNCHER> agent-entry --runtime codex --request "<USER_REQUEST>" --cwd "$PWD"
```

If discovery returns `selected`, use the reported `runtime_launch` guidance for the next session. For Codex, the normal shape is:

```bash
codex -C <TARGET_REPO>
codex -C <TARGET_REPO> --add-dir "${TAO_HOME}"
```

Use the second form only when the task needs the Tao Agent OS root in the session workspace, such as maintaining shared Tao Agent OS docs, scripts, or runtime bridges. Repo instruction files decide behavior; `-C` and `--add-dir` decide which filesystem roots the runtime can use without repeated prompts.

For products that span several repos, add a local workspace group to `~/.tao/projects.json` instead of relying on prompt guessing:

```json
{
  "workspace_groups": [
    {
      "name": "product-x",
      "aliases": ["product-x"],
      "members": [
        {"role": "app", "root": "~/GitHub/product-x-app", "aliases": ["app", "desktop"]},
        {"role": "web", "root": "~/GitHub/product-x-web", "aliases": ["web"]}
      ]
    }
  ]
}
```

When an agent starts in one repo and discovers that another repo must be written, it should stop for a workspace scope checkpoint before that write. The checkpoint names the starting primary repo, secondary/source-of-truth repo, selected mode, write scope, session model, and cross-repo verification.

```text
Shared Tao Agent OS guidance:
${TAO_HOME}/AGENTS.md
${TAO_HOME}/index.md
<TAO_LAUNCHER>
<TAO_LAUNCHER> workflow
<TAO_LAUNCHER> setup-agent-hooks
<TAO_LAUNCHER> agent-preflight
<TAO_LAUNCHER> agent-finish-check

Use repo-local instructions first.
For multi-step tasks, run `<TAO_LAUNCHER> start` once. It performs routing and
preflight; then read every route required_docs entry directly before work.
Use the review hook after meaningful edits and the finish hook before final
report, commit, release, or handoff. Direct <TAO_LAUNCHER> workflow route,
<TAO_LAUNCHER> agent-preflight, and <TAO_LAUNCHER> agent-finish-check calls are lower-level diagnostic
or compatibility fallbacks only; never run them as a second lifecycle.
Use the shared index only to select the smallest relevant document set.
Do not load every shared document by default.
```

You can also vendor this repository as a submodule or workspace dependency if your team wants a pinned version.

### Safety Gate

VibeGuard is required in every distribution mode, but its commands and operating details live in VibeGuard docs. The Tao Agent OS-side contract is to pass the selected Tao Agent OS root as the rule source.

Do not run `setup` or `update` blindly. First inspect the target repo for existing agent instructions, `.vibeguard.json`, `VIBEGUARD.md`, or a managed VibeGuard block. When any of those exist, ask a short application drill before changing files:

```text
Application drill:
1. Tao Agent OS link style: add a short pointer (recommended), merge into the
   current instruction file, or pin a repo-local copy?
2. VibeGuard handling: audit only with current guardrails (recommended for
   existing custom docs), refresh the managed block with update, or first-time
   setup?
3. Scope: apply now and continue the original task, or prepare instructions
   only?
```

After the user answers, use the matching command shape.

Audit only, preserving existing guardrails:

```bash
export TAO_HOME="/path/to/existing/tao-agent-os"
<TAO_LAUNCHER> workflow validate
npx --yes @taehwandev/vibeguard audit . --rules "${TAO_HOME}"
```

Refresh an existing managed VibeGuard block only when explicitly requested:

```bash
export TAO_HOME="/path/to/existing/tao-agent-os"
<TAO_LAUNCHER> workflow validate
npx --yes @taehwandev/vibeguard update . --rules "${TAO_HOME}"
npx --yes @taehwandev/vibeguard audit . --fix --rules "${TAO_HOME}"
npx --yes @taehwandev/vibeguard audit . --rules "${TAO_HOME}"
```

First-time VibeGuard setup only when the target has no guardrails yet:

```bash
export TAO_HOME="/path/to/existing/tao-agent-os"
<TAO_LAUNCHER> workflow validate
npx --yes @taehwandev/vibeguard setup . --rules "${TAO_HOME}"
npx --yes @taehwandev/vibeguard audit . --fix --rules "${TAO_HOME}"
npx --yes @taehwandev/vibeguard audit . --rules "${TAO_HOME}"
```

Full VibeGuard usage for humans: `https://vibeguard.thdev.app/`

If an agent cannot fetch that site, continue with the package command shape above. To confirm the current CLI surface, run:

```bash
npx --yes @taehwandev/vibeguard --help
```

When applying Tao Agent OS, use the selected Tao Agent OS root as the VibeGuard rule source. If VibeGuard cannot run, report the blocker instead of bypassing the gate. Do not copy full VibeGuard onboarding or command reference material into public Tao Agent OS docs; link to VibeGuard's current instructions.

## Apply With Any AI Agent

Give an AI coding agent this request:

```text
Apply Tao Agent OS to this project:
https://github.com/taehwandev/tao-agent-os

If Tao Agent OS already exists locally, link this repo to the existing copy.
Do not clone, vendor, or copy a second copy unless no usable local copy exists.
If a usable local copy exists but you think a fresh copy is needed, ask me
first: "Tao Agent OS already exists locally at <path>. Do you want me to
download or pin a new copy anyway, or should I reuse the existing root?"
Inspect the current repo instructions and VibeGuard files first. If either
already exists, ask me a short application drill before running setup or update.
Use the selected Tao Agent OS root as the VibeGuard rule source. For
multi-step work, run the stable launcher once:
`<TAO_LAUNCHER> start --request "<USER_REQUEST>"`.
It owns routing and preflight; read its required documents before editing.
Update the repo-local agent instructions with a short routing block. Keep
repo-specific commands, paths, services, product policy, and domain language in
this repo. In committed repo-local instruction files, use a portable
Tao Agent OS root reference: `${TAO_HOME}` for shared local installs
or a repo-relative pinned path such as `.agents/tao-agent-os`; do not commit my
personal absolute path. If existing repo-local Claude, Codex, Antigravity, or
other runtime instruction files are present, update the necessary Tao Agent OS
pointer there in the same pass. If the runtime reads AGENTS.md, do not create a
duplicate runtime-specific file. Treat user-level runtime bridges as optional
Step 2 work, not part of the required application prompt.
```

### Actual Application Flow

When an agent applies Tao Agent OS to a target repo, it should execute this flow instead of copying the whole library:

 1. Identify the target repo and read its existing local instructions first.
 2. Choose one setup mode: existing local install, first-time local shared install, or team-pinned install.
 3. If any usable local or repo-pinned root exists, stop install selection there and reuse it unless the user explicitly approves a new download or pinned copy.
 4. Validate the selected Tao Agent OS root with `<TAO_LAUNCHER> workflow validate`.
 5. Inspect existing VibeGuard and repo-local instruction files. Ask the application drill when the repo already has custom instructions or guardrails.
 6. Apply the selected VibeGuard mode with the selected Tao Agent OS root as the rule source: audit-only, refresh with `update`, or first-time `setup`.
 7. Add a short routing block to the repo instruction file the agent runtime actually reads, preferring `AGENTS.md` when supported.
 8. Use a portable Tao Agent OS root reference in committed repo-local files: `${TAO_HOME}` for shared local installs or a repo-relative pinned path such as `.agents/tao-agent-os`. Personal absolute paths are allowed only in shell env setup, one-shot prompts, or uncommitted user-level runtime bridges. Replace existing committed personal paths before reporting success.
 9. Keep repo-specific commands, paths, services, product policy, and domain language in the target repo.
10. Update any existing runtime-specific instruction files, such as `CLAUDE.md`, `CODEX.md`, `.agents/README.md`, or Antigravity CLI docs, so they point to the same Tao Agent OS root or back to `AGENTS.md`.
11. Do not create new runtime-specific instruction files when the active runtime already reads `AGENTS.md`.
12. Offer optional Step 2 for user-level runtime bridges. Only update personal or global runtime instruction files when the user chooses that option. The bridge must explicitly tell the runtime to read the current target project's local instructions first: Codex-style agents read `AGENTS.md`, Claude reads `CLAUDE.md`, and Antigravity reads `AGENTS.md`.
13. For multi-step follow-up work, run `<TAO_LAUNCHER> start ... --request "<USER_REQUEST>"` once and follow its route and gate ledger. It performs classification, routing, and preflight; do not repeat those commands after a successful start. Answer direct questions before start.
14. Read every route `required_docs` entry directly after start, run the review hook after meaningful edits, and run the finish hook before final report, commit, release, or handoff. Direct `<TAO_LAUNCHER> workflow route`, `<TAO_LAUNCHER> agent-preflight`, and `<TAO_LAUNCHER> agent-finish-check` calls are lower-level diagnostic or compatibility fallbacks only.
15. Before reporting success, verify the routing block, VibeGuard gate result, and any route gates that were required.

## Prompt A Local Agent

When prompting Codex, Claude, Antigravity, or another local agent inside a project, tell it to read the current project's own agent instructions first. That keeps project commands, paths, product policy, and local constraints in the target repo while Tao Agent OS supplies shared workflow discipline.

Use this shape for one task:

```text
Use this project's current agent instructions first.
Read whichever exist in the target repo:
AGENTS.md, CLAUDE.md, CODEX.md, .agents/README.md, CONTRIBUTING.md, task docs,
PRD/ARD docs, equivalent project docs, or explicitly documented local override
files.
Do not rely on implicit runtime discovery. Codex-style agents should explicitly
read the current project's AGENTS.md, Claude should read CLAUDE.md when
present, and Antigravity should read the current project's AGENTS.md before
Tao Agent OS.

Then use Tao Agent OS:
<TAO_ROOT>/AGENTS.md
<TAO_ROOT>/index.md
<TAO_LAUNCHER>
<TAO_LAUNCHER> workflow
<TAO_LAUNCHER> agent-preflight
<TAO_LAUNCHER> agent-finish-check

Apply the required VibeGuard safety gate with <TAO_ROOT> as the rule
source before editing. Use the published VibeGuard package command; the
VibeGuard site is a human reference and does not need to be fetched by the
agent.
For multi-step work, run `<TAO_LAUNCHER> start` once with `--request
"<USER_REQUEST>"`; it performs routing and preflight. Read every route
`required_docs` entry directly before work and follow the gate ledger. If the
user asks a direct question, answer it before starting project work. Run the
review hook after meaningful edits and the finish hook before final report,
commit, release, or handoff. Direct `<TAO_LAUNCHER> workflow route`, `<TAO_LAUNCHER> agent-preflight`,
and `<TAO_LAUNCHER> agent-finish-check` calls are lower-level diagnostic or compatibility
fallbacks only. Missing wrapper evidence or missing route gate evidence is
non-compliant.
After each completed or failed gate or task step, show:
Gate signal: 🐱🟢 SUCCESS | gate: <gate> | evidence: <evidence> | next: <next gate>

Completion requires every required gate to be 🐱🟢 SUCCESS. 🐱🔴 FAIL means the
gate was blocked, failed, missed, or lacks evidence and must use missed-gate
recovery. Do not report any third gate state.

For PRD-only work:
<TAO_LAUNCHER> start --command prd --request "<USER_REQUEST>" --platform <platform> --concern <concern>

For PRD -> ARD -> implementation:
<TAO_LAUNCHER> start --command product --request "<USER_REQUEST>" --platform <platform> --concern <concern>
```

Full bootstrap instructions live in docs/skills/agent-bootstrap/SKILL.md. A shorter reusable prompt lives in templates/apply-tao-request.md.

## Use With Codex, Claude, And Antigravity

Tao Agent OS is not tied to one runtime. Codex and Antigravity may discover `AGENTS.md` directly, while Claude or generic agents may need a repo-local bridge file or a pasted prompt.

- For long-lived repo setup, add the routing block from templates/repo-agents-routing.md to the instruction file the runtime reads, preferring `AGENTS.md` when supported. If `CLAUDE.md`, `CODEX.md`, `.agents/README.md`, or Antigravity CLI docs already exist, update their pointer in the same pass instead of leaving stale runtime guidance.
- For one-shot use, paste templates/use-tao-prompt.mdinto the agent with the target repo, task, Tao Agent OS root, and VibeGuard docs link filled in.
- For stronger future behavior, use the optional Step 2 prompt in templates/apply-tao-request.mdto update user-level runtime bridges such as `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.antigravity`, `~/.antigravitycli`, or `~/.antigravity-ide`. The managed bridge must route the current request before document selection, use the local document graph and `workflow-doc-surfaces.json`, and read the route's `required_docs` even when the user did not name document keywords.
- When a runtime starts from `~` or another non-project directory, resolve the target first with `<TAO_LAUNCHER> agent-entry --request "<USER_REQUEST>" --cwd "<CURRENT_DIRECTORY>" --runtime <RUNTIME>`. Continue only when it returns `selected`; ask the user when it returns `ambiguous` or `not_found`. Optional local aliases can live in `~/.tao/projects.json`.
- To avoid repeated prompts for Tao Agent OS commands, run `<TAO_LAUNCHER> setup-agent-hooks --check`, then run `<TAO_LAUNCHER> setup-agent-hooks` after approval if user-level bridges, hooks, or permissions are missing. This writes short managed bridge blocks for Codex, Claude, and AGY plus global runtime config only for Tao Agent OS-managed entrypoints; it does not broadly allow `python3`. Codex and AGY permissions use the resolved absolute stable launcher path, not `$HOME`, `~`, relative paths, or shell `-lc` strings. Claude managed hooks use the same launcher plus a refreshed `~/.tao/tao-root` pointer, so moving or migrating the checkout does not leave `~/.claude/settings.json` pointing at a stale checkout-local command. Rerun setup after moving Tao Agent OS to refresh that pointer and repair stale managed bridges and hooks.
- Spill token metering is optional and separate. Tao Agent OS does not install token-usage event hooks. If the local Spill setup helper is present, `<TAO_LAUNCHER> setup-agent-hooks` may wire a safe workflow label bridge; if the helper is absent, it removes only Tao Agent OS-managed Spill label hooks/env and leaves Tao Agent OS routing and evidence wrappers working normally.
- For Codex, Claude, and Antigravity/AGY, `<TAO_LAUNCHER> setup-agent-hooks --check` also verifies the managed user bridge in the runtime's user-level instruction file. A missing or stale bridge is treated as missing setup so the runtime cannot proceed as if project discovery, graph-backed document routing, fail-closed, and silence rules were installed.
- For runtime-specific setup rules, read docs/skills/agent-runtime-integration/SKILL.md.

## Distribution Modes

- Existing local install: required by default when the user already has Tao Agent OS. Link the target repo to that root and do not reinstall unless the user explicitly approves a new copy after seeing the found path.
- Local shared install: clone once to `~/.tao-agent-os` and reuse it across personal repos.
- Team-pinned install: add Tao Agent OS as a git submodule or vendored dependency when every teammate and agent must use the same reviewed version.

In every mode, VibeGuard is mandatory. Tao Agent OS names that requirement and the selected rule source; VibeGuard owns the operating flow. Use the published VibeGuard package command, with <https://vibeguard.thdev.app/> as the human-facing reference. If an agent browsing/fetch tool cannot read the site, do not treat that alone as a blocker. If the VibeGuard command itself cannot run, report the blocker instead of bypassing the gate. The target repo keeps its own commands, paths, services, product policy, and domain rules. Tao Agent OS provides shared defaults only.

## Workflow Router

For multi-step work, agents generate the route manifest through one start hook before selecting documents manually, editing, reviewing, committing, or reporting completion:

```bash
<TAO_LAUNCHER> start --command product --request "<USER_REQUEST>" --platform web --concern security --concern ui
```

The start hook performs classification, routing, and preflight. Read its `required_docs` directly before work; do not separately repeat the lower-level commands. Use these only for diagnostics, compatibility fallback, or route development when the start hook is unavailable:

```bash
<TAO_LAUNCHER> workflow list
<TAO_LAUNCHER> workflow classify "Change the button on home"
<TAO_LAUNCHER> workflow route triage --request "Change the button on home"
<TAO_LAUNCHER> workflow route product --request "<USER_REQUEST>" --platform web --concern security --concern ui
<TAO_LAUNCHER> workflow route feature --request "<USER_REQUEST>" --platform kmp --concern compose --concern state
<TAO_LAUNCHER> workflow route feature --request "<USER_REQUEST>" --platform flutter --concern widget --concern state
<TAO_LAUNCHER> workflow route docs-review --request "<USER_REQUEST>" --concern wiki
<TAO_LAUNCHER> workflow validate
```

Supported commands are `ambiguity`, `bugfix`, `docs`, `docs-review`, `feature`, `multi-agent`, `planning`, `prd`, `product`, `refactor`, `release`, `retrospective`, `review`, `task`, and `triage`.

Supported platforms are `android`, `application`, `flutter`, `ios`, `kmp`, `server`, and `web`. Supported concerns are `accessibility`, `aeo`, `ai-mode`, `ai-overviews`, `ai-search`, `ai-search-optimization`, `agent-credentials`, `answer-engine`, `answer-engine-optimization`, `api`, `asset`, `assets`, `auth`, `background`, `billing`, `brokered-credentials`, `cache`, `canonical`, `capability-token`, `channel`, `component`, `component-api`, `compose`, `config`, `copy`, `credential-broker`, `defensive`, `dependency`, `desktop`, `discovery`, `effort`, `egress-control`, `error`, `errors`, `failure`, `generated`, `generative-ai`, `generative-ai-search`, `geo`, `intake`, `interaction`, `invite`, `llms`, `llms-txt`, `module`, `observability`, `open-graph`, `persistence`, `platform`, `prose`, `react`, `release`, `reusability`, `robots`, `runtime-url`, `security`, `seo`, `sitemap`, `stack`, `state`, `structure`, `structured-data`, `swiftui`, `ui`, `uikit`, `url`, `voice`, `widget`, `wiki`, `worktree`, and `writing`.

Use `classify` before route selection when the request may be vague or when the agent runtime can choose model/reasoning effort. The classifier is intentionally cheap: it suggests `clear-exact`, `clear-scoped`, `vague-action`, `broad-product`, or `risky-unclear`, then recommends quick, standard, deep, or specialist effort. It is a first pass, not a replacement for repo-local inspection.

The router infers the canonical `seo` concern from explicit public-discovery keywords in the request, including SEO, AI search, AEO, GEO, AI Overviews, AI Mode, `llms.txt`, sitemap, robots, canonical, Open Graph, and structured data. Agents should still pass exact concerns when local context shows a specific risk. It also infers `runtime-url` from requests about environment-specific runtime URLs, API/base URLs, API origins, callback URLs, `redirect_uri`, webhook endpoints, CORS origins, asset hosts, and CDN origins.

If the workflow router cannot run, the agent must stop and report the blocker or ask whether to continue with an `index.md` fallback. The route output contains `docs`, `gates`, `gate_ledger`, `repair_cycle_limit`, `repair_policy`, `resume_scope`, `stop_condition`, `notes`, and `missing`. The recovery values are `1`, `retrospective_repair_verify_resume`, `first_failed_checkpoint`, and `same_failure_after_repair_or_unsafe_repair`. Agents should read the listed docs in order, use gates as the task checklist, mark each completed or failed gate with evidence while working, and show a short gate signal after each completed or failed gate or task step. Stop if any document is listed under `missing`. Completion requires every required gate to be `🐱🟢 SUCCESS`. `🐱🔴 FAIL` means blocked, failed, missed, or missing evidence and triggers missed-gate recovery: stop finalization, preserve `first_failed_checkpoint`, run an actionable retrospective, improve and verify the owning Tao Agent OS guidance, hook, validator, or test, apply safe scoped fixes, and resume the original task at that checkpoint. Stop on the same post-repair failure, unsafe or ambiguous repair, uncertain source ownership, or an exhausted single repair cycle. Do not report any third gate state. After a successful work-producing task, the agent must run the retrospective check. When it records a reusable gap for a skill it actually used, the same closeout runs the content-free observation, bounded draft/review/stage sequence, canonical skill-document edit, and verified maintenance receipt. Absence, storage failure, token limits, or reviewer unavailability keep that closeout pending; no observation hook bypasses the maintenance verifier.

## Executable Evidence Gate

For stronger enforcement, agents should use the wrapper scripts that turn the route, VibeGuard checks, git status, validation, and gate ledger into local JSON evidence.

When an agent runtime executes these wrapper commands, resolve `${TAO_HOME}` to the absolute path first. Do not leave `$HOME`, `${HOME}`, `~`, or a relative path in approval-sensitive executable commands.

Before multi-step edits, run one lifecycle entry that performs routing and preflight:

```bash
<TAO_LAUNCHER> start \
  --project . \
  --rules "${TAO_HOME}" \
  --command task \
  --request "<USER_REQUEST>" \
  --concern wiki
```

Read every route `required_docs` entry directly after start and before work. Run the review hook after meaningful edits. Before recording the final `report` gate, record the exact gate slug `retrospective check` (including the space, not `retrospective-check`) with the exact fields `skills_checked`, `outcome`, and `observation` (`no_reusable_gap`/`no_skill_used` pairs with `not_needed`; `reusable_gap` pairs with `recorded`). Record `report` only after the final report is prepared. Then run the read-only finish hook before final report, commit, release, or handoff:

```bash
<TAO_LAUNCHER> gate-batch \
  --project . \
  --rules "${TAO_HOME}" \
  --gate-record '[{"gate":"orient","status":"SUCCESS","evidence":"<instructions and required-doc route>"},{"gate":"scope","status":"SUCCESS","evidence":"<scope decision>"},{"gate":"act","status":"SUCCESS","evidence":"<diff or changed files>"},{"gate":"verify","status":"SUCCESS","evidence":"<commands and results>"},{"gate":"retrospective check","status":"SUCCESS","evidence":"<skills checked and closeout outcome>","fields":{"skills_checked":"<canonical skill ids>","outcome":"no_reusable_gap","observation":"not_needed"}},{"gate":"report","status":"SUCCESS","evidence":"<final report prepared>"}]'

<TAO_LAUNCHER> finish \
  --project . \
  --rules "${TAO_HOME}"
```

`finish` never writes or overrides the gate ledger. Record corrections through `gate` or `gate-batch`; the latest structured status for each gate is authoritative.

Direct `<TAO_LAUNCHER> workflow route`, `<TAO_LAUNCHER> agent-preflight`, and `<TAO_LAUNCHER> agent-finish-check`calls remain available only as lower-level diagnostic or compatibility fallbacks when the corresponding hook cannot run; never run them as a second lifecycle after a successful start or finish hook.

The scripts write to `.tao/preflight.json` and `.tao/finish.json`. That directory is local runtime evidence and should usually be gitignored. Missing wrapper evidence or missing route gate evidence is non-compliant even if the resulting code or docs look correct. Human-visible gate reports use only two cat signal badges so failures are hard to miss: `🐱🟢 SUCCESS` and `🐱🔴 FAIL`. The JSON evidence keeps the plain signal values for automation. When `--request-classified` is used, pass `--classification-evidence`; otherwise request intake is treated as skipped. Evidence alone does not honor the flag: it applies only to a delegated worker whose parent left a ready and valid execution capsule, and the form with neither a request nor a capsule is rejected. Every other caller passes `--request "<USER_REQUEST>"` and lets the classifier run. A caller that only wants the document listing and label context without asserting intake uses `--advisory`, which satisfies no downstream gate. If route classification or stored request text asks for Grill-Me, the finish check must receive Grill-Me protocol evidence such as `grill-me if needed=</grilling session/output evidence>`. Work routes require resolved-scope classification evidence such as `clear-exact`, `clear-scoped`, `answered ... separate actionable`, or `blockers resolved`; weak evidence such as `classified`, `done`, `clarified`, or `no blockers` does not open work routes by itself.

If final VibeGuard is `Needs review`, the agent must report that state and pass `--allow-vibeguard-review "<reason>"` only when the review state is acceptable. A failed VibeGuard command, `🐱🔴 FAIL`, missing route evidence, or missing VibeGuard output remains a blocker.

## Structure

```text
AGENTS.md         Shared entrypoint for agent runtimes
index.md          Routing map for selecting the smallest useful document set
common/           Platform-neutral engineering guidance
platforms/        Android, KMP, Flutter, iOS, web, server, and application tracks
product-patterns/ Reusable product mechanics such as auth, invite, billing, and agent credentials
workflows/        Repeatable agent work paths
scripts/          Executable workflow routers, preflight checks, and validators
templates/        Repo-local routing snippets
docs/             Static public site source
```

## Concrete Implementation Guides

Tao Agent OS cards should not stop at "write clean code." Platform routes now include implementation-detail cards that tell an agent which boundary to create, where state should live, and what evidence proves the work.

- Android Compose: `platforms/android/skills/android-compose-ui/SKILL.md` covers route/screen/component splits, `UiState`, architecture tracks, previews, package layout, and verification.
- Android module/package structure: `platforms/android/skills/android-module-structure/SKILL.md` covers feature modules, API/implementation splits, repository boundaries, build-logic conventions, shared core/design-system ownership, and migration strategy.
- Android ViewModel/state: `platforms/android/skills/android-viewmodel-state/SKILL.md`covers ViewModel contracts, `StateFlow`, one-off events, use cases, repositories, persistence, and coroutine tests.
- KMP/Compose Multiplatform: `platforms/kmp/skills/kmp-architecture/SKILL.md`, `platforms/kmp/skills/kmp-module-structure/SKILL.md`, `platforms/kmp/skills/kmp-compose-ui/SKILL.md`, `platforms/kmp/skills/kmp-state-data/SKILL.md`, and `platforms/kmp/skills/kmp-platform-integration/SKILL.md` cover shared modules, source sets, umbrella frameworks, `expect`/`actual`, shared Compose UI, state/data boundaries, adapters, target capabilities, and verification across affected targets.
- Flutter: `platforms/flutter/skills/flutter-architecture/SKILL.md`, `platforms/flutter/skills/flutter-project-structure/SKILL.md`, `platforms/flutter/skills/flutter-widget-ui/SKILL.md`, `platforms/flutter/skills/flutter-state-data/SKILL.md`, and `platforms/flutter/skills/flutter-platform-integration/SKILL.md` cover feature folders, package boundaries, widget layers, state management, repositories, platform channels, plugins, federated plugin splits, target capabilities, lifecycle, and verification across affected targets.
- iOS module/package structure: `platforms/ios/skills/ios-module-structure/SKILL.md` covers targets, local Swift packages, access control, feature contracts, app extensions, package layout, and migration strategy.
- iOS SwiftUI: `platforms/ios/skills/ios-swiftui-ui/SKILL.md` covers route/coordinator, screen/section/view splits, ViewModel contracts, `UiState`, clean architecture, previews, navigation effects, and tests.
- iOS UIKit: `platforms/ios/skills/ios-uikit-ui/SKILL.md` covers coordinators, view controllers, ViewModels/presenters, typed UI state, lists, forms, navigation, and XCUITest/snapshot boundaries.
- Web React: `platforms/web/skills/web-react-ui/SKILL.md` covers route/page, container/screen splits, hooks, typed `UiState`, query/mutation boundaries, clean architecture, reusable components, and tests.
- Server API: `platforms/server/skills/server-api-implementation/SKILL.md` covers handlers, validators, use cases, repositories, response/error shapes, tenant filters, idempotency, and API tests.
- Desktop/application: `platforms/application/skills/application-command-ui/SKILL.md` covers command routing, windows/panels, shortcuts, menu bar/tray entry points, IPC, background work, and OS resource cleanup.
- Shared reuse: `common/skills/reusable-code-design/SKILL.md` covers when code should stay local, move into feature common, become a design-system primitive, or become a shared package/API.
- Shared structure/state/errors: `common/skills/code-structure-ownership/SKILL.md`, `common/skills/component-api-design/SKILL.md`, `common/skills/state-modeling/SKILL.md`, and `common/skills/error-modeling/SKILL.md` cover module ownership, component contracts, typed state, effects, retries, and user-visible failure states.
- Product implementation: product-pattern implementation cards cover concrete auth/RBAC, invitation, and billing/entitlement models, state machines, enforcement layers, side effects, and tests. Product-pattern ideation cards cover reusable choices such as agent credential brokering before a project commits to one implementation.
- Human-authored writing: `common/skills/human-authored-writing/SKILL.md` covers preserving meaning and voice while reducing generic AI-writing signals in prose, documentation, release notes, marketing copy, and email.

For implementation work, start once with the platform and concern instead of relying on only a broad architecture card. Each line is an alternative task entry, not a sequence:

```bash
<TAO_LAUNCHER> start --command feature --request "<USER_REQUEST>" --platform ios --concern swiftui
<TAO_LAUNCHER> start --command feature --request "<USER_REQUEST>" --platform ios --concern uikit
<TAO_LAUNCHER> start --command feature --request "<USER_REQUEST>" --platform web --concern react --concern ui
<TAO_LAUNCHER> start --command feature --request "<USER_REQUEST>" --platform android --concern compose
<TAO_LAUNCHER> start --command feature --request "<USER_REQUEST>" --platform kmp --concern compose --concern platform
<TAO_LAUNCHER> start --command feature --request "<USER_REQUEST>" --platform flutter --concern widget --concern channel
<TAO_LAUNCHER> start --command feature --request "<USER_REQUEST>" --platform server --concern api --concern auth
<TAO_LAUNCHER> start --command feature --request "<USER_REQUEST>" --platform application --concern desktop
```

## Loading Model

1. Start from the target repo's local instructions.
2. Open this repository's `AGENTS.md`.
3. For multi-step work, run `<TAO_LAUNCHER> start ... --request "<USER_REQUEST>"` once to generate routing and preflight evidence before selecting task documents. Do not repeat lower-level route or preflight.
4. Read every route `required_docs` entry directly before work; use `index.md`only for a simple answer or an explicitly accepted fallback.
5. Read the common baseline cards required for the task.
6. Add exactly the platform, product-pattern, or workflow cards that match the touched surface.
7. Stop loading once the agent can identify ownership boundaries, risk, and verification.

This is the core design: small cards, loaded only when relevant.

## Core Rules

- Repo-local instructions always win.
- `AGENTS.md` is the shared entrypoint for agent runtimes.
- Use `index.md` to choose only the needed documents.
- Answer direct user questions before starting workflow routing, editing, or project-specific commands.
- Run `<TAO_LAUNCHER> start ... --request "<USER_REQUEST>"` once for multi-step workflows, then read every route `required_docs` entry directly.
- Use the review hook after meaningful edits and the finish hook before final report, commit, release, or handoff. Direct `<TAO_LAUNCHER> workflow route`, `<TAO_LAUNCHER> agent-preflight`, and `<TAO_LAUNCHER> agent-finish-check` calls are lower-level diagnostic or compatibility fallbacks only; missing executable evidence is non-compliant.
- Classify unclear requests before loading broad context or using deep model effort.
- Discover the repo stack before choosing package managers, framework APIs, or project commands.
- Diagnose command failures from stdout/stderr before changing code or deciding whether a changed condition justifies another execution.
- Start most coding work from `common/skills/agent-operating-skill/SKILL.md`.
- Use `workflows/skills/agent-task-lifecycle/SKILL.md` for multi-step agent work of any kind.
- Use `workflows/skills/request-triage/SKILL.md` and `common/skills/task-intake-effort-routing/SKILL.md` when deciding whether to ask blocker questions, run the Grill-Me protocol, or lower/raise effort.
- Use `workflows/skills/product-architecture-delivery/SKILL.md` for product work that needs PRD, architecture, implementation, verification, UI tests, and commit gates.
- Use `workflows/skills/development-cycle/SKILL.md` for lower-level multi-step implementation work.
- Use `workflows/skills/ambiguity-gate/SKILL.md` before PRD, ARD, task breakdown, or implementation when unknowns could change behavior, risk, or verification.
- Use `workflows/skills/multi-agent-collaboration/SKILL.md` when delegating or parallelizing agent work.
- Use `workflows/skills/multi-perspective-review/SKILL.md` for non-trivial reviews and release candidates that need multiple risk lenses.
- A typical coding task should load `common/skills/llm-coding-discipline/SKILL.md`, `common/skills/code-conventions/SKILL.md`, one platform architecture card, and only relevant detail or concern cards.
- Naming is surface-specific: app display names can use product capitalization, while repos, slugs, services, and CLIs usually use lowercase `kebab-case`.
- Security, background work, release, permission, and OS integration concerns should load their detail cards explicitly.
- Keep repo paths, commands, components, role matrices, domain terms, and product-specific policy out of this library.
- Keep shared documents short, action-oriented, and reusable.
- Write shared agent guidance in English so multiple agent runtimes and repos can reuse it consistently.
- Public-facing site copy under `docs/` may be localized, but source guidance cards remain English.
- Move repeated platform-neutral rules into `common/`.
- Promote a local lesson only when project names, local paths, commands, service names, and platform-specific API names can be removed without losing the rule.
- Move reusable SaaS or product mechanics into `product-patterns/`.
- Use `workflows/` to compose common and platform cards into repeatable work paths.
- Use `scripts/` for small dependency-free Python routers that turn repeated workflows into command manifests for agents.

## VibeGuard Relationship

Tao Agent OS and VibeGuard stay separate.

- Tao Agent OS owns reusable agent guidance: routing, workflow gates, engineering cards, and platform/product patterns.
- VibeGuard owns the required safety gate and its operational UX.
- Tao Agent OS links to VibeGuard instead of documenting VibeGuard operational details here.
- VibeGuard should use Tao Agent OS as a rule source when applying this Tao Agent OS to a target repo.

VibeGuard documentation:

```text
https://vibeguard.thdev.app/
```

## Language And Localization

Shared agent-facing documents in this repository are written in English. That keeps the guidance easier for different agent runtimes and teams to parse.

Public-facing site copy under `docs/` can be localized. The site currently supports English and Korean copy. Localized marketing or onboarding text should not become the source of truth for agent behavior.

For a Korean quick guide to updating an existing checkout, use `docs/ko/update-tao.md`. The canonical policy remains in this README and the shared agent guidance.

## Metadata

Most documents use frontmatter:

```yaml
keyflow_id: sys_example
status: review
type: ai-generated
```

- Frontmatter `status` values mean `draft`, `review`, `stable`, or `deprecated`. Prefer `review` for active guidance and `stable` only for entrypoints or cards that are ready for broad reuse.
- Frontmatter `type` values describe provenance and review state: `ai-generated`, `human-reviewed-needed`, or `human-reviewed`. Use `status`for operational readiness and `type` for audit or human review queues.
- The `keyflow_id` key is retained for compatibility with older local tooling and document indexes. New documents should continue using it until a separate metadata migration is planned.

## Contributing Guidance

- Keep cards short and action-oriented.
- Prefer links over duplicated guidance.
- Add platform-neutral lessons to `common/`.
- Add LLM-readable wiki, runbook, and durable knowledge-base rules to `common/skills/llm-wiki-documentation/SKILL.md`.
- Add reusable product mechanics to `product-patterns/`.
- Add repeatable task paths to `workflows/`.
- Add or update the workflow route definitions when a repeated workflow should be resolved as a command route.
- Keep repo-specific paths, commands, services, product names, and policies in the target repo, not in this shared library.
- When adding a public-facing page, keep agent source guidance in English and localize only the distribution copy.

## Local Hook Testing

To verify that Tao Agent OS lifecycle commands and search tools function correctly in an E2E sandbox environment:

```bash
python3 scripts/run_smoke_checks.py
```

This runs E2E workflow checks (preflight initialization, constraint verification, gate ledger merges, and workflow search) in a temporary git repository sandbox.
