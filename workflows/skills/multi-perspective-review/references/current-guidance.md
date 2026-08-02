---
keyflow_id: sys_multi_perspective_review_workflow
status: stable
type: human-reviewed-needed
---

# Multi-Perspective Review

Use for non-trivial reviews where a single correctness pass may miss product,
UX, architecture, reliability, security, release, or QA risk.

Review perspectives are lenses, not fictional voices. Each perspective should
produce concrete findings, risks, and verification gaps.

## Use When

- code changes are non-trivial
- UI, interaction, or navigation changed
- architecture, module boundaries, or refactors changed
- permissions, privacy, security, packaging, or distribution changed
- release candidates need a broad readiness pass
- a feature idea needs structured critique before implementation

For tiny mechanical edits, use `common/skills/code-review/SKILL.md` directly.

## Context Packet

Collect:

- user request or feature intent
- changed files or diff summary
- relevant PRD, ARD, issue, task, or design note
- product constraints and non-goals
- verification already run
- known unresolved questions and residual risk

Do not invent acceptance criteria when a blocking product decision is missing.
Use `workflows/skills/ambiguity-gate/SKILL.md` first.

## Perspectives

Product / Scope:

- product fit, scope creep, user value, non-goals, and whether the change belongs
  in this product surface

Platform UX:

- platform conventions, visual hierarchy, hit targets, menus, navigation,
  motion, accessibility labels, and discoverability

Workflow:

- repeated-use speed, keyboard and pointer ergonomics, fallback paths, and
  recovery from disabled or failed states

Architecture / Maintainability:

- module boundaries, state ownership, side effects, coupling, testability,
  migration safety, and whether complexity is reduced or hidden

Reliability / Performance:

- refresh cadence, async cancellation, resource use, timeouts, startup behavior,
  stale data, unavailable dependencies, and failure recovery

Security / Privacy / Release:

- permissions, secrets, user trust, private or privileged API risk, data
  retention, packaging, signing, deployment, and rollback

QA / Regression:

- edge cases, empty/loading/error/permission states, known regressions,
  automated coverage, smoke/manual coverage, and missing acceptance checks

## Specialist Personas

Use these as named lenses when they match the risk. They are roles in the review
packet, not separate authorities:

- Code Reviewer: correctness, readability, ownership, imports, side effects,
  maintainability, and nearest tests.
- Test Engineer: assertions, fixtures, state coverage, boundary values,
  regression evidence, and missing automated or manual checks.
- Security Auditor: auth, permission, tenant, secret, privacy, dependency,
  logging, and release trust boundaries.
- Web Performance Auditor: Core Web Vitals, bundle size, runtime cost, network,
  cache, layout shift, and measurement quality.

Split these across subagents only when each reviewer receives raw artifacts,
clear scope, and no leaked expected answer. Merge duplicate findings and keep
the final recommendation in one place.

## Output

Lead with findings:

```text
Findings:
- [Severity] Perspective: path:line or behavior area - issue, impact, recommendation, verification
```

Then include:

- cross-perspective tradeoffs
- open questions
- verification gaps
- concise recommendation

If there are no findings, say so clearly and list remaining test gaps or
residual risk.

## Severity

- Blocker: should not ship without a fix or decision.
- High: likely user-visible regression, data loss, permission confusion, trust
  risk, or unbounded maintenance cost.
- Medium: meaningful risk, missing tests, or workflow issue that should be fixed
  soon.
- Low: polish, clarity, naming, or minor maintainability improvement.
- Note: observation without required action.

## Structured Findings

When findings from parallel reviewers must be merged mechanically, require each
finding to carry:

- severity: one of the levels above
- confidence: High (reproducible from the diff and code evidence alone),
  Medium (conditional but evidenced), Low (plausible, needs confirmation)
- file and line
- duplicate_key: stable dedupe key in the form
  `<category>:<file>:<short-problem>`, for example
  `state:UserProfileViewModel:stale-avatar-after-save`
- rule_ref: path of the governing rule doc, or `none`
- evidence: grounded in the diff or referenced code
- impact: concrete behavior, user, or maintenance effect
- suggestion: minimal fix direction

Merge cross-reviewer duplicates by duplicate_key first, then by
file/line/title. Drop findings with no file and line evidence,
preference-only suggestions ("looks cleaner"), "might be a problem someday"
claims with no concrete trigger, and issues that pre-date the diff.

A reviewer with nothing blocking outputs exactly `No blocking findings.` — no
praise, no summary, no filler — so the merge step can parse results
mechanically.

## Modes

- Full review: use every perspective.
- Lightweight review: Product / Scope, Architecture / Maintainability, and
  QA / Regression.
- Release review: full review plus repo-local release checklist.
- Delegated review: split perspectives across agents only when write scopes and
  review ownership are explicit.

Merge duplicate findings. If perspectives disagree, name the tradeoff instead
of averaging it away.

## Read-Only Reviewer Contract

A delegated reviewer without write scope must not: create, modify, or delete
files; author patches; run formatters or fixers; install dependencies; create
build artifacts or caches; mutate external state; stage; or commit. It must not
report in an "I fixed it" voice.

It may run bounded non-mutating diagnostics whose contract is to read existing
state and emit findings, such as `git status`, `git diff`, `git show`, `rg`, and
file inspection. A test, linter, build, package-manager command, or unfamiliar
script needs separate execution scope unless the orchestrator has established
that it will not write files, caches, generated output, or external state. When
side effects are unknown, the reviewer returns the proposed command to the
orchestrator instead of running it.

Allowed outputs are structured findings and suggested fix directions. The
reviewer does not acquire mutation authority merely because a diagnostic found
a valid issue.

A delegated-reviewer prompt includes, in order:

- role lens: which perspective this reviewer owns
- scope: files, diff, or PR range
- requirement summary
- role-specific focus notes
- hard rules: read-only, structured findings only
- the context packet

When a reviewer runs in an external agent runtime, never guess or hardcode its
invocation flags. Use only a user-designated invocation. If none is confirmed
or auth is blocked, mark that reviewer unavailable, substitute an equivalent
internal reviewer, and record the substitution in the final report.

## Verify-Then-Fix

Use when the review should end in applied fixes, not only comments.

- Exactly one orchestrator agent applies patches. Every other reviewer is
  read-only; its findings are advisory input, never applied verbatim.
- The orchestrator independently re-verifies each finding against the code
  before fixing. Even a High finding from another reviewer may be declined
  when its evidence is weak; record the decline reason.
- Fix only Blocker and High findings, plus Medium findings with clear runtime,
  UX, data, or architecture regression risk. Do not fix style or naming
  preferences, speculative cleanup, large structural changes, or pre-existing
  problems outside the review scope.
- One finding maps to one small patch. Do not widen existing behavior while
  fixing.
- For already-verified critical flows, prefer a behavior-preserving wrapper
  over an in-place rewrite.
- Judge UI fixes with their interaction side effects — transition, focus,
  scroll, input method, re-render — not just the code diff.
- Compile and run focused tests after each fix. On failure, analyze the cause
  and add only the minimal correction.
- Report fix-centric, not finding-centric: fixed issues, declined issues with
  reasons, verification results, remaining risk.

## Stop If

- Required context is missing: request, diff, acceptance criteria, known risk, or
  verification evidence.
- A blocking product, security, release, or data decision is unresolved.
- The review would invent acceptance criteria instead of using the request,
  PRD, ARD, issue, or repo-local policy.
- A release review is requested but repo-local release artifacts or checks are
  unavailable.
