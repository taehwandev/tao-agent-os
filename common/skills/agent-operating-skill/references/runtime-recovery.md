---
keyflow_id: sys_runtime_recovery
status: stable
type: ai-generated
---

# Runtime Recovery

For an explicitly selected new project, `mkdir [-p] <one absolute new path>`
is directory bootstrap wherever its nearest existing parent resolves outside
an existing Git checkout. `-p` may create intermediate directories; a safe
parent alias is allowed. Existing targets, hidden target names, `..`, extra
options and chained writes retain ordinary checks. Create and edit the new
project in its own directory; once it becomes a governed Git project, follow
its instructions and use a linked worktree for changes to a protected checkout.
Do not audit unrelated repositories merely because the shell started there.

Read only for the condition named by the runtime bridge, not as an extra startup reading list. Paths below are relative to <TAO_ROOT>. Current user authority and project instructions prevail.

A Codex exec result that only reports `Script running with cell ID ...` or a session id is transport state, not proof that the command started or that approval was rejected. Keep only one pending equivalent request. Resume that request with the matching wait tool; sequential waits are not duplicate execution or renewed approval requests. Use bounded waits compatible with runtime guidance and keep the user informed. A quiet wait interval is not a failure deadline: do not cancel or hand the task to the user solely because output is absent. For an idempotent local command that normally completes immediately, do not spend multiple minutes on repeated empty waits. After one bounded wait, if the command has reported no progress and target-state evidence still shows no side effect, request interruption and reconcile possible side effects. If interruption reports Operation not permitted, do not report the request as cancelled. For a verified read-only lookup with no pending approval or actual execution denial, one fresh bounded lookup may recover the answer without resolving the old terminal handle; preserve that handle as unresolved. A successful fresh lookup establishes only that the read works, not that the old session was closed or that writes work. Never kill another session or its parent runtime to clear a terminal count. Local writes still require confirmed termination and effect reconciliation before retry. This recovery does not apply to non-idempotent or external writes. Use available read-only process or target-state evidence when needed; unchanged files or an unavailable process listing alone do not prove denial or non-execution. Outside the bounded idempotent-local recovery above, cancel only for a user stop, an explicit failure/timeout, or evidence that the request cannot progress. Before retrying a cancelled request, confirm it is no longer pending and reconcile possible side effects. Use a supported recovery path within existing authority and required sandbox approval; never automatically retry a non-idempotent external write. A real denial must be handled through the permitted approval path, never bypassed with another tool. Do not ask again for user authorization already given. Keep agent-executable recovery with the agent; request a user action only for a verified user-only prerequisite and name that prerequisite. Pending transport alone does not establish inability to complete the task; do not end with an unsupported cannot-do conclusion or instructions for the user to run the same command. Attribute a target change to an actor only with direct actor evidence, not a delayed command or changed target state alone.

Permission evidence: reuse user approval for the identical action and target; request required sandbox escalation through the tool, not another conversational approval. DNS/name-resolution errors alone do not prove sandbox denial. A pending tool result alone does not prove that an approval dialog is visible or awaiting a user click. State the observed error and what remains unverified; never instruct the user to approve an unconfirmed dialog.

Native Codex approval and Tao admission are separate boundaries. A native
"Would you like to run" or "send input to terminal" prompt does not become a
Tao operator-review request. Never self-approve either boundary or change the
user's approval policy or sandbox profile to clear a prompt.

Honor Codex's configured native reviewer, including `auto_review`. For an
already authorized action and target, submit required sandbox escalation through
the execution tool and let that reviewer handle eligible approval requests;
do not add a conversational approval question for the same permission. Keep one
pending request and use its handle. A successful review supplies native execution
permission only: it does not widen the user's requested scope, settle a Tao
operator-review request, or override an explicit rejection. Handle an actual
denial through the permitted recovery path. Ask only when existing authority and
agent-executable recovery leave a material decision for the user; name that
decision rather than asking again to perform the original task. Do not change
`approvals_reviewer`, `approval_policy`, or sandbox settings as a prompt workaround.

For a Tao operator handoff, first reuse existing authority and independently
gated agent-executable recovery. An unreadable command effect does not prove a
write and must not replace actionable workflow-entry or isolation recovery
with a duplicate permission question. Read-only, target scope, publication and
explicit rejection checks still apply. Codex operator consent cannot waive
read-only, isolation, ordinary missing-entry or publication checks; the named
paused-run exception retains its exact explicit decision contract.

If a genuine Tao operator decision remains, prefer an available structured
choice tool explicitly permitted for approvals, such as
`request_user_input_async`. Do not use the plan-only `request_user_input` for
permissions. Explain the exact action and target, expected effect and reason,
and offer allow once / always allow this exact action and target / reject.
Otherwise show the same choices as a short numbered list in conversation.
The agent records an explicit selected or free-text answer internally; never
make the user run an approval helper or send `y` to a CLI stdin prompt.
Preselection and silence grant no authority. The exact-call consent, waiting,
expiry and revocation contract is in
`common/skills/worktree-hygiene/references/current-guidance.md`; use it when a
remaining operator decision needs handling. Native sandbox escalation still
uses the execution tool rather than this question.

Before submitting an authorized test or local build, use literal argv that
matches an existing native prefix rule. A shell assignment such as
`KEY=value <runner> <args>` can cause Codex to match the entire shell invocation,
so a different task list or worktree asks again. When the existing rule covers
it, use `env KEY=value <runner> <args>` with the same literal environment value,
runner, arguments, target and conditional ordering. Keep the absolute
`cd "<worktree>" &&` target explicit. Do not introduce expansions, substitutions
or redirections merely to set the runner's environment. Verify matching with
`codex execpolicy check --rules <rules-file> -- <argv>` when it is uncertain;
this inspects policy without executing the requested command.

If no existing rule covers required escalation, request it through the tool
with a stable, scoped runner prefix rather than the full task list, shell
script or worktree command. An environment wrapper prefix includes its exact
literal assignments and runner; never request a blanket `env`, interpreter or
shell prefix. A matching rule grants only native execution permission. Keep
the user's action and target authority and Tao checks: tests or local packaging
do not authorize install, publish, deploy or unrelated writes. Apply invocation
choices before submission. Do not rewrite a denied command or resubmit a
pending equivalent request; follow the denial or pending-request recovery above.

For a semantic checkpoint, save the bounded work object to an ignored local
JSON file and invoke `<TAO_LAUNCHER> checkpoint ... --work-file <absolute-path>`
once, with exact run evidence. The file uses the same byte budget and schema as
`--work-stdin`, and supplies no new action authority. Use stdin only when the
caller can deliver it noninteractively in the original invocation. Do not
launch an escalated interactive terminal solely to send JSON later with
`write_stdin`: sending input to that terminal has a separate native permission
boundary. A real interactive session may still need that approval. An already
pending terminal-input request stays pending until it is answered or confirmed
cancelled; changing the checkpoint transport does not settle it.

When a Codex session starts outside its task worktree, make every shell command's execution directory explicit: use `git -C "<worktree>" <args>` for Git and `cd "<worktree>" && <command>` for other commands, with an absolute, shell-quoted worktree path. Do not rely on exec_command.workdir alone: Codex versions that send only tool_input.command to PreToolUse leave the hook with the session cwd. Keep workdir consistent when supplied, and use absolute worktree paths for file-edit tools. Reuse the current bound task instead of creating another worktree or restarting its workflow after a location denial. Explicit targeting does not grant sandbox permission; preserve checks on actual write targets and request escalation only for a real permission boundary.
