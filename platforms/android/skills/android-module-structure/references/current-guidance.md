---
keyflow_id: sys_android_module_structure
status: review
type: human-reviewed-needed
---

# Android Module Structure

Use when deciding Android Gradle modules, package layout, `api`/implementation
splits, feature ownership, build convention plugins, or where new code should
live.

This card follows current Android guidance: modularization is a tool for
maintainability, build isolation, visibility control, and replaceable
boundaries; it is not mandatory ceremony for every feature.

References:

- Android app modularization:
  `https://developer.android.com/topic/modularization`
- Android app architecture:
  `https://developer.android.com/topic/architecture`
- Android UI layer:
  `https://developer.android.com/topic/architecture/ui-layer`
- Compose compiler Gradle plugin setup:
  `https://developer.android.com/develop/ui/compose/setup-compose-dependencies-and-compiler`
- Hilt bindings, components, scopes, and Android entrypoints:
  `https://developer.android.com/training/dependency-injection/hilt-android`
- Dagger set/map multibindings:
  `https://dagger.dev/dev-guide/multibindings.html`
- Navigation 3 modularization:
  `https://developer.android.com/guide/navigation/navigation-3/modularize`

## Default Rule

Start with the smallest owner boundary that works:

```text
package/private file -> feature package -> feature module -> api/impl pair
-> api/impl/assertions trio -> shared core or core-app module
-> public SDK-like contract
```

Use a single package or module unless a real caller, dependency, build,
navigation, testing, or ownership boundary needs a split. Multi-module apps need
clear dependency direction; otherwise the extra modules only move complexity into
Gradle.

For a feature, treat `impl` (or an unsplit feature module serving the same role)
as the default owner of Compose UI. Add `api` only for a stable caller or
navigation contract, and add `ui` only when a named consumer outside `impl` must
reuse the concrete Compose surface. These are independent promotions, not three
modules that every feature must create. The canonical ownership and dependency
rules live in [`module-boundaries.md`](module-boundaries.md).

## File And Class Split

Apply
`../../../../../common/skills/code-structure-ownership/references/current-guidance.md`
before growing Android runtime files. Kotlin and Java source should default to
one primary public or internal top-level class, interface, object, composable
screen/state owner, repository, adapter, mapper, fake, or assertion subject per
file.
For stateless UI preview placement, apply the canonical Compose preview rule in
`../../android-compose-ui/references/current-guidance.md`; this document only
owns Android package and module boundaries.

Split files before adding behavior when a feature file contains separate owners
such as route contract, `NavEntry` mapping, screen rendering, ViewModel,
UiState, repository contract, repository implementation, DTO mapper, platform
adapter, fixture, recorder, and assertion DSL.

Review must fail when an Android runtime file keeps multiple independently
importable Kotlin/Java owners in one file: classes, objects, interfaces,
ViewModels, repositories, services, mappers, validators, DI bindings, platform
adapters, fakes, fixtures, or assertion subjects.

Do not:

- Put a ViewModel, screen, route key, repository, mapper, and DI binding in one
  file because they all belong to one feature.
- Keep multiple importable Kotlin/Java classes or objects in one file unless
  they are a small sealed/value family with one caller-facing contract.
- Introduce Kotlin `typealias` in Android runtime code. In Kotlin 2.x, aliases
  remain alternative names for existing types rather than new contracts. Prefer
  named value classes, interfaces/fun interfaces, data classes, or explicit
  types so domain, route, callback, and platform contracts stay reviewable.
- Use nested classes, companion objects, or extension files to hide unrelated
  UI, state, data, platform, or testing responsibilities.
- Create one-folder-per-type module structure without changing import rules;
  split files first, then packages or modules only when ownership demands it.


## Topic References

The rules below the always-applicable core live in focused siblings so a
route can select the boundary, layout, entry-contract, build, split, or
review material it actually needs. Each sibling is separately routable.

- [`module-boundaries.md`](module-boundaries.md) — Android Module Boundary Contracts.
- [`module-layout.md`](module-layout.md) — Android Module And Package Layout.
- [`compose-entry-contracts.md`](compose-entry-contracts.md) — Android Compose And Entry Contract Boundaries.
- [`di-build-logic.md`](di-build-logic.md) — Android DI And Build Convention Plugins.
- [`split-and-migration.md`](split-and-migration.md) — Android Split Decision And Migration.
- [`skill-source-coverage.md`](skill-source-coverage.md) — Android External Skill Source Surfaces.
- [`review-checklist.md`](review-checklist.md) — Android Module Structure Review.
- [`feature-package-structure.md`](feature-package-structure.md) — focused feature package gate.
