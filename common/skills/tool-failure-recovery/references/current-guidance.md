---
keyflow_id: sys_tool_failure_recovery
status: stable
type: human-reviewed-needed
---

# Tool Failure Recovery

Use when a build, test, lint, typecheck, formatter, package, script, file-edit,
or local tool command fails.

## Default

Do not blindly retry, broadly revert, or silence the failure. Read the actual
stdout/stderr, identify the failing boundary, and make the smallest correction
that addresses the observed error.

## Diagnose

Capture the useful facts before editing:

- command, working directory, and exit code
- first failing file and line number, when present
- error code, exception type, test name, or assertion message
- whether the failure is from code, config, missing dependency, environment,
  sandbox, permissions, network, timeout, flaky external state, or edit context
- whether the failing area was touched by the current task

If output is truncated, rerun the narrowest command that exposes the relevant
error. Do not paste secret values from logs.

## Correct

- Fix the smallest relevant code, config, test, fixture, or docs issue.
- Preserve unrelated user changes and unrelated failures.
- Rerun the narrowest command that proves the correction.
- Escalate or ask only when the failure requires network, credentials,
  destructive cleanup, external state, or a product decision.
- If the same command fails twice for different reasons, repeat diagnosis from
  the new output instead of assuming the old cause.

## Environment And Permission Failures

Some failures cannot be corrected by editing project files. If output points to
sandbox, permission, network, registry, cache, missing toolchain, or unavailable
service state:

- Do not keep editing code to compensate for an environment failure.
- Retry only after a concrete condition changes, such as approval, network
  access, a different documented cache path, an installed tool, or a repo-local
  setup command.
- Use approved escalation paths for network, package, or filesystem access.
- Prefer temporary local caches over changing global caches when the package
  manager supports it.
- Report the blocker when the needed condition cannot be changed safely.

### Do Not Misdiagnose A Gate Refusal

A workspace gate refuses on the invocation's working directory, not on the
executable being run. Before concluding that an interpreter, a network path, or
a credential is unavailable:

- Check the working directory first. When the session's cwd is the main
  checkout of a worktree-gated project, every mutating tool is refused,
  including read-only invocations such as `git ls-remote`. Passing an explicit
  target path (`git -C <worktree>`) does not help because the gate reads the
  invocation's cwd. Move the cwd itself (`cd <worktree>`) instead.
- Run a control command before blaming the environment. If the same binary
  succeeds against a known-good target, the refusal is a gate decision, not a
  missing tool, a network outage, or an authentication failure.
- Run the command the gate prescribes verbatim. Appending a pipe or
  redirection (`... 2>&1 | head`, or a bare `--help`) can make the start hook
  itself fail the gate's own allowlist match, so the gate returns the same
  "run the start hook" message that the hook was meant to clear. That reads as
  a deadlock in which the gate blocks its own remedy; dropping the pipe
  resolves it.
- Correct an earlier wrong diagnosis explicitly when the real cause is found,
  because a reported blocker changes what the requester does next.

## Common Scenarios

Hook failure:

- Treat a hook `FAIL` as an active recovery task, not a handoff summary.
- Read every failure detail and classify it as safe scoped fix, scope decision,
  environment blocker, external-state risk, or broader refactor.
- Follow the canonical bounded repair cycle in
  `workflows/skills/retrospective-learning/SKILL.md`: run an actionable
  retrospective, improve and verify the owning Tao Agent OS guidance, hook,
  validator, or test, then resume the original task at
  `first_failed_checkpoint`.
- Keep the hook read-only. Apply safe scoped fixes outside it only after the
  durable Tao Agent OS improvement is verified.
- If recovery requires destructive action, credentials, external state, or a
  broader refactor, ask before acting. Stop when the same failure signature
  recurs after repair, the repair is unsafe or ambiguous, source ownership is
  uncertain, or the single repair cycle would be exceeded.

Lint or formatting failure:

- Prefer repo-local format or lint commands.
- If auto-fix changes unrelated files, keep only changes that belong to the
  task and report the rest.

Compile or type failure:

- Fix the type, import, contract, or generated artifact that caused the error.
- Do not downgrade types, add ignore comments, or loosen compiler rules just to
  make the check pass.

File edit failure:

- Re-read the target file and patch the current content.
- Check whether another change altered the expected context.
- Avoid broad rewrites when a smaller patch is available.

## Flaky Failures

Treat a failure as flaky only when there is evidence of nondeterminism, such as
intermittent pass/fail behavior, timeout, race, external service instability, or
order-dependent tests.

When flakiness is suspected:

- Rerun the smallest failing test or command once to confirm the pattern.
- Check whether the failure depends on time, random order, parallel execution,
  network, filesystem state, cache, or shared external state.
- Do not mark the work verified just because a repeated command happened to pass.
- Stabilize the test or isolate the nondeterministic boundary when it is in
  scope.
- If stabilization is out of scope, report the flaky signal, rerun count,
  observed results, and residual risk.

## Clean Build Or Cache Recovery

Use clean rebuilds only after output suggests stale artifacts, corrupted cache,
generated-file mismatch, dependency resolution drift, or build-system state.

Before cleaning:

- Prefer repo-local clean commands or documented wrappers.
- Identify the cache or artifact being removed.
- Avoid deleting global caches, user data, simulator state, derived data, or
  dependency stores without approval.
- Keep dependency reinstall, generated output, and lockfile changes separate
  from code fixes unless the task requires them.

Examples of acceptable local recovery paths when repo-local policy allows them:

```text
package-manager clean/build command from the repo
project clean task or build wrapper
targeted generated-client regeneration
targeted local build output deletion
```

## Do Not

- Repeat the same failing command more than twice without a changed hypothesis.
- Run broad cache deletion or reinstall commands without evidence and approval.
- Delete tests, loosen assertions, or bypass lint rules only to make checks pass.
- Catch and ignore runtime errors to hide a failing path.
- Roll back broad files when a line-level correction is available.
- Mark verification as passed when the command failed for environment reasons.

## Report

For unresolved failures, report:

```text
Command:
Failure:
Likely cause:
What was changed:
Next action or blocker:
Residual risk:
```
