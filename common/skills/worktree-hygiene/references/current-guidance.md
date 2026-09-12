---
keyflow_id: sys_worktree_hygiene
status: stable
type: human-reviewed-needed
---

# Worktree Hygiene

Use when working in an existing checkout, especially when the agent did not
start from a clean tree.

## Default

User-owned changes are part of the environment. Preserve them unless the user
explicitly asks to remove or replace them.

Worktree isolation is a code-development boundary, not a general filesystem
permission rule. Apply it to changes against an existing published repository
baseline when the target project requires isolation. Initial project setup,
folder/repository administration, and read-only lookup do not require a task
worktree merely because they operate in a Git directory. Reading context outside
a worktree does not authorize writing there; runtime filesystem permissions and
user authorization remain separate from isolation. Load the isolation procedure
when that workflow applies, not as an entry gate for every task.

## Before Editing

- Check the current diff or status when edits, commits, reviews, or releases are
  in scope.
- Identify files already changed before the task.
- Read a file before editing it, especially if it is already modified.
- Keep formatting, generated output, dependency changes, and cleanup separate
  from the requested behavior unless they are required.

Use concrete evidence instead of memory:

```text
git status --short --untracked-files=all
git diff --name-only
git diff -- <path>
```

For long tasks, record the initial changed-file list in your notes. When the
repo is already dirty, treat that list as user-owned until you have inspected
the file and can identify the lines you changed.

## During Work

- Do not revert, restage, reformat, or overwrite unrelated user changes.
- If user changes touch the same file, edit around them and preserve intent.
- If user changes make the requested work ambiguous or unsafe, stop and state the
  conflict instead of guessing.
- Keep commits, patches, and summaries limited to changes made for the task.
- Treat generated files and lockfiles as user-visible diff noise unless the task
  or toolchain requires them.

## Rollback Missed Gate Scope

Use when a workflow gate was missed and the agent must retry that gate.

- Roll back only changes made by the agent that depend on the missed gate or
  must be undone before retrying that gate.
- Preserve pre-existing user changes, even in files the agent also touched.
- Prefer a targeted reverse patch or explicit file edit over broad repository
  reset commands.
- Do not roll back completed earlier gates or unrelated valid work.
- Do not use destructive history or filesystem cleanup without a direct user
  request.
- If safe rollback cannot be separated from user-owned changes, stop and report
  the blocker instead of guessing.

## Isolated Worker Worktrees

Use when a dispatched worker runs in its own git worktree because it shares an
overlapping `owned_scope` with another concurrent writer.

- Create the worktree with `git worktree add` from the base ref before the
  worker starts. Setup is fail-closed: if the worktree cannot be created, raise
  and stop. Never silently fall back to the main checkout.
- Treat Git-repository membership and agent-runtime project trust as separate
  checks. Before a runtime receives trust for a generated worktree, verify that
  the path is the canonical direct child reserved by the dispatcher, is the Git
  top level, uses a linked-worktree `.git` file, and shares the parent
  repository's Git common directory. A nested or standalone repository at the
  expected-looking path must fail closed.
- When Codex needs explicit trust for the generated worktree, pass an ephemeral
  per-process `projects` trust override for the exact verified `--cd` path.
  Never mutate global Codex trust state as a dispatch side effect, and never use
  `--skip-git-repo-check` as a trust substitute; that flag addresses repository
  eligibility, not project-local `.codex` policy loading.
- An isolated worker writes only inside its own worktree directory. Never write
  the main checkout directly from an isolated worker.
- Base-ref constraint: worktrees branch from `HEAD`, so uncommitted parent
  changes are not visible in the worker worktree. If the overlapping scope has
  uncommitted parent changes, the lead checkpoint-commits first or serializes
  that slice instead of isolating it.
- Cleanup is the lead's responsibility, not the worker's. After the lead reviews
  and integrates a worker's result into the lead checkout, run
  `<TAO_ROOT>/scripts/workflow.py dispatch-finalize --project <PROJECT>
  --worktree <WORKTREE>`. The finalizer must independently compare every
  tracked and untracked worker change with the lead checkout before it may
  force-remove the intentionally dirty tree, prune Git admin state, and remove
  an empty `.tao/worktrees` root. A mismatch fails closed and preserves the
  worker result. Ignored files are preserved unless the lead explicitly passes
  `--discard-ignored`; do not infer that policy from a successful worker exit.
  Do not auto-remove a worktree on worker exit.
- Verification must exercise both boundaries: inspect the model-visible prompt
  or equivalent deterministic runtime input to prove project-local policy was
  loaded, then run a real worker without the repository-check bypass and confirm
  its writes stay in the worktree while the shared checkout remains unchanged.
  After lead integration and finalization, also prove `git worktree list
  --porcelain` and the `.tao/worktrees` filesystem state return to their
  pre-dispatch baseline while the integrated result remains in the lead checkout.

## Repo-Declared Root-Session Isolation

The following is an explicitly declared stricter repository policy, not the
shared default above. Do not infer it from Git membership or install it merely
to perform initial setup or repository administration. A repository opting into
root-session isolation may track `.agents/shared/worktree-policy.json` with this
closed contract:

```json
{
  "schema_version": 1,
  "require_linked_worktree": true,
  "protected_branches": ["develop", "main"],
  "require_workflow_entry": true
}
```

`require_workflow_entry` is the one optional key; the waiver described below is
what it turns off, and it defaults to absent so an existing declaration keeps
its current behaviour. Every other key is required, and the contract stays
closed in both directions: an unrecognised key is a malformed declaration that
falls back to the default policy rather than an extra that is ignored.

This file is also an opt-in signal by itself, and it is the only one a linked
worktree carries. The state directory is written by a run, so a freshly created
worktree of a governed repository has none until it has already complied, and
the marker-file token depends on the runtime's product name appearing in the
entry document's prose, which an ordinary documentation edit can remove. A
repository that tracks this file has declared governance in a file every one of
its worktrees checks out.

Runtime adapters must treat this declaration as an executable boundary, not as
advisory prose. Discrete file edits and Bash commands that are not provably
read-only or limited to worktree bootstrap must fail closed in the main checkout
and on a listed protected branch. A read-only status check, `git fetch`, and
`git worktree add` remain available so the agent can reach the compliant
checkout, but workflow `start` is denied there: opening a run before relocation
leaves a second unfinished lifecycle behind. Do not auto-create a worktree from
the pretool hook: branch, base, ticket, path, and ignored local-file copy
decisions belong to the repository workflow. After selecting the linked
worktree, run `start` with that path as the project root before any mutating tool.

### The Preflight Waiver Inside A Compliant Worktree

Isolation and workflow entry are two separate protections, and by default
satisfying the first waives the second. Once the session is in a compliant
linked worktree of a repository that declares this policy, the gate stops
requiring run evidence for mutations there. Requiring both made the policy
unusable: a compliant worktree still could not be written to until preflight
evidence existed, so the cheapest way to get work done was to turn the gate off
and lose the isolation with it. The waiver is earned by the declared policy and
never by its absence -- a repository that declares nothing has proved nothing
and still needs the run.

The consequence has to be read plainly, because it is not what the surrounding
denials suggest. In a repository that declares only `require_linked_worktree`,
an agent can be sent into a worktree by this gate and then complete a whole
task there -- edits, commits, and a pull request -- without `start`, `gate`, or
`finish` ever being required. Feeling this gate is not evidence that the
lifecycle is being enforced. A repository that wants both declares
`"require_workflow_entry": true`, which drops the waiver and puts mutations in a
compliant worktree back behind workflow entry; `start` itself stays reachable
there, and the shared-repository prompt is unaffected either way.

The run that `finish` settled still publishes its own result. `finish` runs
before the commit and closes the run, so requiring an active binding for that
commit would refuse the last step of the order this contract asks for, and the
only way through would be to open a second run for work the first already
attested. A successful `finish` therefore keeps `add`, `commit`, `push` and
`tag` available to that session while its evidence is fresh. It does not reopen
editing: `finish` attested one diff, so moving the worktree afterwards needs a
new run, and rewriting or discarding commands are not part of publishing.

Two environment variables bridge and override this declaration, and both must
stay rare and explicit. During a transition window where the tracked
`worktree-policy.json` has not yet reached the current checkout,
`TAO_REQUIRE_LINKED_WORKTREE=1` in project-local runtime configuration applies
the same boundary to that one Git repository; its meaning must stay identical
to the tracked declaration once the shared file merges.
`TAO_ALLOW_MAIN_CHECKOUT_EDIT=1` disables the main-checkout denial for a
user-approved exception only; it is never a default and never set by tooling.

If an older session already opened a clean main-checkout run before relocating,
settle it with `tao-hook cancel --evidence <SOURCE> --replacement-evidence
<COMPLETED_LINKED_WORKTREE_RUN>`. Cancellation is fail-closed: both runs must
share the request, runtime session, route, rules root, and Git common directory;
the replacement must be a completed linked worktree and the source checkout
must have no tracked or untracked changes. The command preserves both evidence
directories and writes a content-free cancellation receipt.

A run whose honest outcome is that nothing needed changing is settled the other
way, with `tao-hook cancel --evidence <RUN> --no-change-evidence "<why>"`. The
two are mutually exclusive: a transfer says another run did the work, and this
says the work was correctly not done. It is proven rather than asserted, by two
observations -- the checkout is clean, and the run's own continuation packet
records no changed scope. The second is what covers a run that changed files and
committed them, which a clean checkout alone would not catch. A file written
outside the governed path leaves no record in either place; preventing that is
the pretool gate's job.

Reach for it when an investigation route ends in "no change needed": the review
hook refuses every scope with `no changed paths` and cannot attest a clean
checkout, so without this the run stays unfinished, and unfinished runs are what
make a session start blocking its own edits.

Either cancellation also records, per session, that this session's work in that
project is closed, which is what the Claude Stop gate reads before blocking a
stop. Without that record the gate kept blocking a session that had cancelled
correctly, and told it to run `review` and `finish` on a run already terminal --
a remedy nothing could accept.

## Before Reporting

- Re-check the final diff or touched files.
- Separate changes made by the agent from pre-existing changes.
- Mention skipped cleanup or unrelated issues instead of bundling them into the
  task.
- Do not claim the worktree is clean unless it has been checked.

Before staging or committing, compare staged files against the task scope:

```text
git diff --name-only
git diff --cached --name-only
git status --short --untracked-files=all
```

Stage only files that were inspected and are part of the current task.

Before branch creation, push, PR, or tag publication, check the branch context:

```text
git status -sb
git branch --show-current
git remote -v
```

Use repo-local policy and `common/skills/branch-strategy/SKILL.md` to decide whether the
current branch is a work branch, integration branch, release branch, or
protected branch. If the repo has multiple plausible bases or targets, stop
before moving work or mutating remote state.

## Never

- Use destructive history or filesystem commands to simplify the task without a
  direct user request.
- Hide unrelated edits inside a broad refactor or formatting pass.
- Commit files that were not inspected when they contain pre-existing changes.
