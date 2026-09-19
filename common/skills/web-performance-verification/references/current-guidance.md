---
keyflow_id: sys_web_performance_verification
status: stable
type: human-reviewed-needed
tao_card_contract: strict
---

# Web Performance Verification

Use when changing or reviewing web performance, loading behavior, bundle size,
rendering cost, Core Web Vitals, caching, image/media loading, streaming,
hydration, animation performance, or browser resource use.

The goal is to measure the user-facing performance claim instead of inferring it
from code shape.

For all-platform performance proof rules, first use
`common/skills/performance-verification/SKILL.md`. This card adds browser and
web-runtime measurement details.

## Use When

- A change claims faster load, smoother interaction, smaller bundle, reduced
  memory, fewer requests, or better Core Web Vitals.
- A UI or data change can affect network, JavaScript execution, rendering,
  layout shift, image loading, or caching.
- A release needs a web performance readiness pass.

For non-web UI verification, use the matching platform visual verification card.

## Inspect First

- Repo-local performance budgets, existing measurements, CI checks, and browser
  test setup.
- The affected route, viewport, device class, network profile, and user flow.
- Bundle, asset, cache, API, and render boundaries touched by the diff.
- Applicable web platform contracts; detailed UI or visual procedures only when
  the changed behavior or an unresolved verification question requires them.

## Decision Rule

Do not claim a performance improvement without a before/after measurement or a
clear statement that only a structural risk was reduced. Choose metrics that
match the user-visible claim.

## Process

1. Define the performance claim and the user path it affects.
2. Pick the metric: load, interaction latency, layout stability, CPU, memory,
   bundle size, request count, cache hit behavior, or media bytes.
3. Establish baseline when feasible.
4. Run the smallest reliable measurement for the changed path.
5. Compare before/after or report partial evidence.
6. Record environment details: browser, viewport, device/emulation, network,
   build mode, and data state.

## Loading Investigations

- Separate deployed first visits, client-side navigation, local production
  builds, and development startup. Label auth/data and cold/warm cache state;
  a fresh browser context does not reset server caches. If the reported scenario
  is unresolved, bounded common-path diagnosis may continue, but do not present
  its result as proof of the user's deployment latency.
- HTTP first-byte time, complete response time, and response bytes locate part
  of the cost; they do not measure when the useful page appears. Choose a stable
  selector for the intended content, not an arbitrary first article unless it
  actually represents that outcome. Report LCP's observation window; a fixed
  sleep supplies a bounded sample, not necessarily the page's final LCP.
- Prefer the network waterfall, request initiator, build manifest, or source
  import chain to explain a costly chunk. Search a minified bundle when those
  sources cannot resolve the dependency; do not treat a library string match as
  proof that its code executes on initial navigation.
- Keep source/query findings distinct from measured improvements. Redundant
  reads are a candidate fix, while cache invalidation, visibility and auth checks
  remain necessary when that fix changes which data is fetched or reused.

## Common Rationalizations

| Rationalization | Required Response |
| --- | --- |
| "This code is obviously faster." | Measure or state that no performance claim is proven. |
| "The bundle built successfully." | Build success does not prove load, runtime, or interaction performance. |
| "One Lighthouse run is enough." | Check stability, environment, and whether the metric matches the claim. |
| "The issue only affects slow devices." | Use an appropriate device, throttle, or residual-risk note. |

## Red Flags

- A performance claim has no metric, path, or environment.
- The measured path is not the path changed by the diff.
- A bundle-size change ignores dynamic imports, images, fonts, or third-party
  scripts.
- Caching changes lack invalidation or stale-data verification.
- Animation or layout changes are checked only at desktop size.

## Do Not

- Do not equate typecheck, unit tests, or screenshots with performance evidence.
- Do not compare development mode against production build unless the claim is
  explicitly development-only.
- Do not hide network, third-party script, image, font, or cache cost outside
  the measured surface.
- Do not optimize one metric by regressing accessibility, correctness, or
  recoverability.
- Do not add client-side caching without invalidation and privacy review.

## Stop If

- The performance target, route, viewport, or data state is unclear and can
  change the recommendation.
- The change affects auth, privacy, payment, persistence, or release behavior
  and performance work would bypass required checks.
- Measurement tooling is unavailable and the user expects a proven performance
  result rather than a structural review.

## Verification

Use Playwright/browser traces, Lighthouse, Web Vitals, bundle analysis,
production build checks, network waterfalls, CPU profiles, memory snapshots, or
repo-provided performance tests. Use the narrowest tool that proves the claim.

## Report

Report the metric, path, environment, before/after when available, command or
tool used, and whether the result proves performance or only reduces structural
risk.
