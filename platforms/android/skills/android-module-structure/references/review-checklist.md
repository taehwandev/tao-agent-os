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
- Is any reusable `BaseActivity` limited to Activity template work instead of
  owning product routing, DI, repositories, ViewModel creation, or screen state?
- Did the change update convention plugins instead of duplicating Gradle setup
  across modules?
- Are previews, ViewModel tests, repository tests, or import-direction checks
  covering the new boundary?
