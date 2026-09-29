---
keyflow_id: sys_android_review_runtime_performance
status: review
type: ai-generated
---

# Android Runtime Performance

Procedure for Android runtime performance outside Compose recomposition:
main-thread work, IO, startup, network and cache behavior, media and WebView
cost, and dependency or build cost. Use it when implementing a performance
change and when reviewing one. Compose recomposition, stability, lazy lists,
and modifier cost belong to
[compose-performance.md](../../android-compose-ui/references/compose-performance.md).
The all-platform measurement loop belongs to
[performance-verification](../../../../../common/skills/performance-verification/SKILL.md).

## 1. Classify The Bottleneck

Put the problem in one class before changing code.

| Class | Symptom | Check first |
| --- | --- | --- |
| UI frame / jank | scroll stutter, dropped animation frames | Compose performance guidance, Layout Inspector, heavy draw or layout |
| Main-thread blocking | frozen screen, input delay, ANR | disk IO, network, bitmap decode, JSON parsing, or file copy on the main thread |
| Startup | slow first launch or first screen | eager initialization, DI graph size, synchronous IO, remote config on the startup path |
| Data / network | duplicate calls, slow mapper, stale results | cache, paging, request dedupe, cancellation, stale-result guard |
| Media / WebView | memory growth, slow load, stutter with video or embeds | owner lifecycle, pool, preload scope, release on exit |
| Build time | slow compile, KSP/KAPT, configuration time | module boundary, plugin and dependency churn |

## 2. Before Fixing

- Record the reproduction: input size, screen, network state, device, and
  build variant.
- Frame-time or startup claims need a release-like build (R8 on) on a physical
  device. Debug or emulator numbers are diagnostic only.
- Detect the repo's existing convention first: search for an existing cache,
  paging source, image loader, player pool, request batching, or dispatcher
  provider, and reuse it before adding a new one.
- Before adding a dependency, check whether an existing dependency or a
  platform API already solves the problem.
- State whether the fix changes UX behavior, cache freshness, retry policy,
  privacy, or logging.

## 3. Rules

- No disk IO, network, large JSON parsing, bitmap decode, or file copy on the
  main thread. Move it behind the repository or data source with the repo's
  IO dispatcher, not into the composable or Activity.
- Long work runs in the owning scope: the ViewModel, a lifecycle-aware scope,
  or WorkManager. See
  [android-memory-lifecycle](../../android-memory-lifecycle/SKILL.md) and
  [android-background-work](../../android-background-work/SKILL.md).
- Latest-only work (search, filter, paging on scroll) cancels the previous
  request or drops stale results, for example with `collectLatest`,
  `flatMapLatest`, or a request token. A late response must not overwrite a
  newer one.
- Reuse heavy objects only within their lifecycle, and define the release
  condition together with the reuse.
- Design every cache with its freshness rule and its invalidation on logout,
  account switch, and permission change. A cache without invalidation serves
  one user's data to another.
- Image, video, and WebView optimizations must state their effect on quality,
  autoplay, accessibility, and data usage.
- Change one variable at a time: Baseline Profile, R8 rules, lazy key or
  content type, and state-read changes are measured separately.

## 4. Dependency And Build Cost

Before adding or upgrading a library, SDK, or build plugin, answer:

- Is this a standard, engine, protocol, or security area that local code should
  not own?
- Are binary size, startup, memory, and build-time costs justified?
- Does it add native code, telemetry, code generation, install hooks,
  permissions, or network side effects?
- Is the dependency change kept out of the feature diff so review stays clear?
- Is the lockfile or version-catalog change limited to the intended scope?

Do not add a dependency for a small formatter, a single helper, or a minor UI
convenience. Follow
[dependency-policy](../../../../../common/skills/dependency-policy/SKILL.md).

## 5. Do Not

- Do not change architecture, modules, or dependencies because it "should be
  faster".
- Do not add a cache without measurement; it creates stale and private-data
  risk.
- Do not add a prefetch window, Baseline Profile, or R8 keep rule without
  measurement. Do not add a broad keep rule for a whole library package.
- Do not call a repository or data source directly from UI to work around a
  performance problem.
- Do not move cost elsewhere with broad preloading at startup.
- Do not mix a performance change with a large refactor, module move, or
  dependency upgrade.

## 6. Verification

- Compile or typecheck when an API or shared boundary changed.
- Focused unit tests for mapper, cache, invalidation, cancellation, and
  stale-result behavior.
- Manual scenario for scroll, startup, media load, retry, offline, and large
  input as applicable.
- Macrobenchmark, Baseline Profile, trace, or profiler when the repo uses them
  or the path is critical.
- For a Perfetto root-cause claim, start from metrics and schema-backed SQL,
  identify the thread and process by `utid`/`upid`, and cite the metric or
  slice behind each claim.
- Without measurement, report the change as structural risk reduction, not a
  proven speedup.

## 7. Report

Report each change as hypothesis -> evidence: which bottleneck hypothesis the
change targets, which measurement or trace reduced or confirmed it, and what
remains unmeasured. Do not report only "what was made faster".
