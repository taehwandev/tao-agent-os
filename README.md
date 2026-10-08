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

### Automatic Project Memory

The installed `<TAO_LAUNCHER> project-memory` command lets agents capture,
recall, replace, and retire short, source-attributed project guidance. A capture
is recalled by later task starts without an approval step; records expire on
their review date. Memory is reference context, never instructions: the current
request, repository rules, and source evidence prevail.
Capture and correction work without an active development run or task worktree.

Start ranks eligible records by token overlap with `--request`,
`--target-summary`, and verified `--surface-path` values. Exact file paths,
file stems and identifiers such as `retry_queue` or `ProfileScreen` receive
extra weight; a path's two nearest directories count only as plain words and
its other directories not at all, so a repository-wide prefix such as
`app/src/main/java/...` matches nothing. A Hangul word also matches without a
trailing particle (`프로필을` matches `프로필`). Ties retain route-specific, review-date,
then id ordering. The route/`all`, expiry, replacement, three-item and
1,200-character limits still apply. Query context is never saved as memory.
Standalone `project-memory recall` accepts `--request`, `--target-summary`,
and repeatable `--target-path` values for the same ranking.

Capture can include up to four repeatable `--source-path` values naming tracked,
repository-relative evidence files. Tao stores their paths and Git blob hashes
of the current worktree bytes, without filters, contents or history. Recall
marks changed or unavailable evidence with `verify before use`, hashing each
file once per recall and never for a record too long to show; it neither
retires the record nor treats an unchanged file as proof that the guidance is
correct. Existing records without file evidence remain readable and date-based.
Paths outside the repository, untracked files and symlinks are rejected.

The command and start behavior travel with every Tao Agent OS installation.
The records remain in that PC's user-local `~/.tao/project-memory/` store;
linked worktrees of the same repository share them, while another PC starts
with its own empty store. Tao does not sync memory content between PCs.

### Work Cards

Each tracked start opens a local work card holding its `--target-summary` line,
route command, project path, state, and timestamps. A run continued with
`--continue-from` keeps the same card; a successful finish or a transfer to a
completed replacement marks it `done`, and a no-change cancel marks it
`cancelled`. Start lists up to three other open cards
of the same repository as reference context, so unfinished work stays visible in
a new session. `<TAO_LAUNCHER> work-cards list [--all]` shows the board and
`work-cards close <work id>` settles a card by hand.

For Codex, start also records the runtime session automatically. From the
repository, run `<TAO_LAUNCHER> work-cards resume` and choose a numbered task
summary to open its exact conversation, including completed tasks. No session
renaming or UUID entry is needed. The current directory is the default project;
`--project <repo>` selects another repository. Selection uses the displayed
snapshot and never guesses the latest session. Older cards use their own retained
run evidence when available; unbound cards cannot be resumed this way. This
navigates to a conversation without resuming a Tao run or granting work authority.

Cards live in one SQLite file under the PC's user-local `~/.tao/work-cards/`,
shared by linked worktrees of a repository. Cards idle for 90 days are dropped.
They hold no prompt, transcript, or log, and Tao never syncs them. The
content-free delegation queue in `.tao/scheduler.json` is separate.

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
- Spill workflow labels are written only after a successful real route or start preflight. Advisory prompt routing never writes labels; classify/list/query/validate use `--if-absent` and cannot replace an active task. A successful preflight records the selected route mapping (for example bugfix -> debugging/implement, commit -> git_commit/implement, review -> code_review/verify), including in-process routing. Failed routes preserve the prior label. Bounded synchronous helper writes prevent late detached classify writes from winning. Existing hooks and per-turn fallback remain enabled.
- Spill token metering is optional and separate. Tao Agent OS does not install token-usage event hooks. If the local Spill setup helper is present, `<TAO_LAUNCHER> setup-agent-hooks` may wire a safe workflow label bridge; if the helper is absent, it removes only Tao Agent OS-managed Spill label hooks/env and leaves Tao Agent OS routing and evidence wrappers working normally.
- To refresh the obsolete Codex dispatch paragraph in an existing managed project `AGENTS.md`, add `--refresh-project-guidance <PROJECT>` to setup (repeat per project). Preview with `--dry-run`; `--check` verifies it afterward. Only the recognized paragraph inside the managed routing block changes; repo-owned instructions remain intact, and the previous file is kept as `AGENTS.md.tao-backup`. Unknown or unmanaged text is left unchanged with a diagnostic.
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
<TAO_LAUNCHER> workflow validate
```

`triage` and `ambiguity` route without intake evidence. Every work route (`product`, `feature`, `docs-review`, and the rest) refuses a bare `workflow route` with "Work routes require a current, session-bound intent envelope"; to inspect one directly, pass the compatibility `--intent-envelope`, `--approval-record`, and `--runtime-session-id` arguments, or run `start` with the platform and concern flags shown above.

Supported commands are `ambiguity`, `bugfix`, `cleanup`, `docs`, `docs-review`, `feature`, `multi-agent`, `planning`, `prd`, `product`, `refactor`, `release`, `retrospective`, `review`, `task`, and `triage`.

`cleanup` is the route for removing merged branches, stale worktrees, and the local refs a merged pull request left behind. It exists because that work has no product: routed as `task` it collected nineteen gates, a review hook, a boundary plan and a test gate for an operation whose git work takes under a second. It answers the four deletion gates the cleanup guidance already states, reports what it removed and kept, and still needs a recorded approval, because deleting a ref is a git write.

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

Leave `--max-added-lines` at its default for ordinary source changes. Raise it only for one named, indivisible standalone artifact, and name that exact file plus the reason it cannot be split in `--structure-review-evidence`.

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

The scripts write to `.tao/preflight.json` and `.tao/finish.json`. That directory is local runtime evidence and should usually be gitignored. Missing wrapper evidence or missing route gate evidence is non-compliant even if the resulting code or docs look correct. Human-visible gate reports use only two cat signal badges so failures are hard to miss: `🐱🟢 SUCCESS` and `🐱🔴 FAIL`. The JSON evidence keeps the plain signal values for automation. When `--request-classified` is used, pass `--classification-evidence`; otherwise request intake is treated as skipped. Evidence alone does not honor the flag: it applies only to a delegated worker whose parent left a ready and valid execution capsule, and the form with neither a request nor a capsule is rejected. Every other caller passes `--request "<USER_REQUEST>"` and lets the classifier run. A caller that only wants the document listing without asserting intake uses `--advisory`, which satisfies no downstream gate and never writes Spill label context. If route classification or stored request text asks for Grill-Me, the finish check must receive Grill-Me protocol evidence such as `grill-me if needed=</grilling session/output evidence>`. Work routes require resolved-scope classification evidence such as `clear-exact`, `clear-scoped`, `answered ... separate actionable`, or `blockers resolved`; weak evidence such as `classified`, `done`, `clarified`, or `no blockers` does not open work routes by itself.

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

## Tao Maintenance Audit

Use these checks for an explicit Tao audit of duplicate reading, memory reuse,
cache freshness, or repeated workflow work. Keep the criteria and findings in
this section so another agent can continue from the same repository evidence.
This is an on-demand reference, not an extra startup read or workflow gate.
[Project instructions](AGENTS.md) and current source contracts remain authoritative.

Record the source revision, dirty paths, runtime, toolchain, and scope. Inspect
the relevant owner and nearest falsifying check before widening the audit. Use
the required lifecycle before edits; reuse the living task and existing authority.

| ID | Check | What to verify | Owner and nearest tests |
| --- | --- | --- | --- |
| H01 | Document selection | Require command/owner contracts; keep optional links on demand. Count conditional follow-up reading too. | [Router](scripts/workflow_route.py), [selection tests](tests/test_workflow_required_doc_selection.py), [project docs tests](tests/test_agent_project_route_docs.py). |
| H02 | Duplicate reads | Reuse complete unchanged reads before/after start, across worktrees, JSON outputs, split ranges, and compound commands. Count file opens separately from model delivery. | [Delivery](scripts/agent_required_doc_delivery.py), [reuse](scripts/agent_required_doc_reuse.py), [delivery tests](tests/test_agent_required_doc_delivery.py), [reuse tests](tests/test_agent_required_doc_reuse.py). |
| H03 | Context freshness | Reject changed/deleted/reordered rules, failed or incomplete reads, and pre-compaction coverage. Takeaways must cover credited readings. | Delivery and reuse above; their negative cases. |
| H04 | Memory | Prefer the request's scope; exclude expired, retired, replaced, malformed, and foreign-repository records. Skip oversized records without losing shorter useful ones. Memory never grants authority. | [Memory](scripts/agent_project_memory.py), [memory tests](tests/test_agent_project_memory.py). |
| H05 | Cache validity | Invalidate changed source/rules/checker inputs; reuse identical inputs. Check same-status and preserved-metadata changes, staging, Unicode paths, and symlinks. | [Audit cache](scripts/agent_vibeguard_cache.py), [graph cache](scripts/workflow_doc_graph_cache.py), [audit tests](tests/test_agent_vibeguard_cache.py), [graph tests](tests/test_workflow_doc_graph_cache.py). |
| H06 | Lifecycle work | Lookup creates no task state or index refresh. An unchanged action does not repeat start, passed checks, review, or finish. | [Lookup](scripts/agent_lookup_start.py), [lookup tests](tests/test_agent_lookup_start.py), [continuity tests](tests/test_agent_work_continuity_start.py), [E2E smoke](scripts/run_smoke_checks.py). |
| H07 | Authority and isolation | Reuse scope-matched authority; protect exact repository/worktree/session/effect. Denied, foreign, diverged, and post-finish writes remain denied. | [Identity tests](tests/test_agent_worktree_identity.py), [finished integration tests](tests/test_finished_worktree_integration.py), [read-only tests](tests/test_read_only_lifecycle.py). |
| H08 | Verification truth | Reproduce the actual condition, verify it after repair, and retain negative controls. Never report a failed wrapper or partial suite as passing. | [Verification contract](common/skills/verification-policy/references/current-guidance.md), affected owner tests, and smoke's rejection check. |
| H09 | Runtime wiring | Resolved launcher/root and exact worktree targeting are correct; supported Claude/Codex payloads reach the protected boundary. Inspect without reinstalling. | Delivery tests above, [Codex cwd tests](tests/test_codex_exec_workdir.py), [continuation hook tests](tests/test_agent_hook_continuation.py). |
| H10 | Measured efficiency | Separate selected bytes, actual reads/delivery, checker calls, and elapsed time. Compare identical inputs; do not estimate token or latency savings. | Owners above, [status snapshot](scripts/agent_observability.py), [snapshot tests](tests/test_agent_observability.py), controlled probes. |

### Verification And Maintenance

Run from the exact target checkout. The following selected suite was used for
the initial audit; later changes use the affected owner's checks rather than
automatically rerunning everything:

```bash
PYTHONPATH=tests:scripts python3 -m unittest \
  test_workflow_required_doc_selection test_agent_project_route_docs \
  test_agent_start_guidance test_agent_required_doc_delivery \
  test_agent_required_doc_reuse test_agent_project_memory \
  test_agent_vibeguard_cache test_workflow_doc_graph_cache \
  test_agent_lookup_start test_read_only_lifecycle test_agent_observability \
  test_codex_exec_workdir test_finished_worktree_integration \
  test_agent_worktree_identity test_agent_hook_continuation \
  test_agent_work_continuity_start
```

Use the [local E2E command above](#local-hook-testing) for lifecycle integration.
It checks start, weak-evidence rejection, a valid gate batch, finish, and search.
Keep fixture evidence outside the read-only source snapshot, such as in ignored
`.tao/` state. Real source drift must still fail verification.

Keep H01–H10 stable and extend the relevant row before adding a new failure
class. Each finding needs an ID, priority, source owner, reproduction condition,
observed/expected behavior, next proving check, and disposition. Retain before
and after evidence when resolving it. Record each audit's revision and limits;
carry untouched findings forward as historical evidence. Keep raw transcripts,
secrets, local memory bodies, and run-state files untracked.

Stop dependent work on a failed required gate, missing authority, unresolved
owner, or missing required source. Follow the existing repair contract. Passing
selected tests does not establish whole-system health or measured efficiency.

### Audit: 2026-10-02

Source baseline: `d074b64f9934587bd0593a2e153cc186e5be5556`. Environment:
local macOS checkout, Codex, Python `3.9.6`. This agent-generated audit covers
H01–H10 using selected source/test contracts, temporary probes, installed-root
inspection, and E2E smoke. It is a focused audit, not the full repository suite
or a live Claude session.

- The 16-module command above passed **282 tests**, exit `0`, `99.532s`.
- The follow-up documentation/routing suite passed **154 tests**, exit `0`,
  most recently `9.767s`: `test_workflow_required_doc_selection`,
  `test_agent_project_route_docs`, `test_agent_start_guidance`,
  `test_workflow_doc_graph_cache`, `test_agent_lookup_start`, and
  `test_read_only_lifecycle`, with the same `PYTHONPATH` and unittest runner.
- E2E initially exited `1`; after F01's repair, all **5 stages passed**, exit `0`.
- **4 temporary observational probes passed**, exit `0`, `0.195s`. They confirmed
  the costs and edge case below; they are not acceptance tests closing F02/F03.
- Documentation integration initially failed on two example targets treated as
  real links; describing their target names removed those broken links. Final
  validation passed **185 workflow references, 386 Markdown frontmatter/link
  checks, and 28 route contracts**. Two focused document checks passed, including
  **33 relative links** and the shared agent entrypoint.

Selection profiles used `resolve_docs(command, None, [], surface_paths=owners,
project_root=ROOT)`. These measure selection, not task admission. Byte totals
are unique `required_docs` file sizes before history reuse and follow-up reads.

| Command | Owner input | Required docs | Selected bytes |
| --- | --- | ---: | ---: |
| `small-change` | none | 2 | 6,705 |
| `small-change` | `README.md` | 7 | 58,084 |
| `small-change` | `scripts/agent_required_doc_delivery.py` | 8 | 74,507 |
| `commit` | none | 2 | 6,803 |

No comparison measured end-to-end latency, tool-call totals, token usage, or
whether real recalled notes reduced exploration. H09 verified local root/cwd
wiring and tested payload shapes; it did not verify a live Claude session.
Results below retain these limits; tests passing does not close the findings.

### F01: E2E Smoke Changed Its Read-Only Fixture

P1 for the advertised smoke command; **resolved in this change**. Owner:
[test_gate_validation_success](scripts/run_smoke_checks.py). At the baseline,
`python3 scripts/run_smoke_checks.py` writes `smoke-gates.json` into the
temporary source root after a read-only triage start. Finish rejects that
untracked-file drift and the command exits `1`.

The repair places the batch in the fixture's ignored `.tao/` directory. The
same E2E command then passes all five stages with exit `0`, preserving source
drift validation and the weak-evidence rejection control.

### F02: Delivery Reopens Content It Already Has Or Can Skip

The follow-up repairs below use the combined Codex/Claude baseline `180bb39`.

P2 efficiency; **resolved**, H02/H10. Owner: `delivery_text`, `_read_in_context`,
and `_render` in [delivery](scripts/agent_required_doc_delivery.py). Reproduce
with [DeliveryTests](tests/test_agent_required_doc_delivery.py)'s existing
empty transcript and two required documents. Count `Path.read_text` calls for
those document paths while invoking `_deliver()`.

At the audit baseline, each unread document was opened **twice**, for transcript
comparison and rendering. A second delivery opened neither document. Controlling
`required_doc_reuse` to prove both documents reusable still opened each **once**,
while delivering no text. This is local file I/O, not duplicate model context
or a measured latency regression.

The repair excludes proven-reused documents before transcript verification and
shares one content buffer between comparison and rendering. The delivery suite
now passes **30 tests**: one content open per unread document, zero per
proven-reused document, and zero after the marker. Five new regression cases
failed before the repair; freshness, partial-read and compaction controls pass.
These counts cover document content reads, not lifecycle-evidence file reads.

### F03: Restored Metadata Can Hide A Document-Graph Change

P2 correctness edge; **resolved for the reported rewrite**, H05. Owner:
[document_key](scripts/workflow_doc_graph_cache.py). In a temporary
`.tao`-enabled fixture, build a graph from a Markdown link to `alpha.md`, replace
its target with equal-length `omega.md`, and restore the original `st_mtime_ns`
using `os.utime`. Clear only the in-process graph cache, then build again to exercise
the persisted cache.

At the audit baseline, the returned edge still pointed to **alpha.md**. Advancing
the mtime and clearing the in-process cache rebuilt it with **omega.md**. The key measured document
path/size/mtime, symlink identity, and builder content, rather than document
contents. The repair adds `st_ctime_ns`, device and inode to the same stat-based
key. The graph suite now passes **24 tests**, including persisted-cache
in-place rewriting, atomic replacement, unchanged-input hits and zero document
content opens while keying. Four regression assertions failed before the fix.
Metadata-only caching still cannot detect an in-place change that leaves every
key field identical at the filesystem's timestamp precision; this is not a
content-hash guarantee.

For acceptance that must detect this case, compare the cached graph with a
graph rebuilt directly from the document contents. The repeatable diagnostic
below checks that comparison and includes a synthetic frozen-metadata
counterexample: cached `alpha.md` remains stale, while an uncached rebuild and
content hashing detect `omega.md`. Normal metadata still invalidates the entry.
The default metadata cache is retained; a content hash on every lookup would
read the whole corpus again. This diagnostic does not add a production strict
mode or guarantee that every ordinary cached lookup verifies content.

### F04: Small-Change Owner Guidance Still Has A Large Read Surface

P3 optimization investigation; **partially improved; broader investigation open**,
H01/H10. Owners: the
[router](scripts/workflow_route.py), [surface rules](workflow-doc-surfaces.json),
and selected guidance. The measured README and runtime-script profiles above
select **58,084** and **74,507 bytes**. This does not establish irrelevance:
verified owner contracts still apply and some readings may already be retained.

The follow-up inspected `required_doc_reasons`: delivery/reuse inherited CI/CD
guidance from the broad `workflow_router` path rule, although neither owner
defines CI checks, release pipelines or scheduled automation. A specific
`required_doc_context` rule preserves scripted workflow, lifecycle and recovery
guidance without that unrelated card. The same delivery-owner profile now
selects **7 docs / 69,386 bytes**, a reduction of **5,121 selected bytes**.
Mixed delivery/workflow changes still require CI/CD guidance. The surface suite
passes **74 tests**, with both owner-only negative controls failing before the
rule split. README's profile remains **7 docs / 58,084 bytes**; its applicable
documentation/source/writing contracts were retained. These are selection
measurements, not actual model reads or latency savings. Further splitting
requires a source-backed owner and conditional-read accounting.

#### Measured File Reads And Timing: 2026-10-02–03

Reproduce with [the isolated benchmark](tests/benchmarks/document_loading.py):

```sh
python3 tests/benchmarks/document_loading.py --revision 95b02f5
```

The benchmark archives the same `95b02f5` document corpus into temporary
directories and restores only delivery code and surface rules from `180bb39`
in the baseline copy. Both variants therefore read identical guidance content.
It makes no model or network calls and does not reset the live graph cache.
Raw samples and counted paths are written to ignored
`.tao/performance/health-measurements.json`; archive creation, fixture setup and
marker removal are outside the timed actions. Read counters run separately
from timing. The measured environment was macOS 27.0.1 arm64, Python 3.9.6,
with warm OS file caches: 10 warmups and 200 samples per action, plus 20 fresh
processes per variant. Corpus keying first warms the builder-code digest.
The tables report the second run; the repeatable command stores its own latest
samples, so subsequent runs need not reproduce the same timings.

| Action | Content opens before → after | Bytes read before → after | Median before → after |
| --- | ---: | ---: | ---: |
| Deliver seven unread docs | 14 → 7 | 138,792 → 69,396 | 1.768 → 1.598 ms |
| Seven docs with completed-run reuse proof | 7 → 0 | 69,396 → 0 | 1.255 → 0.642 ms |
| Already delivered in this run | 0 → 0 | 0 → 0 | 0.027 → 0.028 ms |
| Complete reads in transcript, without run-history reuse proof | 7 → 7 | 69,396 → 69,396 | 2.005 → 2.038 ms |
| Warm routing plus complete selected-doc reads | 28 → 26 | 258,213 → 248,671 | 2.855 → 3.038 ms |
| Fresh-process routing plus complete selected-doc reads | 187 → 185 | 468,902 → 459,360 | 52.272 → 52.603 ms |

Routing counts include every observed Markdown/surface-map content read inside
the resolver as well as explicitly reading each required document once. They
are larger than the selected-doc count: repeated metadata/entrypoint reads
remain, including four opens each for the scripted-workflow and lifecycle
entrypoints on the warm path. File reads dropped, but F04 showed **no latency
improvement** in this measurement. Fresh-process wall time including Python
startup/imports was 151.781 → 151.046 ms. Selected files were 8 / 74,517 bytes
before and 7 / 69,396 after; the older audit's byte totals used earlier guidance.

A first independent run measured unread delivery at 1.758 → 1.269 ms and
proven reuse at 1.268 → 0.640 ms, while fresh routing/read time was
55.009 → 55.593 ms. Variation between runs matters at this scale; these are
local subsystem observations, not a guaranteed speedup percentage.

| F03 key strategy, same 386-document corpus | Corpus/map opens | Bytes read | Median / p95 |
| --- | ---: | ---: | ---: |
| Existing metadata key | 0 | 0 | 2.898 / 3.083 ms |
| Counterfactual full-content hash on every key calculation | 387 | 2,304,078 | 23.964 / 26.132 ms |

The hash comparison measures key construction, not graph rebuild time. The
isolated persisted graph also matched an uncached source rebuild: 386 nodes,
3,512 edges. F03's remaining metadata limit is explicitly reproduced rather
than claimed fixed. F04's local file-read/timing gap is now measured; model
context actually consumed, conditional guidance reads, tool transport, token
usage and end-to-end session time remain unmeasured. Use source-backed evidence
before removing more guidance or caching repeated resolver reads.

The same follow-up fixes the hash-based fixture in
[runs-prune tests](tests/test_runs_prune.py): `PYTHONHASHSEED=240` reproduced a
directory collision before repair; ordinal phase IDs then passed all **22
tests** with that same seed. No run-retention policy was changed.

### Audit: 2026-10-02, Feature QA

Source baseline: `d074b64`. Environment: Claude Code, Python `3.9.6`, a detached
checkout with temporary HOME/state directories. Ten feature areas (install,
router, lifecycle, continuation, safety gate, doc delivery, collaboration,
memory and cards, VibeGuard and release, runtime adapters) were each checked
against README/AGENTS/reference promises by running CLIs, hooks or focused
tests, with reported outcomes of 112 pass, 4 unverified, and 9 fail. Each failure
was reproduced again by an independent agent; one turned out to be a stale fixture rather than
a product failure. After the repairs below, the full `discover -s tests` suite
ran **3776 tests** (**3775 passed**, 1 skipped).

All resolved in this change except F11, which is docs-only by decision:

- **F05** README's direct `workflow route product|feature|docs-review`
  diagnostics needed an intent envelope. Examples now show only routes that run
  bare, with the requirement stated.
- **F06** The one-public-owner review budget does not count lowercase Python
  functions. AGENTS.md now defines what an owner is.
- **F07** A failed `verify` printed a repair-verify instruction but recorded no
  failed checkpoint (`checkpoint_not_failed`). It now records `tests` with a
  stable signature ([verification hook](scripts/agent_verification_hook.py)).
- **F08** `git --version`, `-v`, `--help` and `git version` were denied in a
  protected checkout as Git writes. They now count as reads; `--exec-path=<dir>` does not
  ([classifier](scripts/claude_bash_git.py)).
- **F09** Deleting a protected branch on the remote (`push --delete main`,
  `:main`) got no hook question. It now asks, in the protected checkout and in
  linked worktrees. Other deletions still defer to Claude's own prompt.
- **F10** In a protected checkout, `rm`/`mv`/`sed -i` defer instead of being
  denied, as designed. The safety-gate docs now say so.
- **F11** On Codex, deferred commands pass silently because Codex has no native
  ask. This behavior is kept by decision, and the docs describe it.
- **F12** `setup-agent-hooks` run under a redirected HOME bootstrapped the
  account's real `gui/<uid>` maintenance agent, pointing it at the sandbox
  checkout. It now skips launchctl unless HOME is the account home
  ([scheduler](scripts/support/maintenance_scheduler.py)).
- **F13** Stale tests: the parser-parity fixture for `command -v git` and the
  quoted-commit-message test that still expected a deny.

Unverified in that run (permission classifier or gate refusals, not failures):
`agent-os-status --validate`, the maintenance/watchdog CLIs, the
mailbox/handoff/dispatch suites, and pre-commit audit reuse.

### Audit: 2026-10-07, Figma And PR Follow-Through

Source baseline: `129d256567d1fabacbaa72a0036e3346d7ce095b`. Environment:
Codex on macOS, isolated Tao task checkout. Scope: the Figma command boundary
and the agent's follow-through on one resource-copy change and its requested PR.
This does not migrate or reinstall the active runtime, alter the product
repository's policy, or establish full visual parity.

| ID | Priority / check | Evidence and expected behavior | Owner / proving check / disposition |
| --- | --- | --- | --- |
| F14 | High / H07, H09 | The canonical Figma interpreter operand and URL query were treated as local write paths. Even dry-run required another repository's writable lifecycle. A bytecode-free dry-run should be a read; extraction should protect its output, not require authoring the tool checkout. | [Figma classifier](scripts/claude_bash_figma.py), [regressions](tests/test_claude_bash_figma.py). Two new tests failed before the repair; canonical CLI operand roles now resolve the false targets. Unknown tools/options and protected output writes remain conservative. |
| F15 | Medium / H06 | PR lookup was invoked with `--check` after other options, but the project's explicit non-publication prefix places it immediately after the script. This was an agent invocation error, not a missing publication exemption. | [Prefix contract](scripts/claude_worktree_gate.py), [longest-prefix tests](tests/test_claude_worktree_gate.py). Use the repository's declared lookup form; do not reorder arbitrary script arguments or infer safety from the spelling of a flag. Existing tests passed. |
| F16 | Medium / H02, H10 | The agent asked for design text despite having the Figma link, stopped before supported recovery, reread unchanged guidance, and exported 142 assets for one copy change. These were avoidable execution decisions; no comparable latency benchmark was collected. | Existing operating-skill persistence/reuse rules already cover the first three. Figma guidance needs a bytecode-free invocation and bounded extraction for copy-only work. No end-to-end speedup is claimed. |
| F17 | Medium / H07, H08 | A required product pre-push structure check found inherited upstream debt. Publication authority did not authorize changing its frozen baseline; a separate baseline approval remained necessary. | Product-owned audit and approval rule remain authoritative and unchanged by this Tao repair. Anticipate required publication checks when preparing the concrete PR unit; a failed check must not be bypassed. |
| F18 | Medium / H06, H07 | Staged canonical maintenance rejected a Tao task worktree target as `maintenance_target_mismatch` when `--rules` still named the main checkout. The task worktree is a canonical source owner in the same repository, not a foreign product-local skill. | [Maintenance owner](scripts/agent_skill_maintenance.py), [identity controls](tests/test_agent_skill_maintenance.py). Canonical bundles now require matching Git common directories, exact checkout roots, a linked `.git` file, bundle provenance and containment. Foreign repositories, subdirectories, missing bundles and symlink escapes remain refused. The live maintenance step completed using the actual canonical task worktree as its rules owner. |

The copy implementation and product PR were ultimately completed. The delays
came from both a missing Figma command contract and agent decision errors.
The auxiliary no-source-change extraction run was unnecessary; removing the
false tool-repository target avoids it without weakening the empty-code-review
guard. Keep required approvals, isolation, lifecycle gates, and publication
checks intact.

Verification: **173 tests passed**, exit `0`, with `python3 -B -m unittest`
over `tests.test_claude_bash_figma`, `tests.test_claude_bash_readonly`,
`tests.test_claude_worktree_gate`, `tests.test_claude_pretool_target_protection`,
`tests.test_claude_shell_parser_parity`, `tests.test_figma_cli`,
`tests.test_figma_validate`, `tests.test_agent_skill_maintenance`,
`tests.test_agent_skill_learning`, and `tests.test_agent_skill_hooks`. These cover
the actual CLI dry-run's lack of output, argument-grammar drift, source-operand
exemption, canonical maintenance identity, and negative protection cases.
Canonical Figma guidance was staged and its maintenance verifier passed the
focused unittest selector before marking the change applied. These are not the full Tao suite or
a new live Figma API/network test.
