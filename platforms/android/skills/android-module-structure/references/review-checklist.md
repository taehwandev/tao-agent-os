---
keyflow_id: sys_android_module_review_checklist
status: review
type: human-reviewed-needed
---

# Android Module Structure Review

Use when reviewing an Android package, module, or dependency change
before approval or commit.

## Review Checklist

- Is this package/module the lowest boundary that protects the real owner?
- Does each `api` module have at least one caller that should avoid the
  implementation dependency?
- Does `api` own the destination type, arguments, deep link, result, navigate
  action, and stable ports without importing either UI or platform
  implementation?
- Can a module that only navigates to the feature compile against `api` alone,
  with no dependency on `impl` or `ui`?
- Does `impl` own the complete feature: holder composable, ViewModel, state,
  stateless content, mapping, entry binding, previews, and focused UI/ViewModel
  tests?
- If a `ui` module exists, is there a named consumer outside `impl` that renders
  the surface, and can that consumer compile, render, preview, and test through
  `api + ui` without importing `impl`?
- Does a `Route` name mean exactly one thing in this repo — the destination, not
  also the holder composable?
- Do dependencies point `impl -> api` (plus `impl -> ui` when extracted) and
  `ui -> api`, without any `api -> impl`, `api -> ui`, or `ui -> impl` edge?
- Were the forbidden-import and Gradle-edge searches actually run, and does the
  report list the edges added and removed?
- Does any DI interface exist only to hide a wrong edge (for example `ui` or
  `core` reaching `impl` behavior through a binding)? That is still a wrong
  edge.
- Is there an interface with a single implementation and a single `@Binds`
  that only hides one concrete composable from one caller? Reject it; extract
  the feature `ui` and call the composable directly.
- For a move: did the host module lose the moved ownership, and does every
  host-side bridge record what still has to move and its removal condition? A
  net-grown host is a partial migration.
- Is a feature-specific reusable surface kept in the feature module while only
  domain-free, broadly shared primitives move to the design system?
- Does each `assertions` module expose role-sized fixtures, fakes, recorders,
  builders, and assertion subjects instead of one catch-all testing file?
- Can tests import the assertion helper they need without depending on
  production `impl` modules or unrelated platform/runtime helpers?
- Are DTOs, SDK models, database rows, and Android framework objects kept out of
  stable feature/domain contracts?
- Can a feature implementation depend on repository APIs without importing
  repository internals?
- Are design-system modules free of product routes, analytics, permissions, and
  repository calls?
- Can a new feature import only the capability it needs, or does it have to
  depend on a broad `core-app`, `common`, `base`, `runtime`, or "feedback"
  bucket?
- Does each new module have a named caller, or was it created to fill a
  template shape?
- Is any reusable `BaseActivity` limited to Activity template work instead of
  owning product routing, DI, repositories, ViewModel creation, or screen state?
- Did the change update convention plugins instead of duplicating Gradle setup
  across modules, and does every remaining plugin, task, and configure helper
  have a real caller?
- Are previews, ViewModel tests, repository tests, or import-direction checks
  covering the new boundary?
