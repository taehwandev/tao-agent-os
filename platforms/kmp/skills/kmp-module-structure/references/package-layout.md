---
keyflow_id: sys_kmp_package_layout
status: review
type: ai-generated
---

# KMP Package Layout Inside Modules

Use when adding files to a KMP module, creating or moving a package, auditing a
module whose root package keeps growing, or deciding where `expect`/`actual`
declarations live.

Module families and the split decision stay in
[`current-guidance.md`](current-guidance.md). Layer ownership and dependency
direction are in
[`layering.md`](../../kmp-architecture/references/layering.md).

## Android Rules That Apply As-Is

- The three-step gate (flow root, candidate classification, audit and
  collapse), the flow-internal owner taxonomy, and the boundary promotion
  ladder:
  [Android feature package structure](../../../../android/skills/android-module-structure/references/feature-package-structure.md).
- Package boundary note (owner, allowed imports, forbidden imports, callers,
  verification):
  [structure stops](../../../../../common/skills/code-structure-ownership/references/structure-stops.md#package-boundary-note).
- One primary owner per file:
  [`current-guidance.md`](current-guidance.md#file-and-class-split).

Those rules forbid type-named packages created only because a type exists. This
card adds the opposite failure, which is the common one in KMP code: every file
of a module left in its root package after the module has grown several
independent owners.

## Source Sets Share One Package Tree

A package is a logical owner; a source set is a target slice of that owner.

```text
src/commonMain/kotlin/com/example/feature/orders/ui/OrdersScreen.kt
src/desktopMain/kotlin/com/example/feature/orders/ui/OrdersWindowMenu.kt
src/commonTest/kotlin/com/example/feature/orders/OrdersReducerTest.kt
```

- Mirror the same package path in every source set. Do not invent
  `desktop/`, `jvm/`, or `platform/` packages whose only meaning is "this file is
  in a target source set"; the source set already says that.
- Put an `actual` in the same package as its `expect`, with the target suffix
  file name the repo uses (`Clipboard.desktop.kt`, `Clipboard.android.kt`).
- Put target-only owners that have no `expect` (a window menu, an AWT bridge, a
  process supervisor) in the package of the owner they serve, in the target
  source set. Use a `platform/` package only for adapter contracts in
  `commonMain` and their implementations, when the module has several of them.
- Tests mirror the production package of their subject.

## Root Package Audit

A module's root package should hold only its entry surface: the public entry
composable, the DI/binding declaration, and the small contract callers import.
Everything else belongs to a role package once the module has more than one
role.

Run the audit when any of these is true (counts are audit triggers, not split
commands; the decision still comes from roles):

- the root package of one source set holds more than about 20 files
- the root package mixes three or more of these roles: screen/section
  composables, state owners of unrelated flows, UI mappers, repositories or
  data sources, parsers, platform adapters, policy, localized strings
- a subpackage name repeats a file-name prefix shared by most root files
  (`Order*`, `Invoice*`, `Profile*`), which means a flow owner is hiding in the
  root
- reviewers have to open files to learn which ones are UI and which are data

Audit result: group by owner role or flow, then collapse any package that ends
up with one file and no distinct import rule.

## Default Trees By Module Family

These are fallback shapes for a repo without its own convention. Create a
package only when it will hold an owner; do not create empty packages. Each
package below is a role with its own import rule (`ui` imports Compose and the
design system, the flow root's state owner does not import Compose UI, `di`
may import implementations), which is what separates it from the type-named
packages the Android gate rejects.

### Feature module

```text
com/example/feature/<name>/
  <Name>Entry.kt            public entry composable the app target calls
  <Name>StateHolder.kt      state owner; UiState, Action, Effect stay beside it
  di/                       binding/factory declaration for the composition root
  navigation/               route contract or destination binding, if any
  ui/                       screen and content composables
  ui/section/               screen sections with distinct responsibility
  ui/components/<role>/     feature components shared by 2+ files (inputs,
                            lists, feedback, dialogs, ...)
  mapper/                   domain/data -> UI model mapping, when it is a test target
  policy/                   pure product rules, when they are a test target
  <flow>/                   for a large feature: one package per user flow; the
                            flow root holds its state owner and UDF types, and
                            the flow gets its own ui/ as needed
  preview/                  shared preview fixtures, only when reused
  strings/ or i18n/         feature copy, split per language or per flow
```

UI state, actions, and effects stay at the flow root next to their state
owner, as in the Android owner taxonomy; do not create a `state/` or
`contract/` package only to collect them. A large feature module splits by flow
first (`<flow>/`, `<flow>/ui/`), and by role inside the flow. A flow package that itself grows past the audit
triggers gets the same treatment. When the number of flows keeps growing, the
feature is a candidate for several feature modules; see the split decision in
[`current-guidance.md`](current-guidance.md#split-decision).

Localized string tables are content, not code owners. Keep them per language
and per flow (`strings/orders/OrdersStringsEn.kt`) or in the Compose
Multiplatform resources directory, not as one package holding every string
class of the feature.

### Data module

```text
com/example/core/data/
  repository/               repository implementations (one per capability)
  local/                    database, DAO, entity, migration, settings file
    <store>/                one package per database or store when several exist
  remote/                   HTTP/WebSocket clients and DTOs
  process/ or source/       process- or file-backed sources and their parsers
  mapper/                   entity/DTO <-> model mapping
  di/                       implementation bindings
```

Split large data modules by capability first (`account/`, `catalog/`,
`settings/`), then by role inside each capability. A data root package that
holds DAOs, entities, migrations, database classes, and repositories side by
side is the data equivalent of a flat feature.

### Domain and model modules

```text
com/example/core/domain/
  <capability>/             repository ports, use cases, policies per capability
com/example/core/model/
  <capability>/             pure value types per capability
```

Group by capability (`account`, `catalog`, `billing`, `settings`), never by kind
(`models/`, `repositories/`, `usecases/`). Keep a type in either `domain` or
`model`, not mirrored in both.

### Design-system module

```text
com/example/core/designsystem/
  theme/                    Theme entry, CompositionLocals, theme assembly
  tokens/                   color, typography, spacing, shape, elevation, motion
  components/<group>/       buttons, inputs, feedback, navigation, layout, data
  icons/                    icon set wrapper
  preview/                  component catalog and preview fixtures
```

These names match the Android design-system layout. The full contract is in
[`design-system.md`](../../kmp-compose-ui/references/design-system.md). A
`components/` package with dozens of files and no groups is a flat package.

### Platform capability module

```text
com/example/core/<capability>/
  <Capability>.kt           contract (interface, state, typed failure)
  model/                    capability values, when shared by several files
  host/ or engine/          target implementation and resource ownership
  parse/                    output or protocol parsers with their own tests
```

### App target

```text
com/example/app/
  Main.kt / App.kt          entry point and root composable
  di/                       dependency graph assembly
  navigation/               top-level destinations and feature registration
  window/                   window, menu bar, tray, shortcuts (desktop)
  shell/                    app chrome that is not a feature (frame, rail, status)
```

An app target package that contains screens, policies, scanners, or file
operations is holding feature or data owners; move them out (see
[`layering.md`](../../kmp-architecture/references/layering.md#composition-root)).

## Do Not

- Leave a module's root package as the default home for every new file.
- Add a role package without moving the existing files of that role into it.
  A half-applied layout (some screens in `ui/`, most in the root) is worse than
  either shape.
- Create `common/`, `shared/`, `utils/`, or `misc/` packages inside a module.
- Separate `expect` and `actual` into different package paths.
- Put localized strings for every flow in one package or one file.
- Split a package into one-file subpackages to satisfy a count.

## Stop If

- You cannot classify the files of the package into owner roles; settle the
  taxonomy first.
- The move would change public API or package names consumed outside the
  module without a migration plan
  ([split and migration](../../../../android/skills/android-module-structure/references/split-and-migration.md)
  applies as-is).
- A role package would contain owners with different allowed imports
  (for example UI and data parsers); split by role first.

## Review Checklist

- Does the root package of each source set hold only the entry surface, or has
  the audit result been recorded?
- Do `commonMain` and target source sets use the same package paths?
- Is each `actual` next to its `expect`?
- Are large features split by flow, then by role?
- Are data modules split by capability, then by role?
- Are string tables grouped per flow or in resources?

## Verification

- Count files per package per source set, for example
  `git ls-files '<module>/src/*/kotlin/**/*.kt' | xargs -n1 dirname | sort | uniq -c | sort -rn | head`,
  and audit any package over the trigger.
- Compile every affected target after a move; package moves break `internal`
  visibility and `expect`/`actual` matching first.
- Search for stale imports of moved packages across the repo.
- Report the audit result: packages created, files moved, packages collapsed.
