---
keyflow_id: sys_agent_runtime_hook_install
status: review
type: human-reviewed-needed
---

# Agent Runtime Hook Install

Use this when changing or diagnosing what `setup-agent-hooks` installs for each
runtime: Codex and Claude hooks, native agent roles, the Codex permission
profile, the stable launcher and mailbox entrypoint, status lines, the Spill
label bridge, and the managed instruction-file bridge block. Setup modes and
the command itself are in
`docs/skills/agent-runtime-integration/references/runtime-setup.md`.

## Codex And Claude Installs

For Codex, the same setup also merges one Tao Agent OS-owned `Stop` hook into
`~/.codex/hooks.json` without replacing unrelated hooks such as local metering.
It installs three namespaced native agent files from
`templates/codex-agents/` into `~/.codex/agents/`: `tao_explorer` gathers bounded
read-only evidence, `tao_worker` implements an assigned slice, and
`tao_reviewer` reports correctness and verification risks without editing.
They reuse the rules in
`common/skills/agent-operating-skill/references/runtime-collaboration.md`.
A first-line Tao marker declares ownership. Setup refreshes only managed files,
preserves unrelated roles, and reports a conflict for an unmarked same-name
file, a symlink, or a non-file path instead of overwriting it; customize a
separately named role.
`--dry-run` and `--check` only inspect; check fails on missing, stale, or
conflicting roles, and installation fails on a conflict.

Codex TOML roles require `name`, `description`, and `developer_instructions`
and may set other config keys such as `sandbox_mode`, which Tao's explorer and
reviewer set to `read-only`; see the
[official subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents)
(verified 2026-10-08). Model and reasoning settings inherit.
Setup preserves `[agents]` settings such as a disabled state or concurrency
limit; a two-agent local limit is:

```toml
[agents]
max_concurrent_threads_per_session = 2
```

This limit excludes the main thread. Enabled agent tools never bypass the
eligibility rule or a valid handoff. Restart the client to load new roles.

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
Existing user roots, default selection, `approval_policy`, `sandbox_mode`, and
network settings are preserved. Setup never selects this optional profile.
Without a selected default, setup skips creating optional profiles; existing
profiles without a default are reported as incomplete. Codex 0.154.0 rejects
profiles without `default_permissions`, so TOML syntax checks alone are insufficient.
Older setup selected `default_permissions = "tao-workspace"` automatically;
updating alone does not undo a saved selection, whose provenance is unknown.
Setup reports a notice when that selection remains, without changing it.
With the user's explicit authorization, run
`python3 scripts/setup-agent-hooks.py --reset-codex-permission-default` to
replace that top-level Tao selection with the built-in `:workspace` default,
or repair a missing default when profiles remain. Never delete only the default
while retaining profiles. `--dry-run` previews the change;
`--check` exits nonzero when repair would occur. This migration does not run
other installers, remove the optional profile, or grant network/Full access.
Other selected profiles and explicit user policies remain untouched.
Reconnect the host and verify effective permissions separately: setup readiness
is not proof of network access, and changing a file does not change the active
session's sandbox. A DNS error alone does not identify which policy is active.
The installed Codex bridge also distinguishes tool-session state from execution
evidence. A result that only supplies a running cell or session id does not
prove that an escalated command started. The canonical waiting and recovery
contract is `CODEX_APPROVAL_WAIT_BRIDGE_PHRASE` in
`scripts/support/runtime_bridge.py`. Quiet waits call for read-only process or
target-state diagnosis, not automatic cancellation. Keep one pending equivalent
request and resume it with the matching wait tool. Do not attribute the delay
to hooks or tests without evidence. For an idempotent local command that
normally completes immediately, the phrase allows one bounded wait and then a
confirmed interrupt once it reports no progress and target-state evidence still
shows no side effect. Outside that recovery, cancel only for a user stop, an
explicit failure/timeout, or evidence that the request cannot progress;
unconfirmed execution alone is not that evidence. Before retrying, confirm the
cancelled request is no longer pending and reconcile possible side effects.
Never automatically retry a non-idempotent external write.
`start` binds evidence to Codex's exact `CODEX_THREAD_ID`; the Stop gate acts
only when that same session still owns an active run. It continues the turn
once with the remaining `finish` and same-closeout skill-maintenance work, then
stops an unchanged second attempt explicitly instead of looping or reporting a
false completion. A successful `finish` closes the run and lets Stop proceed, and so does a
settled `cancel`: both write a per-session record that the gate reads, and a
cancellation settles only against a verified clean checkout.
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
Claude setup installs the same roles from `templates/claude-agents/*.md.template`
(not `.md`, so doc validators skip them) into `~/.claude/agents/` under the
Codex ownership rules; frontmatter must open the file, so the marker is a YAML
comment on line two. Roles use `model: inherit`; explorer and reviewer set
`disallowedTools: Edit, Write, NotebookEdit` and keep Bash read-only by
instruction. Load them in a new session; pick one by `subagent_type`.
Claude still applies settings `ask` rules after a PreToolUse hook allows a
call, so a user `ask` rule naming a Git subcommand the gate approves as
ordinary (for example `Bash(git -C * rebase *)`) re-prompts it inside a task
worktree, and no allow rule cancels it. Claude setup, including `--check`,
prints a stderr notice listing such rules in `~/.claude/settings.json`; it never
edits them or fails because of them (`scripts/support/claude_ask_override_notice.py`).

The same stable launcher exposes `agent-mailbox` for all configured runtimes.
Setup adds that entrypoint to the managed narrow permission surface and
refreshes each runtime bridge with two rules: check the current project's local
mailbox once at the start of a normal user-visible task, and use
`agent-mailbox send` for bounded reference context without a development run.
Only explicit execution-evidence sends require `handoff`. Users never choose
room or task ids; linked worktrees share the reference inbox.

Reference state stays under user-local `~/.tao/agent-mailbox/`; explicit
run-bound handoffs retain the project's `.tao/agent-mailbox/` store. Setup
does not install a provider adapter, daemon, LaunchAgent, watcher, polling
process, external API service, or background queue for it. Sending writes a
local packet only. An idle target remains idle and incurs no model use until
the user gives that product its next normal prompt; the runtime then consumes
the addressed local brief once and continues under its own current request and
normal lifecycle.

## Status Line

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

## Spill And Instruction Bridges

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
