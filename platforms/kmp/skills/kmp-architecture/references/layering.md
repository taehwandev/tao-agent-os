---
keyflow_id: sys_kmp_architecture_layering
status: review
type: ai-generated
---

# KMP Layering And Dependency Direction

Use before creating a KMP module or feature slice, before adding a Gradle
project dependency, or when deciding which layer owns a new runtime boundary:
a platform service, a long-running process, a window, or a data source.

Split out of `current-guidance.md`, which keeps the source-set and production
baseline rules every KMP change applies. Package trees inside each module are
in
[`package-layout.md`](../../kmp-module-structure/references/package-layout.md);
the design-system module contract is in
[`design-system.md`](../../kmp-compose-ui/references/design-system.md).

## Android Baseline Applies

A Compose Multiplatform app has the same layers as a Compose Android app. These
Android rules apply to KMP as-is; read them instead of re-deriving the shape:

- Architecture tracks (Local UI, MVVM, Clean Architecture, Reducer/MVI) and the
  "no ceremony" rule:
  [Android Feature Slice Baseline](../../../../android/skills/android-architecture/references/current-guidance.md#feature-slice-baseline).
- Effect sinks and delegates instead of broad base state holders:
  [Android Boundaries](../../../../android/skills/android-architecture/references/current-guidance.md#boundaries).
- Module tree as a growth ceiling, never a scaffold:
  [Android Structure Baseline](../../../../android/skills/android-architecture/references/structure-baseline.md).
- `api`/`impl`/`ui` split decision and forbidden edges:
  [Android module boundaries](../../../../android/skills/android-module-structure/references/module-boundaries.md).

The sections below state only what KMP changes: where source sets cut the
layers, how platform services cross them, and what desktop targets add.

## Layer Map

```text
app target (composition root)
  -> feature presentation (state holder, UI state, screens)
     -> domain (optional: pure policy shared by several features)
        -> data contracts (repository ports, stable entities)
data implementation -> data contracts, local/remote sources, platform adapters
platform adapters   -> target SDKs, process, file system, native interop
model               -> nothing but Kotlin stdlib and serialization annotations
design system       -> Compose runtime/foundation/material only
```

| Layer | Typical module | Owns | Must not import |
| --- | --- | --- | --- |
| App target | `:app` or `:app-<target>` | entry point, window or activity host, DI graph assembly, top-level navigation, feature registration | business rules, repository implementations written inline |
| Feature presentation | `:feature:<name>` | state holder, UI state/action/effect, screens, sections, feature components, UI mappers | data implementation, database entities, DTOs, process/file APIs, other features' implementation |
| Domain | `:core:domain` | pure policy and use cases reused across features | Compose, target SDKs, DTOs, database types, `java.io`/`java.nio` in `commonMain` |
| Data contracts | `:core:data` `api` package or `:core:data-api` | repository interfaces, stable entities, typed failures | storage engines, HTTP clients, SDK types |
| Data implementation | `:core:data` | repository implementations, DAOs/entities, DTO mapping, cache/sync coordination | Compose, feature state, window APIs |
| Platform capability | `:core:<capability>` | one platform service each: terminal/process host, file watcher, notifications, device bridge, browser engine | feature UI state, product copy, routes |
| Model | `:core:model` | pure value types shared by several modules | anything with I/O, Compose, or target APIs |
| Design system | `:core:designsystem` | theme, tokens, domain-free components | feature, data, domain, platform capability modules |

`core:domain` and `core:model` are optional, exactly as on Android. Do not add
pass-through use cases to fill `domain`, and do not keep the same concept in
both `model` and `domain`. When both exist, `model` holds shared value types and
`domain` holds policy and ports; a repository interface lives in one of them,
not split between them by accident.

## Composition Root

The app target is the only module that may see every implementation:

- It assembles the dependency graph (Koin, Metro, kotlin-inject, or manual
  construction) and passes contracts into feature entry composables.
- Feature modules expose an entry composable plus a binding/factory
  declaration; they do not start a global graph, read process environment, or
  construct data implementations.
- Default parameter values must not hide implementation choices. A
  dependencies holder such as `AppDependencies(repo: Repo = FileRepo())`
  silently makes every caller depend on the data implementation and defeats
  test substitution. Bind implementations in the graph; keep constructor
  parameters required.
- When the repo adopts a DI framework, assemble every implementation through it.
  A half-migrated root where some services come from the graph and others from
  hand-built data classes has two composition roots.
- The app module stays thin. A screen, policy, or repository that lives in the
  app target because "only the app uses it" is a feature or data owner in the
  wrong module. Typical leaks: notification policy, a full settings or catalog
  screen, git/file scanners, and process launchers in the app's desktop source
  set.

## Platform Service Boundary

Choose the boundary by contract size and test pressure:

| Need | Boundary |
| --- | --- |
| Pure value or formatting that differs by target (locale number format, path separator) | small `expect fun` / `expect class` in the owning module |
| Service with state, lifecycle, or fakes in tests (process, terminal, file watcher, device bridge, database builder) | interface in a contract package, implementation in the target source set or a `:core:<capability>` module, bound at the composition root |
| Capability some targets lack | capability object or typed `Unsupported` result in the contract |
| Composable that hosts a native view (browser, terminal widget, video surface) | `expect` composable in the module that owns the surface, `actual` per target; the native resource stays behind a capability interface |

Rules:

- A single-target project (desktop only) still keeps `commonMain` free of JVM,
  AWT/Swing, and process APIs when other targets are planned. When no other
  target is planned, say so in the module note; do not add `expect`/`actual`
  pairs that have exactly one `actual` only to look multiplatform.
- `expect`/`actual` functions that start, stop, or submit to a long-running
  resource (`stopSession()`, `sendInput()`) are a service hidden as free
  functions. Replace them with an injected interface that owns the resource.
- Platform capability modules live under `core/`, not `feature/`. A module
  whose content is device bridges, command builders, output parsers, and
  native frame decoding is a platform capability even when one feature is its
  only caller; name it by the capability.

## Desktop Target Concerns

Desktop adds runtime owners that mobile apps rarely have. Assign each to a
layer before writing code:

- Windows: the app target owns window creation, multi-window state, placement
  persistence, menu bar, tray, and global shortcuts. Feature screens receive
  window size class or callbacks, never a `Window`/`FrameWindowScope`.
- Detached or floating panes: the design system may own a domain-free pane or
  popup host primitive (in its desktop source set); which content detaches and
  when is feature policy.
- Long-running processes (terminal sessions, language servers, build or device
  processes, file watchers): a `:core:<capability>` or data owner starts,
  supervises, and releases them with cancellation, timeout, and app-quit
  cleanup. Feature state holders observe a `Flow` and send commands through a
  contract; they never hold a `Process`, PTY, or socket.
- Process output parsing (git porcelain, device lists, tool status) belongs in
  the data or capability layer that runs the process, with parser tests there,
  not in feature presentation.
- File system access, user-chosen roots, and path canonicalization stay in data
  or platform adapters; feature state carries typed identifiers or display
  strings, not `File`/`Path`.
- Packaging, signing, notarization, and bundled native helpers are build
  concerns of the app target or the capability module that ships the helper.

## Feature-To-Feature Dependencies

A feature depending on another feature's implementation is forbidden on Android
and in KMP alike. When one feature embeds another feature's surface (a
dashboard showing an embedded console or media pane):

1. Prefer composition at the app target: the host passes the embedded
   surface as a slot (`@Composable () -> Unit`) or an entry contract.
2. If the host feature must name the embedded feature, depend on that feature's
   `api` contract module, never its implementation.
3. If the embedded code is really a platform capability, move it to
   `:core:<capability>` and let both features depend on the contract.

## Do Not

- Declare a Gradle dependency the module's code does not import. An unused
  `implementation(project(":core:data"))` in a feature is a dependency edge
  reviewers will trust and future code will use.
- Let feature presentation import data implementation packages, DAOs,
  entities, or process wrappers, even when Gradle allows it.
- Put a full screen, policy, or data adapter in the app target to avoid
  creating a feature or data owner.
- Put platform capability code (process, device, browser engine) in a
  `feature/` module.
- Leave the architecture document's dependency rule and the Gradle files
  disagreeing; fix one of them in the same change.

## Stop If

- A new dependency edge points from `core` to `feature`, from `designsystem` to
  anything but Compose and resources, or from one feature to another feature's
  implementation.
- A long-running resource has no named owner, release path, or app-quit
  cleanup.
- The change needs a new layer (domain, data contract module, capability
  module) and no caller or test that needs it can be named.

## Review Checklist

- Does every module's Gradle dependency list match the layer map, and does
  each declared project dependency have at least one import?
- Is the app target the only module assembling implementations?
- Are feature-to-feature edges absent or limited to `api` contracts?
- Is every process, window, watcher, and native handle owned by app, data, or a
  capability module, with cleanup?
- Are single-`actual` `expect` declarations justified by a planned target?

## Verification

Run these with the repo's module paths and package root:

1. Print the declared edges per module:
   `./gradlew :feature:<name>:dependencies --configuration <target>CompileClasspath`
   or read the `dependencies {}` blocks of every changed `build.gradle.kts`.
2. Search for forbidden imports from presentation:
   `rg "^import .*\.core\.data\." feature/` and
   `rg -P "^import .*\.feature\.(?!<own>\.)" feature/<name>` — compare the
   hits against the declared edges.
3. Search for declared-but-unused edges: for each `project(":x:y")` in a
   module, confirm at least one `import <root>.x.y.` in that module.
4. Search `commonMain` for target APIs:
   `rg "^import (java\.io|java\.nio|java\.awt|javax\.swing|android\.)" --glob "**/commonMain/**"`.
5. Compile every affected target and run the capability module's lifecycle
   tests when an owner of a long-running resource changed.

A clean result is a search result. Report the commands run and the edges
added or removed.
