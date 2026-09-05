---
keyflow_id: sys_agent_runtime_setup
status: review
type: human-reviewed-needed
---

# Agent Runtime Setup

Use this when installing or wiring Tao Agent OS into a runtime or a repository:
which entries an installer may own, which setup mode a request needs, and how a
runtime finds the project it is meant to work in.

The execution contract a runtime follows once it is wired -- the capsule, the
required flow, the model tiers -- is
`docs/skills/agent-runtime-integration/references/current-guidance.md`.

## Installer Ownership Boundary

A runtime reads one settings file, so every installer writes into a space it
shares with tools it knows nothing about. Setup, update, repair, and uninstall
may touch only entries whose provenance is readable, and provenance must be
something the installer produced, not something it recognises.

| Signal | Verdict |
| --- | --- |
| a unique alias inside the command the installer generated | ownership |
| a marker block the installer emitted around its lines | ownership |
| a matching timeout, event, or install directory | resemblance |
| an environment value another product also sets | resemblance |
| the absence of another product's file | not proof that product is gone |

Resemblance is where this goes wrong, because two products configuring the same
runtime naturally look alike. Two hooks on the same event with the same timeout
prove nothing about who wrote either. An environment entry is the hardest case:
its value is the same string whoever set it, so an installer that removes it on
value equality will eventually delete a live setting belonging to something
else. Record what was actually written, keep that record in the installer's own
state directory, and remove only what the record names. A stale entry left
behind is a cheaper failure than a working one deleted.

Removal granularity matters as much as the predicate. Configuration formats
group entries, and dropping a group to remove one owned entry takes its
neighbours with it. Filter within the group and keep the rest.

Never write into another product's install tree, and never make setup depend on
another product being installed. When a companion tool is absent, degrade to
doing less rather than to cleaning up on its behalf.

Synchronous lifecycle hooks must be bounded, whoever owns them: a runtime kills
what overruns, and the failure surfaces as that lifecycle event failing rather
than as the slow hook being named. When diagnosing a hook timeout, identify the
owning command first — the reported failure is the event, not the culprit — and
leave the fix with the product that owns it. Implementation details of another
product's hook belong in that product's documentation, not here.

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

Without a `--runtime` selector, that one command configures every detected
Claude, Codex, and AGY installation. Each managed merge is idempotent, so the
same command is also the convenient repair path after updating Tao Agent OS;
merging or pulling the repository alone never rewrites user-level runtime
settings.

On macOS, the same setup also installs and loads one Tao-owned LaunchAgent for
the selected Tao root. It runs the bounded `agent-os-maintenance.py` pass at
login and every 24 hours, so completed run evidence is pruned by the existing
retention policy without a daemon or per-agent polling loop. Active runs and
unclassified directories remain fail-closed and are not deleted. `--check`
reports the scheduler missing when either its plist or loaded service is absent.

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
For Codex, the same setup also merges one Tao Agent OS-owned `Stop` hook into
`~/.codex/hooks.json` without replacing unrelated hooks such as local metering.
It adds Codex's native `five-hour-limit` and `weekly-limit` items to
`tui.status_line`, preserving the existing item order and every unrelated
setting. When no status line was configured, it keeps Codex's default model and
current-directory items before the two limits. Codex itself supplies and draws
the remaining percentages, so this does not install a poller, call another API,
or depend on Agent Cat. The bottom line currently formats those built-ins as
compact text such as `5h 60% left · weekly 6% left`; the larger `/status` panel
is the Codex surface that draws block gauges. Codex exposes no custom renderer
slot for making the bottom line mirror that panel. Start a new Codex session
after setup to see the line.
The setup also maintains a Tao-owned `tao-workspace` permission profile in
`~/.codex/config.toml`. The profile extends Codex's built-in `:workspace`
profile and adds only exact generated worktree roots. A scoped target repair,
for example `setup-agent-hooks --runtime codex --target <TARGET_REPO>`, adds
`<TARGET_REPO>/.tao/worktrees` and does not write `.claude/settings.json`.
Existing user roots and unrelated settings are preserved. A foreign default
profile or legacy `approval_policy`/`sandbox_mode` is an ownership conflict and
must be reported rather than replaced.
The installed Codex bridge also distinguishes tool-session state from execution
evidence. A result that only supplies a running cell or session id does not
prove that an escalated command started. For an operation expected to finish
promptly, the agent waits once for at most 15 seconds and then uses a read-only
process or target-state check. It must not attribute the delay to hooks or tests
without that evidence. If execution remains unproven, it terminates the cell
before a retry; it retries only after proving no side effect occurred and never
automatically retries a non-idempotent external write.
`start` binds evidence to Codex's exact `CODEX_THREAD_ID`; the Stop gate acts
only when that same session still owns an active run. It continues the turn
once with the remaining `finish` and same-closeout skill-maintenance work, then
stops an unchanged second attempt explicitly instead of looping or reporting a
false completion. A successful `finish` closes the run and lets Stop proceed.
If the Codex launcher process is replaced while `CODEX_THREAD_ID` survives, a
lifecycle hook may reclaim only that exact session's run and only after the
recorded process owner's death is proven. The atomic takeover increments the
resume generation; a live owner, different session, settled run, or public
packet-less `resume --last` request remains refused.
For Claude, `setup-agent-hooks.py` installs a stable user-level launcher at
`<TAO_LAUNCHER>` and writes the current checkout to
`~/.tao/tao-root`. Rerun setup after moving or migrating
Tao Agent OS so the pointer is refreshed without changing the Claude hook
command.

The same stable launcher exposes `agent-mailbox` for all configured runtimes.
Setup adds that entrypoint to the managed narrow permission surface and
refreshes each runtime bridge with two rules: check the current project's local
mailbox once at the start of a normal user-visible task, and use `handoff` plus
`agent-mailbox send` when another runtime needs the bounded context. The
sender's exact active Tao run is the internal source key, so users never choose
room or task ids.

Mailbox state stays below the selected project's `.tao/agent-mailbox/`. Setup
does not install a provider adapter, daemon, LaunchAgent, watcher, polling
process, external API service, or background queue for it. Sending writes a
local packet only. An idle target remains idle and incurs no model use until
the user gives that product its next normal prompt; the runtime then consumes
the addressed local brief once and continues under its own current request and
normal lifecycle.

Claude's runtime bridge is otherwise advisory: unlike the Codex prefix rule,
prose alone does not stop a file edit when the agent skipped `start`. To make
workflow entry and continuation enforceable, `setup-agent-hooks.py` installs:

- a `SessionStart` continuation hook for `startup|resume|fork`;
- the Claude `PreToolUse` workflow/checkpoint gate for
  `Edit|Write|MultiEdit|NotebookEdit`;
- matching `PostToolUse` and `PostToolUseFailure` continuation hooks; and
- the existing `Stop` finish gate.

Setup also installs a managed `statusLine` entry, so where this session lives,
the runtime's own remaining quota, and the run currently open stay on screen
without a wrapper launcher. The runtime hands the status-line command the
session as JSON, and that JSON already carries `rate_limits`, so the renderer
subtracts what each window has used and draws what is left, as a block gauge
beside the number; the open run is read from the project's run registry and its
bound gate ledger. Neither number is asked for over the network and nothing is
written.

```
5h █████▎░░  65%  │  7d ███████▌  94%  │  ~/git/tao-agent-os/…/gauge  │  task 14/20
```

Both runtimes render this from `scripts/support/statusline.py`, which composes
the line, and `scripts/support/tao_run_state.py`, which reads whether a run is
open; each runtime keeps only an entry point saying how it is invoked. They were copies once, and the copy is
how a defect travelled -- a status word outside the installer's vocabulary was
written in one and inherited by the other -- so a segment added twice is a
mistake the shape now prevents.

The path names the directory the session **started** in, not the one it is
currently in. The runtime reports both (`workspace.project_dir` and
`workspace.current_dir`), and the difference is what makes the segment worth
reading: a label that moved under you answers a question nobody asked, while a
fixed one lets you recognise at a glance which checkout this window belongs to.
The open run is still found from the current directory, because that is where
the run lives. Home folds to `~`, and past `PATH_LIMIT` the middle segments give
way to `…` -- every task worktree sits under the same `.tao/worktrees`, so that
is the part carrying no information. The leaf is never truncated; a half-written
worktree name is worse than a long one.

The gauge fills to what remains, so it empties as the budget does. It is drawn
at eighth-block resolution because whole blocks round both 3% and 12% to no
cells at all, and an exhausted window and one with a sliver left are the two
states most worth telling apart -- eight cells of eight give 64 steps, so 1%
still draws. Its width is fixed and the percentage is padded, because the line
is redrawn constantly and a segment that changes width moves everything after
it.

Colour marks the quota by how much is left -- cyan, then yellow below
`CAUTION_REMAINING_PERCENT`, then bold red below `LOW_REMAINING_PERCENT` -- and
dims the path and the run so the number that says when to stop is the one seen
first. Three rules keep it honest. It is written as the terminal's own palette
indices rather than exact values, so a theme adjusted for colour vision applies
its adjustment instead of being overridden. The ramp avoids green, because green
and red are the pair most often collapsed, and its three entries differ in
brightness as well as hue. And colour is never the only signal: the gauge length
carries the same reading and a window running out keeps its `!`, so `NO_COLOR=1`
loses emphasis and nothing else.

That slot holds one command and other tools install into it, so the managed
entry never replaces what it finds: it puts Tao in front and passes the untouched
payload on through `--chain`, keeping that output beside its own. A managed entry
is recognised by the `TAO_STATUSLINE=1` prefix rather than by the script name,
because a chained third-party script may itself be named for the status line.
Reinstalling rewrites the launcher path and preserves the existing chain instead
of nesting a second copy.

AGY executes a managed `statusLine` command configured in
`~/.gemini/antigravity-cli/settings.json`. When rate limits or quota information
are provided on stdin as JSON, the renderer draws what is left using
runtime_quota; when rate limits are absent, it silently renders the active Tao
run progress (`task X/Y`). It reads the window shapes both Claude and Codex
emit, so a later Codex surface needs no third renderer.

Codex also has a status line -- `/statusline` configures it and `status_line`
stores it -- but it selects from a fixed list of built-in items instead of
running a command. That list includes `five-hour-limit` and `weekly-limit`, so
setup safely adds those two items to `tui.status_line` and emits a
`codex / statusLine` row with the actual merge result. Existing picker choices
and their order are preserved. The quota data and rendering remain Codex-owned;
Tao does not install a second renderer or read a session transcript for this
runtime.

A row's status word is the report's vocabulary, not prose: `print_results` marks
anything it does not recognise as MISSING, so a merger that has nothing to do
must return `ok` (optionally followed by its reason in parentheses), a dry run
that would act must return `would_update`, and a completed write must return
`installed`.

The start hook allocates `.tao/runs/<opaque-run-id>/preflight.json` whenever no
explicit evidence path was supplied, including runtimes without a session id.
When Claude supplies a runtime session id, every later hook uses the common
exact-session resolver and requires runtime name, session id, registry evidence
key, and resume generation to identify that path. An isolated worker additionally binds
the resolver to the exact launcher-issued `TAO_WORKER_EVIDENCE` path and never
falls back to parent evidence; without that worker binding, the resolver
traverses worker evidence only to account for its active registry keys,
excludes those files from parent matching, and then requires one exact
parent-session match.
Multiple parent-session matches fail closed, while a malformed, foreign, or
unregistered worker binding fails without parent fallback. Candidate discovery
uses one registry snapshot and one bounded state-tree traversal with explicit
parent/worker scope classification rather than one recursive scan per active
run; `.tao/preflight.json`, freshness
alone, and newest-file selection never unlock editing. `PreToolUse` fails closed
when the required pre-mutation checkpoint cannot be written. The post hooks
clear the pending mutation after success or failure and block the next agentic
step when reconciliation is required. Non-edit tools and directories outside
Tao Agent OS remain outside this gate. Tune the freshness window with
`TAO_CLAUDE_GATE_MAX_AGE_SECONDS` (default 8 hours). Policy violations return a
deterministic denial instead of an operator confirmation, so Claude repairs the
workflow or worktree boundary without asking for every Edit, Write, or Bash call.

For a repository that requires linked worktrees, isolation governs writes, not
visibility. The protected checkout remains readable through Claude's `Read`
tool and through Bash commands the classifier proves read-only. An Edit, Write,
or mutating Bash target in that checkout is denied. The generated project
permissions anchor `Read`, `Edit`, and `Write` at `/.tao/worktrees/**`, so a
compliant linked worktree remains readable and writable even while the runtime
is already inside its generated directory. A session launched from the
protected checkout may operate on that worktree through a recognised
`cd <worktree> && ...` prefix or Git's global `-C <worktree>` option; the launch
directory is context, not a second write target. Any explicit path back into
the protected checkout is still denied.

Codex uses the equivalent filesystem boundary through the `tao-workspace`
profile's exact `<TARGET_REPO>/.tao/worktrees` root. Because that profile
extends `:workspace`, adding the generated root does not make the protected
checkout or Codex's own configuration writable.

Do not generate Claude `Bash(git ...)` allow-prefix rules. Claude handles its
built-in read-only Git forms without a prompt, while wildcard Bash rules can
absorb a later writing or executable option: for example, a listing prefix can
also match bundled `branch -vD`, and `git log *` can match `--output`. For a
simple Git invocation inside a compliant linked worktree, the PreToolUse gate
instead emits an explicit `allow` for ordinary work such as add, commit,
checkout, merge, rebase, fetch, and non-forced push. A compound shell line is
never covered by that approval. Operations that discard work, overwrite shared
state, force or delete remote refs, change executable/config paths, prune
recovery data, or use output/execution-capable Git options emit `ask`. This
keeps the common development path prompt-free while preserving a meaningful
operator decision for the rare dangerous path.

The Bash allowance is command- and option-aware. A compound line is read-only
only when every command it executes is read-only; loop and branch keywords are
syntax, but their conditions and bodies are still classified. `find`, `sort`,
and `sed` may traverse, order, print, or substitute inspection output, while
delete/exec actions, named output or temporary-file locations, external
compression programs, in-place edits, and scripts that write or execute remain
denied. Any shell or option shape the classifier cannot prove safe fails closed.

After a new parent `start` has atomically promoted its claim to `running`, it
may self-heal same-session ambiguity by cancelling older active parent claims
for that exact runtime session. The registry performs that cancellation as a
compare-and-set on evidence key, run id, run-instance start time, active state,
and resume generation. If an older run finishes, fails, is rebound, or its
terminal id is adopted by a new start before the transaction acquires the
registry lock, its newer state wins and the start must not report it as settled.
Claims from another runtime session and isolated worker claims are never
superseded by this path.

On a `ready` SessionStart resume, Claude receives the bounded objective,
decisions, remaining work, reusable inspected scope, and successful
verification ids. The injected brief explicitly distinguishes trusted reuse
from invalidation conditions. It never includes command text or output and is
not emitted for drift, ownership, integrity, or local-boundary refusals.

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
