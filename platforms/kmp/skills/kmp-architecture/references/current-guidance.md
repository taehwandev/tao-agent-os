---
keyflow_id: sys_kmp_architecture
status: review
type: human-reviewed-needed
---

# KMP Architecture

Use for Kotlin Multiplatform, Compose Multiplatform, shared Kotlin modules,
Gradle source sets, `expect`/`actual` boundaries, and shared mobile/desktop
application logic.

Also use:

- `platforms/kmp/skills/kmp-compose-ui/SKILL.md` for Compose Multiplatform UI.
- `platforms/kmp/skills/kmp-state-data/SKILL.md` for state, coroutines,
  repositories, persistence, and data flow.
- `platforms/kmp/skills/kmp-platform-integration/SKILL.md` for platform APIs,
  source sets, native interop, shell, files, clipboard, permissions, or
  background resources.
- `platforms/kmp/skills/kmp-module-structure/SKILL.md` for shared modules,
  source-set hierarchy, umbrella frameworks, and Gradle module splits.
- The matching Android, iOS, or application card for target-specific shells.

## Boundaries

```text
App Target -> Platform Shell -> Shared Presentation/UI -> Use Case
-> Repository -> Platform Adapter
```

The layers, architecture tracks, and effect-sink rules are the Android ones;
the KMP layer map, composition root, platform service boundary, and desktop
runtime owners are in [layering.md](layering.md).

Use source sets as ownership boundaries:

```text
commonMain    shared models, domain rules, state, pure services, shared UI
commonTest    shared behavior tests
androidMain   Android adapters, permissions, lifecycle, resources
iosMain       Apple adapters, native interop, platform services
desktopMain   desktop shell, files, process, window/system adapters
```

## Rules

- Keep `commonMain` free of target-only APIs unless the dependency explicitly
  supports every target used by the repo.
- Put platform behavior behind an injected interface or a small
  `expect`/`actual` boundary with the same contract on every target.
- Keep target entry points thin. They should wire platform services, DI,
  windows/activities/controllers, and lifecycle into shared presentation or use
  cases.
- Keep domain models free of Compose, Android, UIKit, AppKit, file-system,
  process, and credential APIs.
- Treat Gradle source-set dependencies as architecture decisions. A dependency
  that only works on one target should not leak into common source sets.
- Do not hide target gaps with silent no-op actual implementations. Return an
  explicit unsupported capability, typed failure, or disabled command state.
- Keep target-specific formatting, localization, permissions, filesystem paths,
  and resource lookup in target adapters or UI mapping layers.

## Production KMP Baseline

Use KMP to share behavior, not to hide target differences. For production app
work, make these decisions explicit before implementation:

- Composition root: target apps or the shared app module own dependency
  assembly, navigation graph assembly, platform entry points, and feature
  registration. Feature modules should not start global DI, own app lifecycle,
  or register unrelated routes.
- Dependency direction: presentation depends on domain contracts and design
  system; data implements domain contracts; database/cache stays behind data;
  app target wires implementations. Do not let presentation import data
  implementation, database entities, network DTOs, or platform SDK clients.
- State track: choose local state, ViewModel/state holder, reducer/MVI, or use
  case boundary based on async, navigation, offline, auth, sync, and test
  pressure. Do not add Clean Architecture layers only because a template uses
  them.
- Typed failures: map network, serialization, auth, local storage, permission,
  unsupported-target, and sync failures into shared failure types before they
  reach UI state.
- Runtime config: API origins, WebSocket endpoints, callback/deep-link hosts,
  and public client identifiers belong in the platform or build configuration
  path selected by the repo. Credential-bearing values stay out of source.
- Logging: use the repo's multiplatform logger or target logger abstraction.
  Do not use ad hoc `println` or debug logs for production diagnostics, and do
  not log tokens, auth headers, request bodies, file paths, or native handles.
- Release behavior: release builds must verify serialization or minification
  rules, signing, package identifiers, config injection, and target-specific
  smoke paths instead of relying only on debug builds.

## Refactor Signals

- `commonMain` imports Android, desktop, iOS, JVM-only, or native APIs without a
  deliberate source-set boundary.
- A target app entry point owns business rules instead of wiring shared
  components.
- Shared code branches on target names instead of using a capability or adapter.
- Actual implementations behave differently without the contract naming that
  difference.
- A shared module depends on platform UI or storage just to reach a convenience
  API.
- Feature presentation imports data/database/network implementation modules.
- Token refresh, local sync, or WebSocket reconnection is hidden inside UI code
  instead of a repository, client, or state owner.
- Release-only code paths such as minification, signing, packaging, or debug
  inspector no-op variants are not represented in verification.
- A Gradle file declares a project dependency the module never imports, or the
  repo's architecture document and Gradle edges disagree.
- The app target holds screens, policies, scanners, or process launchers that
  belong to a feature, data, or platform capability owner.
- A `feature/` module contains platform capability code (device bridges,
  process or browser engines) instead of UI for one feature.
- A module's root package holds most of its files across unrelated roles, or
  feature code bypasses the design system with raw colors, dimensions, or
  private primitives.

## Required References By Decision

Each reference below holds rules this file does not repeat. When the change
makes that decision, read the reference before editing.

- [layering.md](layering.md): before creating a module or feature slice,
  adding a Gradle project dependency, wiring the composition root, or placing a
  platform service, window, or long-running process.
- [package-layout.md](../../kmp-module-structure/references/package-layout.md):
  before adding a package, moving files between packages, or when a module's
  root package keeps growing.
- [design-system.md](../../kmp-compose-ui/references/design-system.md): before
  changing the design-system module, adding a token or shared component, or
  reviewing hardcoded colors, dimensions, or primitives in features.

## Verification

- Run the narrowest compile/test task for every affected target or state why a
  target cannot be checked.
- Add shared tests in `commonTest` for platform-neutral behavior.
- Add platform tests or smoke checks for actual implementations, permissions,
  files, shell/process behavior, lifecycle, and resource cleanup.
- Run repository/state-owner tests for offline cache, token refresh, retry,
  logout/session clear, WebSocket reconnect, and typed failure mapping when
  those paths changed.
- For release-sensitive changes, run or document the Android release artifact,
  iOS release build, desktop package, coverage, minification, and signing checks
  that apply to the repo.
- Review the final diff for accidental target-only imports in shared source
  sets and for no-op actuals that mask unsupported behavior.
