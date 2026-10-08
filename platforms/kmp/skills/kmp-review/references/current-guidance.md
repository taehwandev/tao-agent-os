---
keyflow_id: sys_kmp_review
status: review
type: human-reviewed-needed
---

# KMP Review

Use when reviewing Kotlin Multiplatform, Compose Multiplatform, shared Kotlin
modules, source-set changes, platform actuals, or target app integration.

## Findings Priority

1. Cross-target behavior mismatch, unsupported target hidden as success, or data loss.
2. Security, credential, file, shell, permission, or native interop risk.
3. Shared source-set dependency leak or platform API import in common code.
4. Missing target build/test evidence.
5. UI/state ownership, cancellation, cleanup, or lifecycle bug.
6. Maintainability, naming, package layout, or duplicated adapters.

## Check

- Does the route use the target repo's local KMP/Gradle/module rules?
- Are module and source-set boundaries checked against
  `platforms/kmp/skills/kmp-module-structure/SKILL.md` when Gradle modules, umbrella frameworks, or package
  moves changed?
- Are source-set dependencies intentional and compileable for every affected target?
- Is shared code free of accidental Android, desktop, iOS, JVM-only, or native-only APIs?
- Do actual implementations satisfy the same contract or return typed unsupported failures?
- Are platform resources cleaned up on cancellation, failure, lifecycle teardown, and app quit?
- Are state, effects, repositories, and platform adapters owned by the right layer?
- Is verification run for every affected target, or is the skipped target and
  residual risk stated?
- Do presentation modules avoid data implementation, database entity, network
  DTO, generated client, and platform SDK imports?
- Are feature/domain/data/database/presentation splits justified by ownership,
  dependency leakage, source-set pressure, offline/sync behavior, or test
  boundaries rather than template ceremony?
- Are build logic and version catalog changes limited to shared build setup,
  with product routes, DI membership, secrets, signing values, and environment
  policy kept out?
- Does offline-first code use a durable local source of truth, explicit sync
  state, retry/backoff, migration, conflict handling, and logout/account-switch
  invalidation?
- Does auth/network code skip token refresh loops, clear cached tokens on
  logout, redact debug output, and map session expiry into typed state?
- Are debug-only tools disabled or replaced with no-op release variants?
- Are Compose screens split into root/state holder and stateless screen, with
  typed state/actions/effects and previews or visual checks for changed states?
- Are Flow, Channel, StateFlow, SharedFlow, callbacks, and suspend APIs tested
  with deterministic coroutine control when behavior changed?
- Are release checks covering serialization/minification rules, signing,
  framework export, package identifiers, config injection, and target smoke
  paths when release surfaces changed?
- Do Gradle project dependencies match the layer map in
  `../../kmp-architecture/references/layering.md`, with no unused declared
  edge, no feature-to-feature implementation edge, and no app-target screen,
  policy, or data adapter?
- Do touched packages pass the root-package audit in
  `../../kmp-module-structure/references/package-layout.md`?
- Does UI code consume the design system per
  `../../kmp-compose-ui/references/design-system.md`, without new hardcoded
  colors, repeated dimension literals, or private primitives?

## Do Not Approve When

- `commonMain` imports Android, JVM, iOS, desktop, native, Compose runtime, or
  generated platform APIs without an `expect`/`actual`, adapter, or source-set
  boundary.
- An `actual` implementation changes semantics, returns platform-specific
  success for unsupported behavior, or hides unsupported targets instead of
  typed failure.
- Presentation modules import database entities, network DTOs, generated
  clients, SDK types, platform APIs, or data implementation packages.
- Shared state, Flow, coroutine, callback, or native resource work lacks
  cancellation and lifecycle cleanup for every affected target.
- Gradle, version catalog, framework export, signing, package id, or release
  config changes are mixed with product behavior or lack affected-target
  verification.
- The design-system module gains a dependency on a feature, data, domain, or
  platform capability module.
- A long-running process, window, watcher, or native handle is owned by
  feature presentation instead of the app target, data, or a capability module.

## Output

Lead with concrete findings:

```text
Findings:
- [High] platforms/kmp/... - issue, impact, recommendation, verification
```

If no findings remain, say so and list target/test gaps that were not checked.
