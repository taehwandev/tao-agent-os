---
keyflow_id: sys_verification_policy
status: stable
type: human-reviewed-needed
---

# Verification Policy

Work is not done just because files changed. Completion requires evidence or a
clear explanation of why evidence could not be collected.

For the final completion bar before handoff, commit, release, PR, or final
report, also use `common/skills/definition-of-done/SKILL.md`.

## Verification Order

Prefer the smallest reliable check first:

```text
format / static check
typecheck / compile
unit test
focused integration test
UI or end-to-end test
manual smoke test
package / release check
```

Run broader checks when the change touches shared models, cross-module
contracts, API or schema compatibility, persistence, auth, permissions,
payments, filesystem, network, accessibility-critical UI, platform integration,
deployment, migration, or release packaging.

## Before The First Check In A Fresh Checkout

A new worktree or clone is missing every ignored local file the build needs. Collect
that list from the build configuration before the first run, not from failure
messages.

- Read the build scripts and their signing, credential, and environment blocks, and
  collect every referenced local file: `*.properties`, keystores and certificates,
  service-account keys, and local SDK or path config.
- Check that list against the source checkout in one pass, then copy only what is
  missing. Do not print the contents, and confirm afterwards that each copied file
  is still ignored.
- Do not infer which files are needed from the build type or variant. A debug
  variant can still run a signing-config validation step that demands the release
  keystore.
- When a run fails with "file not found", copy that file **and** re-check the rest of
  its kind in the same pass. Fixing one file per run turns a single setup step into
  a failure-and-copy loop as long as the file list.

## Choose Checks By Change Type

Use repo-local commands and names. This table defines the minimum evidence shape,
not exact command strings.

| Change type | Minimum verification |
| --- | --- |
| Documentation only | markdown/frontmatter/link check when available, plus whitespace or diff check |
| Formatting only | formatter or diff check, and confirm behavior files were not unintentionally changed |
| Copy or labels | locale/message parity when applicable, plus affected UI or snapshot check when text can overflow |
| Pure refactor | nearest tests for the moved or extracted behavior; typecheck/build when exported contracts changed |
| Runtime behavior | targeted unit, integration, or component test; manual smoke for the affected user/API path when no test exists |
| Boundary value mapping | normal, missing, invalid, lower bound, upper bound, stale, duplicate, and unavailable cases for the parser, mapper, or adapter |
| Shared module, API, schema, or DTO | caller-focused tests plus contract, serialization, or compatibility check |
| UI layout or interaction | component or browser check for main interaction, loading, empty, error, disabled, and responsive states as relevant |
| Auth, permissions, tenant, billing, or privacy | allowed and denied paths; stale, revoked, or invalid input path when relevant |
| Persistence, cache, sync, or migration | write/read/update/delete or load/save path; invalidation, stale data, rollback, or backward compatibility note |
| External integration, background job, filesystem, network write, release, or deploy | dry run, sandbox, staging, or explicit approval path; idempotency or rollback evidence when applicable |

If a change fits multiple rows, use the highest-risk applicable row.

## Risk Levels

- Low: docs, comments, isolated copy, or mechanical formatting. A narrow static
  check may be enough.
- Medium: local component, hook, utility, route, or command behavior. Run the
  nearest targeted automated check when available.
- High: auth, permissions, billing, personal data, persistence, cache,
  migration, public API, external state, platform integration, release, or
  shared contract. Use targeted tests plus a contract, integration, manual
  scenario, or explicit residual-risk report.

High-risk work is not complete with only a formatter, linter, typecheck, or
successful page load.

## Capture The Verdict, Not The Log

A check's output is evidence; carrying all of it into the conversation is not.
A full suite run in this repository prints about 14 KB — roughly 3,500 tokens —
and its verdict is three lines. Redirect the run to a file, read those lines,
and quote the numbers into the report. The log stays on disk for the one case
that needs it: a failure whose detail you have to read.

```text
<command> > <run-log> 2>&1; echo "exit=$?"
grep -nE "^(OK|FAILED|Ran [0-9]+ tests)" <run-log>
```

Never pipe the run itself into `head`, `tail`, or `grep`. A pipeline's status
is the last command's, so a failing suite whose output is filtered reports
success, and the filter is what you would be trusting. Redirect first, capture
the run's own exit code, then read the file.

This is about your own check commands. A workflow hook is run verbatim: adding
a redirection there can break the permission prefix the gate matches on, which
reads as the gate refusing its own remedy. See
`common/skills/tool-failure-recovery/SKILL.md`.

The same rule scales down: prefer the nearest checks while iterating and run
the full suite once before finish. That is a wall-clock saving rather than a
token one — the log was never the expensive part once it stays in a file — but
a check that finishes in seconds gets run, and one that takes minutes gets
skipped.

## Evidence To Preserve

In the final response, include:

- exact command names for automated checks
- whether each check passed, failed, or was not run
- a short reason for skipped checks
- residual risk when verification is partial
- workflow gate ledger status when a scripted route was used

Prefer this compact format when multiple checks were run:

```text
Verified:
- PASS `command`: what it proved
- FAIL `command`: failure summary and next action
- SKIP `command`: why it was skipped and residual risk
```

For manual checks, name the user path, environment, input, and observed result.
Do not report screenshots, logs, or smoke checks as proof unless they exercise
the changed behavior.

When a scripted route was used, every route gate must have evidence before the
work is reported complete. If a required gate was not executed, follow missed
gate recovery instead of reporting completion.

Gate status is part of verification and has only two public states:

- `🐱🟢 SUCCESS`: executed with evidence.
- `🐱🔴 FAIL`: missed, blocked, failed, or missing evidence after the gate should
  have run; follow missed-gate recovery.

Before final report, commit, release, or handoff, every required gate must be
`🐱🟢 SUCCESS`.

Manual evidence should be specific:

```text
Manual:
- Scenario: unauthenticated user opens protected resource
- Environment: local browser, desktop viewport
- Action: visit the protected URL
- Expected: login or denied state
- Observed: redirected to login with the original destination preserved
```

## Prove The Claim, Not Something Beside It

A green test is not evidence that the thing it names works. It is evidence that
*something* works. The two separate only when you break the code on purpose and
watch the test fail.

Five defects shipped green in one session, all the same shape — the assertion sat
one level away from the claim:

| the test said | what it actually proved |
|---|---|
| the refusal names a stopped command | the phrase appears somewhere in the sentence, which also held while the sentence read `this project in this project` |
| the compactor takes the writer's lock | the writer and `state_lock` agree on a path — the compactor was free to lock a private file |
| `promote` is anchored so it is not a release | that request had no release scope, so it was not a release either way |
| the command runs once when cleanup fails | it runs once when cleanup *succeeds* |
| the hook prints the reason | the formatter formats — deleting the line that called it stayed green |

None of these was caught by reading. Every one was caught by a mutant.

**Write the mutant that should kill the test, and run it.** If the test survives,
it is testing its neighbour, not its subject:

- Assert the artifact the consumer receives — the whole sentence, the returned
  route, the printed line — not a fragment inside it or the helper that builds it.
- Reach the subject through the call the real caller uses. A test that invokes
  the helper directly cannot see broken wiring.
- Set up the failure the test is named for. A concurrency test whose happy path
  is all it exercises names a case it never runs.
- When a fix removes wording or behaviour, assert its absence too. An additive
  fix leaves the wrong thing sitting beside the new one.

### Judge A Mutant By Exit Code

```text
<test command> > <log> 2>&1; echo "exit=$?"
```

Not by counting `FAIL:` lines. A mutant that breaks the module — `SyntaxError`,
`RecursionError`, an import error — prints a traceback and no `FAIL:` line at
all, and a grep-based detector reports it as a survivor. That misreading happened
twice in the same session, in both directions: a surviving mutant called dead,
and a dead mutant called a survivor.

### Do Not Let The Host Answer

A test that reads ambient state — an environment variable, a cache directory, a
clock, a checkout — passes or fails by who ran it. One asserted that a fallback
returned success, which held only because that host's cache path happened to be
writable; in the sandbox the fallback exists for, the same assertion failed.

Set the condition the test depends on, or assert only what holds regardless.

## When Tests Are Missing

If no useful test exists:

- add a focused test when the change is risky enough
- otherwise perform a manual smoke check
- state that automated coverage is missing
- do not replace a missing high-risk test with a weaker assertion merely to make
  the check pass

## User-Executed Verification

When policy or the environment forbids the agent from running a check itself —
a fragile local toolchain, user-owned execution, or restricted commands — the
user is the executor and the user's report is the verification evidence:

- Hand the user the exact command or commands to run, plus the expected pass
  and fail signals.
- Wait for the reported result. Only the user-reported PASS or FAIL counts as
  gate evidence.
- Route a reported FAIL back into the fix loop like any other failed check.
- If the user declines or defers, the completion report must state the check as
  `unverified (not run by user)`. Never mark work verified on an unexecuted
  check, and never fabricate or imply that the check ran.

## When Commands Fail

Use `common/skills/tool-failure-recovery/SKILL.md`. A failed command is evidence, not a
reason to guess. Read stdout/stderr, identify the failing file, line, error code,
or test name, make the smallest relevant correction, and rerun the narrowest
proving command. Do not repeat the same command blindly or downgrade assertions
only to make the check pass.

## Do Not Overclaim

Do not say a feature is complete when:

- behavior is mocked or placeholder-only
- the user path was not exercised
- persistence or sync-back was not verified
- auth, permissions, or data loss cases are untested
- only formatting or compilation was checked for a behavioral change
- UI visibility was checked but the protected command or trusted boundary was not
  exercised
- boundary-dependent behavior was checked only with normal input
- an API response, DTO, migration, cache, or generated artifact changed without a
  compatibility or consumer check
- a visual snapshot was updated without stating the product reason
- tests were skipped only because they were slow, broad, or inconvenient
- generated files changed and their inclusion in the task was not confirmed
- only the author's own check ran. A self-declared "done" or "verified" is not
  credible on its own; the reliable signal is an independent check — a separate
  reviewer, or a negative control that injects the violation and confirms the
  check fails. When the integrator is also the only verifier, treat the result
  as unverified until one of those confirms it.
