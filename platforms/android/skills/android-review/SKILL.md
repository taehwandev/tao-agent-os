---
keyflow_id: sys_platforms_android_android_review_md_skill
status: review
type: ai-generated
required_contract: core
---

# Android Review

Use when reviewing any Android app, Compose/ViewModel, permission, background,
or UI flow change.

## Read

The core below is the required review contract. Open
`references/current-guidance.md` only for an unresolved in-scope question:

- `## Lifecycle And Performance` for an owner/cleanup or performance claim.
- `## Review Checklist` for a state, module, design-system, security, SDK, or
  base-class host question.
- `## Completion Gate: External State And Persisted Data` for evidence options.
- `## Tools` and `## UI Test Focus` to pick or scope a check.
- `## Executable Action Boundary` when the check flags a ViewModel bypass.
- `## Structure Review Hook Evidence` when the hook reports a package/owner finding.

## Surface Procedures

First anchor to the requirement and size: apply the proportionality gate in
[llm-coding-discipline](../../../../common/skills/llm-coding-discipline/references/current-guidance.md)
and [change-size-policy](../../../../common/skills/change-size-policy/SKILL.md),
and write down the requirement every finding is measured against. Then run each
procedure whose surface is in the diff:

| Changed surface | Run |
| --- | --- |
| Resource, listener, effect, Flow collection, coroutine scope | [android-memory-lifecycle](../android-memory-lifecycle/SKILL.md) Steps |
| Main thread, IO, startup, cache, network, media, dependency | [runtime-performance.md](references/runtime-performance.md) |
| Composable performance, recomposition, lazy lists | [compose-performance.md](../android-compose-ui/references/compose-performance.md) |
| ViewModel, `UiState`, effects, repository boundary | [android-viewmodel-state](../android-viewmodel-state/SKILL.md) |
| Module, package, `api`/`impl`, build logic | [android-module-structure](../android-module-structure/SKILL.md) |
| Worker, foreground service, sync, upload | [android-background-work](../android-background-work/SKILL.md) |
| Manifest, intent, deep link, WebView, storage, credentials | [android-security](../android-security/SKILL.md) |
| Platform SDK named in the source trigger map | [external source coverage](../android-external-skill-source-coverage/SKILL.md) |

## Must

- Write each finding as Requirement, Risk (with file:line), Failure scenario,
  Fix direction. No failure scenario, no finding. Drop taste, speculative
  extensibility, and out-of-requirement refactors.
- Run android-memory-lifecycle Steps for every changed listener, receiver,
  launcher, effect, Flow collection, scope, WebView, player, Bitmap, stream, or
  foreground notification: owner plus cleanup on dispose, failure,
  cancellation, owner end. An ungated `LaunchedEffect` collect, production
  `GlobalScope`, or `runBlocking` is a finding unless that card's documented
  exception applies.
- Classify performance-affecting changes with runtime-performance; reject
  refactors, dependencies, or migrations sold as fixes without reproduction or
  measurement. Apply compose-performance for recomposition and lazy lists.
- Check state hoisting, ViewModel ownership, truthful `@Immutable`/`@Stable`,
  immutable collections, and no mutable/platform/repository objects in `UiState`.
- Check loading, empty, error, permission-denied, offline, process recreation,
  activity result, and navigation arguments; UI must not bypass repositories.
- Reject package/module splits without a boundary note (owner, allowed and
  forbidden imports, callers, verification); `api` exposes contracts only,
  `assertions` depends on `api`. Design-system/core never holds product policy.
- Apply compose-previews to changed renderable composables.
- No secrets or user data in logs. Apply android-security,
  android-background-work, and source-coverage when those surfaces change.
- For calls moved onto a base-class-hosted contract (notices, navigation
  dispatch), name each screen's base class and confirm it installs the host;
  one host serves several contracts, so check each. A missing host is a silent
  no-op that unit tests and static analysis miss.
- Send product actions to the ViewModel. A textual attestation cannot override
  an `agent-structure-check.py` failure; never silence one by renaming or moving
  a callback to a UI helper. Review callback → action → ViewModel → effect and
  test both action and effect; a navigation smoke test, check, or build pass
  alone does not prove the boundary or a migration.
- For hook structure findings, record `owner`, `allowed imports`, `forbidden
  imports`, `callers/tests`, `verification`; "no new boundary" alone is not
  evidence. Do not merge into a file past the owner limit or split a cohesive
  renderer to satisfy counts. Raise `--max-function-lines` only to the measured
  span of a block that neither grew nor gained a responsibility, and record it.

## Stop If

- The requirement the change serves is unknown; ask instead of reviewing by taste.
- A change touches auth, session, permission, privacy, persisted data, cache,
  schema, migration, upload/download/media publish, notification or background
  retry, or release signing/build config with no completion-gate evidence.

## Verification

- Completion-gate changes need a dry run, a focused check of the changed
  transition, explicit approval, or a rollback/idempotency path; name the
  run-twice and fail-halfway result for network and file writes. Otherwise
  write the manual scenario and residual risk.
- Pick the narrowest tool: lint/ktlint/ktfmt/detekt, JVM unit, instrumented,
  Compose UI/Espresso, screenshot, Turbine, Macrobenchmark. With no static tool
  config, review against code-conventions' strict profile; note the gap.
- Use the device MCP when the diff changes a rendered surface; exercise
  enqueue-and-return host contracts on a device or emulator.
- Label debug/emulator performance evidence diagnostic only.

## Report

Findings first, most severe first, in the finding format. Then the surface
procedures run with their evidence, the verified paths, and the remaining
manual checks and residual risk; unverified paths are never reported as passed.
