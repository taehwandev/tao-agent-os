---
keyflow_id: sys_kmp_module_structure
status: review
type: human-reviewed-needed
---

# KMP Module Structure

Use when deciding Kotlin Multiplatform shared modules, source sets, Gradle
module boundaries, umbrella frameworks, `expect`/`actual` placement, or package
layout.

This card follows current Kotlin Multiplatform guidance: start simple, use the
default hierarchy template when it fits, split shared code as it grows, and make
iOS framework consumption an explicit architecture decision.

References:

- Hierarchical project structure:
  `https://kotlinlang.org/docs/multiplatform/multiplatform-hierarchy.html`
- Project configuration:
  `https://kotlinlang.org/docs/multiplatform/multiplatform-project-configuration.html`
- Advanced project structure:
  `https://kotlinlang.org/docs/multiplatform/multiplatform-advanced-project-structure.html`
- Kotlin type aliases:
  `https://kotlinlang.org/docs/type-aliases.html`
- Swift export:
  `https://kotlinlang.org/docs/native-swift-export.html`

## Default Rule

Start with the smallest KMP boundary that works:

```text
package-private/internal code -> feature package -> single shared module
-> feature shared modules -> umbrella module/framework -> published library
```

A single shared module is often the right starting point. Split only when build
scale, source-set ownership, feature ownership, iOS framework shape, or
dependency leakage creates real pressure.

## File And Class Split

Apply `../../common/skills/code-structure-ownership/SKILL.md` in every source set. KMP source
files should default to one primary public or internal top-level class,
interface, object, state holder, use case, repository, adapter, mapper, fixture,
or assertion owner per file.

Split common and target source files before adding behavior when separate
owners appear, such as shared state, route contract, repository contract,
repository implementation, DTO/entity mapping, `expect` contract, `actual`
implementation, platform adapter, fake, fixture, and assertion DSL.

Review must fail when a KMP runtime file keeps multiple independently importable
owners in one file: shared classes, objects, interfaces, use cases,
repositories, state holders, DTOs, mappers, `expect`/`actual` adapters, fakes,
fixtures, or assertion helpers.

Do not:

- Keep shared product policy, target adapter code, Compose UI, DTOs, mappers,
  and repository implementation in one `commonMain` file.
- Put multiple importable Kotlin classes or objects in one file unless they are
  a small sealed/value family with one stable contract.
- Introduce Kotlin `typealias` in shared or target source sets. In Kotlin 2.x,
  aliases can be nested and exported to Swift, but they still do not create new
  types and nested aliases are not supported for KMP `expect`/`actual`
  declarations. Prefer named value classes, interfaces/fun interfaces, data
  classes, or explicit types so domain, route, callback, and platform contracts
  stay reviewable.
- Hide target-specific behavior in nested declarations inside a shared owner.
- Split modules to compensate for files that should first be split by owner.

## Module Families

Use repo-local names first. KMP projects commonly separate these families:

| Family | Owns | Must Not Own |
| --- | --- | --- |
| Target apps | Android app, iOS app, desktop/web shell, app lifecycle, platform navigation host, DI assembly. | Shared business rules or repository implementation details duplicated per target. |
| Shared umbrella module | iOS-exported framework surface, dependency aggregation, shared DI entrypoint, stable app-facing API. | Feature implementation details that do not need iOS export. |
| Shared feature module | Feature state owners, use cases, repositories used by that feature, shared UI when Compose Multiplatform is used. | Platform-only APIs outside source-set adapters. |
| Shared core/domain module | Pure models, policies, result/error types, clocks/dispatchers contracts, reusable use cases. | Compose UI, Android/iOS framework types, database rows, network DTOs. |
| Shared data module | Repository contracts, repository implementations, cache/network coordination, DTO/entity mapping. | Target UI state or platform permission prompts. |
| Platform adapter module/source set | Android/iOS/desktop/web implementations, file/permission/secure storage/native interop adapters. | Silent no-op behavior or shared product policy. |
| Design-system module (`core:designsystem`) | Theme, semantic tokens, domain-free components, icons, previews; target source sets for pointer, popup, and font differences. | Feature, data, domain, or platform capability dependencies; product composites, copy, language settings. See [`design-system.md`](../../kmp-compose-ui/references/design-system.md). |
| Shared product UI module (`core:ui`, optional) | Domain-aware UI patterns reused by several features, built on the design system. | Repository calls, routes, feature state; dependency from the design system back to it. |
| Platform capability module (`core:<capability>`) | One platform service such as process/terminal host, device bridge, file watcher, browser engine, with its contract, lifecycle, and parsers. | Feature UI state, product copy; living under `feature/` because one feature calls it. |
| Build logic/testing | Convention plugins, target setup, fixtures, fake adapters, test utilities. | Runtime behavior hidden from production owners. |

## Build Logic And Version Catalog

Use Gradle convention plugins and a version catalog to keep KMP/CMP modules
consistent when two or more modules repeat the same setup.

- Put target setup, Kotlin/Android/Compose compiler options, shared test
  dependencies, database/codegen wiring, coverage, resource prefixes, and build
  config plugin setup in build logic when repetition is real.
- Keep product behavior, routes, DI graph membership, signing values, API keys,
  flavor policy, and provider-specific secrets out of convention plugins.
- Version catalog entries should use repo-owned plugin aliases, dependency
  bundles, and project config keys. Do not copy template package ids,
  application ids, plugin ids, namespaces, or version values without checking
  the target repo.
- Treat build-time constants as runtime configuration. Public app ids and
  environment URLs can be injected through the repo's config path; private
  credentials, signing material, service-role keys, and refresh tokens must not
  be generated into shared source.
- Use Android resource prefixes or equivalent naming rules for modules with
  Android resources so feature resources do not collide after aggregation.

## Source Set Ownership

Use the default hierarchy template unless the project has a documented reason to
configure manual `dependsOn` edges.

```text
commonMain      target-neutral models, state, use cases, repository contracts
commonTest      shared state, mapper, policy, and repository contract tests
androidMain     Android adapters, lifecycle, resources, permissions
iosMain         Apple adapters, native interop, platform services
desktopMain     window, file, process, tray/menu, shortcut adapters
wasmJsMain/jsMain browser APIs and web-specific adapters
```

Rules:

- A source set may depend only on APIs available to every target it compiles to.
- Put iOS-only dependencies in `iosMain`, Android-only dependencies in
  `androidMain`, and browser-only APIs in web source sets.
- Avoid manual intermediate source sets until the default hierarchy cannot
  express the target sharing shape.
- Do not use `expect`/`actual` for large services. Prefer injected interfaces
  when the behavior needs fakes, multiple implementations, or test control.

## Split Decision

Keep one shared module when:

- the shared code is small enough to navigate and compile
- all target apps consume the same shared surface
- source-set dependencies are simple
- iOS can consume one generated framework without broad API noise
- the module boundary is still changing quickly

Split into shared feature modules when:

- feature owners need independent review and build boundaries
- Android or JVM consumers need only some shared features
- dependencies differ meaningfully by feature
- tests, generated code, or resources are becoming hard to scope
- a feature can be developed or released independently

Add an umbrella module/framework when:

- the iOS app needs a single stable framework that aggregates multiple shared
  modules
- multiple KMP frameworks would duplicate dependencies or complicate Swift
  integration
- the exported Swift surface needs curation and compatibility review

Publish modules separately only when versioning, ownership, and migration notes
are part of the workflow.

## Kotlin 2.x Apple Surface Review

Kotlin 2.x Apple interop is a version-sensitive surface. Before changing an
iOS-exported KMP API, check the repo's Kotlin Gradle plugin version and the
current Kotlin docs for Swift export, Swift package dependencies, generated
module shape, and current limitations.

Rules:

- Treat Swift export as a moving interop surface unless the repo pins and
  verifies the exact Kotlin version. As of Kotlin 2.4.0, Swift export is Alpha.
- Do not create Kotlin `typealias` only because Swift export can preserve it.
  If a Swift-facing concept needs identity, validation, or compatibility, model
  it as a named Kotlin value class, data class, interface, or explicit exported
  type.
- When the exported Swift surface changes, verify the generated Swift modules,
  package names, nullability, async/Flow mappings, and iOS framework or package
  integration in the Apple target.

## Feature Module Shape

Use the repo's names first, but production KMP features usually need these
owners once data, auth, navigation, or offline behavior appears:

```text
feature/<name>/domain        models, repository/service contracts, policies
feature/<name>/data          repository implementations, DTOs, mappers, sync
feature/<name>/database      cache/database entities, DAOs, migrations
feature/<name>/presentation  state holder/ViewModel, UiState, actions, effects, screens
```

Rules:

- Keep `domain` pure Kotlin and framework-light. It owns contracts and product
  policies, not network DTOs, database rows, Compose UI, or target SDK types.
- Keep `data` internal by default. It owns clients, DTO mapping, token/session
  coordination, network/cache merging, and repository implementations.
- Keep `database` optional and scoped to features that really persist local
  state. It owns schema, entities, DAOs, migrations, and schema export paths.
- Keep `presentation` responsible for state, user actions, effects, route
  callbacks, and screens. It depends on domain contracts and UI/design modules,
  not data implementations.
- Register DI modules and navigation destinations at the app or composition
  root. Feature modules may expose route contracts and DI module factories, but
  they should not assemble the whole app graph.
- Use type-safe route data for navigation arguments when the framework supports
  it. Route contracts belong in the smallest module callers need; screen
  implementations stay behind the presentation or feature implementation owner.

## Dependency Direction

Keep shared dependencies predictable:

```text
target app
  -> umbrella/shared feature modules
umbrella
  -> selected shared feature/core/data modules
shared feature
  -> core/domain, data contracts, platform adapter contracts, compose/design
data implementation
  -> data contracts, network/cache/local adapters, mappers
platform source sets
  -> target SDKs and actual adapter implementations
core/domain
  -> pure Kotlin contracts and policies only
```

Forbidden edges:

- `commonMain -> androidMain/iosMain/desktopMain/jsMain`
- shared core/domain -> Compose UI, Android, UIKit, AppKit, browser, DTO, or
  database-specific types
- platform adapters -> feature UI state unless that adapter is feature-local
- feature module -> another feature implementation when a contract can express
  the dependency
- actual implementation that silently succeeds when the target is unsupported
- presentation -> data implementation, database entities, raw network DTOs, or
  generated client models
- build logic -> product routes, DI graph membership, signing secrets, or
  environment-specific private config
- debug tooling dependency -> release runtime when a no-op or disabled variant
  is required
- design system -> feature, data, domain, or platform capability modules
- feature -> data implementation module, even when no file imports it yet; a
  declared edge is an invitation

Layer ownership, the composition root, and the Gradle/import verification
commands are in
[`layering.md`](../../kmp-architecture/references/layering.md).

## Package Layout

MUST read [`package-layout.md`](package-layout.md) before adding a package,
moving files between packages, or adding files to a module whose root package
already mixes roles. It owns the default package trees per module family
(feature, data, domain/model, design system, platform capability, app target),
the rule that every source set shares one package tree with `actual` beside
`expect`, and the root-package audit triggers.

Short form: a module's root package holds only its entry surface; a large
feature splits by flow, then by role; a data module splits by capability, then
by role (`repository/`, `local/`, `remote/`, `mapper/`).

## Test And Coverage Modules

KMP test support is a boundary, not a dump folder.

- Put shared fakes, fixtures, deterministic dispatchers, fake clocks, and
  contract tests in `commonTest` or a dedicated test-support/assertions module
  only when multiple modules need them.
- Tests for state holders, repositories, mappers, retry handlers, and typed
  errors should run without booting Android, iOS, desktop, DI, or network
  shells.
- Use coverage tooling only for modules where the metric is meaningful. Exclude
  generated code, DI modules, serialization/generated implementations, and
  design-system theme glue according to repo policy.
- Do not let test-support modules depend on production implementation modules by
  default. If a fake needs the implementation, the contract is probably too
  broad or the test belongs in the implementation module.

## Migration Strategy

When modernizing an old KMP shared module:

1. Record current targets, source sets, manual `dependsOn` edges, exported
   frameworks, and app consumers.
2. Move target-only imports out of `commonMain` before splitting modules.
3. Prefer the default hierarchy template; keep manual source sets only when the
   target sharing shape requires them.
4. Extract stable contracts and tests before moving implementation.
5. Add an umbrella module before exposing several shared modules to iOS.
6. Compile every affected target or state the target that could not be checked.

## Review Checklist

- Is the split driven by target sharing, feature ownership, dependency leakage,
  build scale, or iOS framework shape?
- Does `commonMain` compile without accidental target-only APIs?
- Are source-set dependencies inherited intentionally instead of duplicated?
- Are `expect`/`actual` boundaries small and contract-compatible?
- Does iOS consume one curated umbrella framework when multiple shared modules
  would duplicate dependencies?
- Are platform unsupported states explicit in shared state or capability models?
- Are `commonTest` and at least one target-specific check covering the new
  boundary?
- Does every declared project dependency have an import, and do the Gradle
  edges match the layer map in
  [`layering.md`](../../kmp-architecture/references/layering.md)?
- Does each touched module's root package hold only its entry surface, or is
  the audit result from [`package-layout.md`](package-layout.md) recorded?
- Does the design-system module stay free of feature, data, domain, and
  platform capability dependencies?
