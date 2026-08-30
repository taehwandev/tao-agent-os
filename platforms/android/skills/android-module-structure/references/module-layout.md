---
keyflow_id: sys_android_module_layout
status: review
type: human-reviewed-needed
---

# Android Module And Package Layout

Use when choosing which module family owns new Android code, when
laying out packages inside a feature or repository module, or when
checking that dependencies still point in one direction.

## Module Families

Use repo-local names first. A large Android app commonly separates these module
families:

| Family | Owns | Must Not Own |
| --- | --- | --- |
| `app` | Application class, build types/flavors, app-level DI graph, startup, top-level navigation wiring. | Feature implementation, repository implementation details, shared UI primitives. |
| `build-logic` | Convention plugins, common Android/Kotlin/Compose/test settings, dependency bundles. | Product behavior or runtime code. |
| `core` | Pure Kotlin or implementation-neutral contracts such as models, domain interfaces, route contracts, network contracts, dispatchers, resource-provider contracts, and test-support contracts. | Android/Compose runtime, feature product policy, or screen-specific UI. |
| `core-ui` / `core-app` / `core-runtime` | Android/Compose app-runtime commonization such as design system, resources, permission helpers, ActivityRoute launch adapters, WebView runtime, notice or alert hosts, toast/dialog rendering, and app UI infrastructure. | Feature-specific copy, route policy, analytics policy, or repository calls. |
| `data` / `core-data` | Repository contracts, repository implementations, local/remote data sources, DTO mapping, DataStore/Room/cache ownership. | Compose UI, navigation decisions, screen state. |
| `domain` | Optional use cases and product policies reused across screens or risky enough to test independently. | Pass-through wrappers around one repository call. |
| `feature-api` | Navigation contracts, public entrypoints, route data, events, small caller-facing models. | Screens, ViewModels, repository implementations, DI bindings with heavy dependencies. |
| `feature-ui` | Independently runnable Compose feature: holder Route, screen ViewModel, UI state/actions/effects, stateless Screen, UI mappers, feature components, Compose navigation entry, previews, and UI/ViewModel tests. | Concrete Activities, manifests, Intent construction, Activity results, or dependencies on the feature platform implementation. |
| `feature-impl` | Optional Android platform entry: Activity, manifest, Intent/request/result mapping, Activity launch handler, SDK entry adapter, and platform DI. | A second copy of the feature ViewModel, Compose Route, Screen, or shared design primitives. |
| `feature-common` / `holder` | Reused product UI or workflow holders with a named owner and stable caller contract. | Dumping ground for unrelated screen fragments. |
| `dev` / `testing` / `assertions` | Dev-only screens, reusable fakes, recording adapters, fixture builders, assertion DSLs, and contract test helpers. | Production-only behavior that callers need at runtime, or dependencies on production implementation modules by default. |

## Core Is A Capability Namespace

Do not treat `core` as a promise that every module under it is pure Kotlin.
Treat it as a stable capability namespace whose Gradle plugin and dependencies
must match the capability it exports.

Choose the module type by import contract:

- Use pure Kotlin modules for platform-free value types, route keys, repository
  ports, domain rules, error models, fakes, fixtures, and assertion DSLs.
- Use Android library modules for contracts or adapters that need resources,
  `Context`, `ActivityResultRegistry`, system services, WebView, credentials,
  permissions, notifications, or Android SDK types.
- Use Compose-enabled Android library modules for reusable composables, state
  holders, app roots, notice hosts, design-system primitives, or lifecycle-aware
  Compose effects.
- Use names such as `kotlin-extensions`, `compose-extensions`, `runtime`,
  `base`, or `designsystem` only when the exported capability and forbidden
  imports are clear. Otherwise prefer a capability name such as `notice`,
  `router`, `permission`, `webview`, `activity`, or `resource`.

Review should stop when a module is called `core`, `common`, `shared`,
`extensions`, or `base` but callers cannot tell whether it is safe for pure
Kotlin, Android runtime, Compose runtime, tests, or app-shell code. Split the
module, rename it, or keep the helper local until the import surface is clear.

For a navigable Compose feature, use `feature-api + feature-ui`: `api` owns the
key and caller contract, while `ui` owns the complete screen-level Compose
feature. Add `feature-impl` only when Android needs an Activity or another
platform-specific entry around it. A local feature that has no cross-module
caller may still remain unsplit.

If the repo already uses convention plugins, apply the nearest plugin instead of
copying dependency blocks by hand. If no convention exists, update or add one
only when at least two modules will share the same setup.

## Dependency Direction

Keep dependencies acyclic and predictable:

```text
Compose host
  -> feature-api + feature-ui
Activity host
  -> feature-api + selected feature-impl
feature-ui
  -> own feature-api, design system, core utilities, repository-api, domain
feature-impl
  -> own feature-api + own feature-ui when it wraps Compose
feature-api
  -> small route/data contracts and stable core contracts only
repository implementation
  -> repository-api, network/local data sources, mappers, config
repository-api
  -> stable entities and repository interfaces only
core/designsystem
  -> platform primitives, resources, tokens, reusable UI contracts
```

When an Activity wraps a reusable Compose feature, add only this platform edge:

```text
feature-impl -> own feature-api + own feature-ui
Compose host -> feature-api + feature-ui
feature-ui -> own feature-api
feature-ui -> design system and stable core UI/value contracts
```

Forbidden edges:

- `feature-api -> feature-impl`
- `feature-api -> feature-ui`
- `feature-ui -> feature-impl`
- `repository-api -> repository implementation`
- `repository -> feature`
- `core/designsystem -> feature`
- `domain -> UI, Compose, Android framework UI types, DTO transport models`
- `app -> concrete repository internals` except app-level DI binding when the
  repo intentionally centralizes bindings there

## Feature Package Layout

Before applying a package template, choose the flow root from the owner and
dependency direction rather than from type names. Use the focused gate in
[`feature-package-structure.md`](feature-package-structure.md) to classify the
flow and audit the split; the layout below remains a vocabulary of possible
owners, not a required directory tree.

Inside a feature UI module, prefer packages that reveal behavior and dependency
direction:

```text
<feature>/
  <Feature>Route.kt          ViewModel/lifecycle/navigation/effect wiring
  <Feature>ViewModel.kt      screen state owner
  model/                     UiState, UiAction, UiEffect, UI display models
  compose/ or ui/            stateless screen composables
  compose/component/         feature-local components
  preview/                   shared preview providers only when reused across
                             multiple composable files
  convert/ or mapper/        domain/repository -> UI model mapping
  di/                        feature-local bindings
  navigation/                local graph or route registration when needed
```

For small screens, keeping `Route`, `Screen`, `UiState`, and preview support in
one package is fine. Use `preview/` only for shared deterministic states or
design-system-owned examples; one-off stateless UI preview placement follows
`../../android-compose-ui/references/current-guidance.md`.

Do not create one of these subpackages merely because a type has that name. A
new boundary needs a caller, owner, dependency, release, or test seam that can
be verified; otherwise keep the owners together and record the audit result.

When the Compose feature crosses a module boundary, keep its state holder and
rendering together in `ui`, then add `impl` only for an Activity or another
platform entry:

```text
feature/<name>/ui/src/main/.../<name>/
  <Name>Route.kt            lifecycle, ViewModel, effects, navigation callbacks
  <Name>ViewModel.kt        screen state and action owner
  <Name>Screen.kt           stateless rendering surface
  model/                    UiState, UiAction, UiEffect, UI display models
  mapper/                   domain/repository -> UI model mapping
  component/                feature-specific reusable components
  navigation/               Compose NavEntry or entry provider when used
  preview/                  previews for the screen surface

feature/<name>/impl/src/main/.../<name>/
  activity/                 Activity/Intent/result adapter when required
  di/                       platform-entry bindings
```

The `ui` module is standalone from `impl`, not from all dependencies. Its
ViewModel may depend on stable repository or domain ports, and a real host may
bind those ports. Preview and focused tests use fakes without importing the
Activity implementation.

## Repository Package Layout

Inside a repository implementation module, keep API contracts and transport
details separate:

```text
repository-<name>-api/
  <Name>Repository.kt        caller-facing interface
  model/                     stable entities returned to domain/UI

repository-<name>/
  <Name>RepositoryImpl.kt    source coordination and error normalization
  <Name>Api.kt               Retrofit or remote source contract
  local/                     Room/DataStore/file source if present
  model/                     request/response DTOs
  mapper/ or convert/        DTO/cache -> entity mapping
  di/                        implementation bindings
```

Repository entities should be stable for callers. DTOs, request bodies,
response wrappers, database rows, SDK models, and generated network models stay
inside implementation packages unless the repo explicitly treats them as public
contracts.

## Shared UI And Holder Modules

Create a shared UI, holder, or feature-common module only when it has a stable
caller contract and repeated use:

- Use design-system modules for domain-free primitives, tokens, typography,
  buttons, list rows, dialogs, sheets, and accessibility contracts.
- Put theme, semantic color/type/shape tokens, component defaults, app UI
  wrappers, and preview fixtures in the design-system module when they are
  reused across features.
- Use feature-common modules for product UI patterns shared by several feature
  owners.
- Use a feature `ui` module for a feature-specific Compose destination that a
  Compose host can navigate to and run without the optional Activity
  implementation. Keep a purely local screen in one unsplit feature module.
- Use holder modules for reusable workflow entrypoints or embedded surfaces that
  own their own state/effects and have a clear lifecycle.
- Keep analytics labels, permission policy, route decisions, and repository
  calls in the caller or holder state owner, not in a leaf component.
- Keep feature product cards, screen headers, fake data, route events, and
  domain-to-UI mapping in feature modules or feature-common modules, not in the
  design system.

If a shared module needs many feature flags, product-specific callbacks, or a
full screen `UiState`, keep the code feature-local instead.
