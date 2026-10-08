---
keyflow_id: sys_agent_runtime_write_isolation
status: review
type: human-reviewed-needed
---

# Agent Runtime Write Isolation

Use this when changing or diagnosing how installed runtime hooks enforce
workflow entry and worktree policy: the PreToolUse gates, exact-session run
evidence, write isolation for protected checkouts, Git and Bash permission
boundaries, and shell mutation bracketing. The setup that installs these hooks
is in `docs/skills/agent-runtime-integration/references/runtime-setup.md`.

## Enforcement Hooks

Runtime bridges are advisory: prose alone does not stop a file edit when the
agent skipped `start`. To make workflow entry and worktree policy enforceable,
`setup-agent-hooks.py` installs the same low-cost PreToolUse policy engine for
Claude and Codex. The engine classifies the pending tool call and reads existing
run evidence; it does not route, search documents, run VibeGuard, or review.
Claude additionally installs continuation hooks:

- a `SessionStart` continuation hook for `startup|resume|fork`;
- the Claude `PreToolUse` workflow/checkpoint gate for
  `Edit|Write|MultiEdit|NotebookEdit`;
- matching `PostToolUse` and `PostToolUseFailure` continuation hooks; and
- the existing `Stop` finish gate.

Codex installs `codex-pretool-gate` for
`Edit|Write|MultiEdit|ApplyPatch|apply_patch|Bash` and keeps `codex-stop-gate` for closeout.
The thin Codex adapter reuses the policy engine while resolving evidence against
the Codex runtime session, so the two runtimes enforce the same repository
declarations without running duplicate project-local worktree guards.
Native Codex `apply_patch` and legacy `ApplyPatch` share the edit-policy path.
Patch bodies supplied directly or under `patch`, `input`, or `command` are
resolved against the event's cwd. Every named file and move destination enters
the existing worktree, read-only-run, and session-bound workflow-entry checks;
an unrelated `file_path` cannot replace the patch's targets. A valid active run
in a compliant worktree requires no additional operator decision.

## Run Evidence Binding

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

## Worktree Write Isolation

For a repository that requires linked worktrees, isolation governs writes, not
visibility. The protected checkout remains readable through Claude's `Read`
tool and through Bash commands the classifier proves read-only. An Edit or
Write target in that checkout is denied, and so are Git commands that author
there (commit, checkout, reset and the like) and a single `touch` naming a file
there. Other mutating Bash commands with a readable target (`rm`, `mv`,
`sed -i`, build or test scripts) are not refused by the hook, because a build
or test may only read: on Claude they defer to Claude's own permission prompt,
where standing allow rules still apply; on Codex, which has no native ask, the
hook stays silent and Codex's sandbox and approval policy decide. The generated project
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
never covered by that approval. Operations that discard uncommitted work,
force remote refs, change executable/config paths, or use
output/execution-capable Git options emit `ask`. Deletions -- `branch -D`,
`tag -d`, `clean`, `worktree remove`, `stash drop`, pruning, and deleting an
unprotected remote branch -- emit no hook `ask`: a hook `ask` offers only
yes/no every time, so they defer to Claude's own permission flow, where "always
allow" persists. The one deletion still asked about is removing a protected
branch (`protected_branches`, e.g. `main`, `develop`) from the remote with
`push --delete` or a `:<branch>` refspec, which no local checkout can restore.
On Codex every `ask` becomes a silent pass to Codex's own approval policy. This
keeps the common development path prompt-free while preserving a meaningful
operator decision for the rare dangerous path.

The Bash allowance is command- and option-aware. A compound line is read-only
only when every command it executes is read-only; loop and branch keywords are
syntax, but their conditions and bodies are still classified. `find`, `sort`,
and `sed` may traverse, order, print, or substitute inspection output, while
delete/exec actions, named output or temporary-file locations, external
compression programs, in-place edits, and scripts that write or execute are
never classified as reads. Any shell or option shape the classifier cannot
prove safe leaves the read-only fast path and is judged by the rules above.

## Same-Session Claims And Resume

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

## Shell Mutation Bracketing

Claude's file tools expose one exact `file_path`, so they can be bracketed
automatically. Arbitrary `Bash` commands do not expose a trustworthy changed
path set. Agents must bracket a shell command, formatter, or generator that may
write with the provider-neutral `checkpoint --checkpoint-kind pre_mutation`
and `post_mutation` commands and the complete bounded path set. Do not parse
command prose to guess ownership or describe Bash as automatically covered.
When executing Tao Agent OS wrapper commands from an agent runtime, replace
`<TAO_ROOT>` with the resolved absolute path. Do not leave `$HOME`,
`${HOME}`, `~`, or a relative path in the executable command.
