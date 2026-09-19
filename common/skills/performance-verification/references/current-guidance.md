---
keyflow_id: sys_performance_verification
status: stable
type: human-reviewed-needed
tao_card_contract: strict
---

# Performance Verification

Use when changing or reviewing performance, loading behavior, rendering cost,
startup, frame time, memory, bundle size, binary size, query latency, cache
behavior, background work, animation smoothness, or runtime resource use.

The goal is to measure the user-facing performance claim instead of inferring it
from code shape.

## Use When

- A change claims faster load, smoother interaction, lower memory, fewer
  allocations, smaller bundle/binary size, less jank, reduced latency, or better
  cache behavior.
- A UI, data, release, build, or integration change can affect runtime cost.
- A review needs to distinguish a proven performance fix from structural cleanup.

For browser-specific tooling, also use
`common/skills/web-performance-verification/SKILL.md`. For platform-specific
profilers or benchmark frameworks, also use the matching platform card.

## Inspect First

- Repo-local performance budgets, existing measurements, benchmark harnesses,
  profiler setup, CI checks, and release build commands.
- The affected user path, device class, viewport/window size, data state,
  network/storage profile, and build mode.
- The touched boundary: rendering, state observation, list virtualization,
  startup, I/O, cache, network, database, bundle/binary, background job, or
  platform bridge.

## Decision Rule

Do not claim a performance improvement without measurement that matches the
claim. If measurement is unavailable, describe the change as diagnostic evidence
or structural risk reduction, not as a proven performance fix.

## Process

1. Define the performance claim and user-visible path.
2. Pick one metric: frame time, startup, scroll, interaction latency, memory,
   allocations, CPU, I/O, query time, bundle/binary size, request count, cache
   hit behavior, or media bytes.
3. Establish a baseline when feasible.
4. Diagnose the most likely cause from profiler, trace, benchmark, or runtime
   evidence.
5. Fix one cause at a time.
6. Re-run the same or stricter measurement.
7. Record environment details: build mode, device/emulator/simulator/browser,
   OS/runtime version, viewport/window size, data state, network/storage profile,
   and tool used.

## Bounded Measurement Work

- Reuse a compatible repo measurement runner before creating another harness.
  Add only the missing metric or scenario; a runner failure is not a reason to
  duplicate the experiment while its earlier invocation remains pending.
- Keep one in-flight invocation for an equivalent measurement. A pending tool
  or approval result is not failure or proof of non-execution. Before switching
  runners, confirm the earlier invocation finished or its cancellation completed,
  and reconcile any output. Follow runtime recovery and permission rules; this
  does not authorize killing unrelated processes or bypassing approval.
- Preserve an accepted baseline. Give retries and before/after runs distinct
  output paths so a delayed invocation cannot overwrite the comparison input.
  Accept a sample only after successful completion and matching environment and
  scenario checks; do not combine partial outputs from competing runs.
- Investigate one evidence-backed hypothesis per measurement. Independent work
  may run in parallel when it cannot perturb the sample. Expand to another
  boundary when the current measurement contradicts it or cannot explain the
  observed delay, not merely because more performance guidance is available.
- After a correction, repeat its affected measurement and correctness checks.
  Retain the final integrated diff review and required regression coverage;
  passing evidence may be reused while its covered inputs and conditions remain
  valid; failed or unresolved checks remain open. Separating a measurement from
  a failed behavior check does not remove that check from acceptance: retain it
  separately or report the unverified behavior. No extra
  gate, receipt, or measurement framework is required by these rules.

## Evidence Levels

| Evidence | Use |
| --- | --- |
| Production/release-like benchmark, trace, profile, or field metric | Can prove a performance claim when it matches the path and metric. |
| CI benchmark or repo-provided performance test | Can prove regressions when the harness is stable and comparable. |
| Debug tools, previews, hot reload, inspector counts, emulator/simulator-only runs | Diagnostic unless the claim is explicitly development-only. |
| Code review, typecheck, screenshots, or successful build | Structural evidence only; does not prove runtime performance. |

When reporting diagnostic-only evidence, say exactly that. Do not let the final
handoff imply a user-visible performance win.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "This code is obviously faster." | Measure or state that no performance claim is proven. |
| "The build passed." | Build success does not prove load, runtime, or interaction performance. |
| "The inspector says fewer recompositions/renders." | Treat it as diagnostic until release-like runtime cost is measured. |
| "Hot reload felt smoother." | Keep iteration speed separate from production correctness and performance. |
| "The issue only affects slow devices." | Use an appropriate device/profile or report residual risk. |

## Red Flags

- A performance claim has no metric, path, environment, or baseline.
- The measured path is not the path changed by the diff.
- Development-mode evidence is used to prove a release-mode claim.
- A structural split is described as a performance fix without naming the
  observer, render node, query, job, or runtime resource that improved.
- A performance change bypasses correctness, lifecycle, accessibility, security,
  cache invalidation, or recovery checks.

## Do Not

- Do not equate typecheck, unit tests, screenshots, or static review with
  performance evidence.
- Do not compare development/debug results against production/release claims.
- Do not tune a secondary metric while regressing the product behavior users
  actually feel.
- Do not batch unrelated performance fixes into one change when the cause is not
  isolated.

## Stop If

- The performance target, metric, path, device class, data state, or build mode
  is unclear and can change the recommendation.
- The change affects auth, privacy, payment, persistence, migration, release,
  or external state and performance work would bypass required checks.
- Measurement tooling is unavailable and the user expects a proven performance
  result rather than a structural review.

## Verification

Use the narrowest reliable measurement that proves the claim: benchmark,
release/profile build, profiler, trace, browser/runtime performance tooling,
database query plan, bundle/binary analysis, network waterfall, memory snapshot,
or repo-provided performance test.

## Report

Report the metric, path, environment, before/after when available, command or
tool used, and whether the result proves performance or only reduces structural
risk.
