---
keyflow_id: sys_android_external_skill_source_coverage
status: review
type: ai-generated
---

# Android External Skill Source Coverage

Use this when Android work cites or imports lessons from external skill
repositories. This card is a source coverage manifest, not a vendored copy of
those repositories.

## Purpose

Tao Agent OS should keep concise shared rules in the Android cards, while this
manifest prevents source omissions. When a task touches a surface listed here,
read the relevant source skill file and its references before designing,
editing, or reviewing that surface.

For the skill-bundle entrypoint and reusable distilled rules, read
`platforms/android/skills/source-coverage/SKILL.md` and
`platforms/android/skills/source-coverage/references/external-source-distillation.md`.

Do not claim all external guidance was applied unless the task checked this
manifest and either loaded the matching source docs or documented why they were
not relevant.

## Source Policy

- Do not vendor or copy full external skill repositories into Tao Agent OS by
  default.
- Distill reusable rules into Tao Agent OS only when they remain correct across
  products and repositories.
- Keep provider-specific setup, sample code, release notes, and surface details
  as source references unless Tao Agent OS needs a reusable rule.
- If a source repository changes, refresh this manifest with the new commit and
  re-check whether Android cards need rule updates.
- In final reports or PR descriptions, cite the source repository and the
  source surface, not only the Tao Agent OS summary.

## Source Snapshots

These local snapshots were reviewed for this manifest:

| Repository | Local snapshot | Commit |
| --- | --- | --- |
| `https://github.com/android/skills` | `/private/tmp/notmid-tao-source-android-skills` | `07302ca15e21d827cab5ca64d46407fb51dbe0aa` |
| `https://github.com/skydoves/compose-performance-skills` | `/private/tmp/notmid-tao-source-compose-performance-skills` | `1b32f81724c0d71fe9ef093ca44697f559fdab6e` |
| `https://github.com/chrisbanes/skills` | `/private/tmp/notmid-tao-source-chrisbanes-skills` | `10e5158f9d674d340531c6559ce311b22e3f6457` |

## No-Omission Gate

For Android documentation, architecture, module, Compose, performance, testing,
or platform-SDK work:

1. Identify the touched source surface below.
2. Read the matching `SKILL.md`.
3. Read the listed `references/` docs when the task changes implementation,
   dependencies, public contracts, security behavior, testing, or verification
   for that surface.
4. Update the concise Tao Agent OS rule card only when the lesson is reusable.
5. Report the source surface and residual source docs not loaded because they
   were out of scope.

This gate is especially important for tasks involving package/module
boundaries, Navigation 3, deep links, Compose performance, edge-to-edge,
testing, credentials, billing, profiling, Wear, XR, CameraX, and AppFunctions.

## Workflow Routing Contract

This manifest is not a passive bibliography. Android routes must load it when
the selected platform is `android` and the task concern touches any source
surface covered by the external skill repositories.

The workflow router should include this manifest for Android concerns such as:

- `architecture`, `module`, or `structure`: module/package boundaries,
  Navigation 3, deep links, `api`/`impl`, `assertions`, and feature contracts.
- `compose`, `ui`, `state`, or `performance`: Compose state, side effects,
  recomposition, stability, lazy layouts, modifier APIs, slots, focus, previews,
  and UI testing.
- `testing` or `test`: Android testing setup, Compose UI testing, screenshot
  testing, state restoration, form-factor coverage, and E2E scope.
- `skills` or `skill`: Android external skill source coverage audits,
  manifest refreshes, split source-map updates, or comparisons against
  upstream `SKILL.md` and `references/` content.
- `security`: exported components, intents, PendingIntent mutability, deep
  links, WebView bridges, credentials, and release configuration.
- `devtools`, `dependency`, `release`, `migration`, or `platform`: Android CLI,
  AGP, R8, Perfetto, XML-to-Compose migration, edge-to-edge, intent security,
  CameraX, Credential Manager, Play surfaces, Wear, XR, and AppFunctions.

If an Android route for those concerns does not include this manifest, treat the
route as incomplete before editing. Keep Tao Agent OS's local Android
architecture as the primary rule source; use external skills to prevent
omission and to confirm version-sensitive source behavior.

## Source Trigger Map

Use the narrowest external source file that matches the touched surface:

| Surface | Start With |
| --- | --- |
| Compose recomposition, stability, deferred reads, lazy list jank, custom modifiers, baseline profiles, or performance claims | `skydoves/compose-performance-skills` `INDEX.md` and the matching `SKILL.md`; then use Chris Banes focused Compose skills when state, effects, or API shape is the root cause. |
| Compose state hoisting, state-holder split, side effects, modifiers, slots, focus, UI testing, Flow, or coroutine ownership | `chrisbanes/skills` matching `skills/<name>/SKILL.md`. |
| Android CLI/device inspection, AGP, R8, Navigation 3, edge-to-edge, testing setup, intent security, CameraX, credentials, Play, Wear, XR, or AppFunctions | `android/skills` matching platform `SKILL.md` and its listed references. |

Do not copy full skill text into Tao Agent OS. Distill only reusable decision
rules, stop signals, and verification requirements into the local Android card
that owns the recurring lesson.

## Google Android Skills Coverage

Repository: `https://github.com/android/skills`

Top-level source docs:

- `README.md`

Skill and reference coverage:

- `build/agp/agp-9-upgrade/SKILL.md`
  - `build/agp/agp-9-upgrade/references/android/build/releases/agp-9-0-0-release-notes.md`
  - `build/agp/agp-9-upgrade/references/buildconfig.md`
  - `build/agp/agp-9-upgrade/references/ksp-kapt.md`
  - `build/agp/agp-9-upgrade/references/paparazzi-gradle-9.md`
  - `build/agp/agp-9-upgrade/references/recipes.md`
- `camera/camera1-to-camerax/SKILL.md`
- `device-ai/appfunctions/SKILL.md`
  - `device-ai/appfunctions/references/adb-interaction-testing.md`
  - `device-ai/appfunctions/references/feature-discovery-analysis.md`
  - `device-ai/appfunctions/references/implementation-configuration.md`
  - `device-ai/appfunctions/references/kdoc-refinement-optimization.md`
- `devtools/android-cli/SKILL.md`
  - `devtools/android-cli/references/interact.md`
  - `devtools/android-cli/references/journeys.md`
- `identity/verified-email/SKILL.md`
  - `identity/verified-email/references/android/identity/credential-manager/index.md`
  - `identity/verified-email/references/android/identity/digital-credentials/credential-verifier.md`
  - `identity/verified-email/references/android/identity/digital-credentials/email-verification-implementation.md`
  - `identity/verified-email/references/android/identity/digital-credentials/email-verification.md`
  - `identity/verified-email/references/android/identity/digital-credentials/index.md`
  - `identity/verified-email/references/android/identity/passkeys/create-passkeys.md`
  - `identity/verified-email/references/android/identity/sign-in/credential-manager-webview.md`
- `jetpack-compose/adaptive/SKILL.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/flexbox/container-behavior.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/flexbox/get-started.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/flexbox/index.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/flexbox/item-behavior.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/grid/container-properties.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/grid/get-started.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/grid/index.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/grid/item-properties.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/layouts/adaptive/mediaquery/index.md`
  - `jetpack-compose/adaptive/references/android/develop/ui/compose/tooling/debug.md`
  - `jetpack-compose/adaptive/references/android/guide/navigation/navigation-3/recipes/material-listdetail.md`
- `jetpack-compose/migration/migrate-xml-views-to-jetpack-compose/SKILL.md`
  - `jetpack-compose/migration/migrate-xml-views-to-jetpack-compose/references/android/develop/ui/compose/designsystems/migrate-xml-theme-to-compose.md`
  - `jetpack-compose/migration/migrate-xml-views-to-jetpack-compose/references/android/develop/ui/compose/migrate/interoperability-apis/compose-in-views.md`
  - `jetpack-compose/migration/migrate-xml-views-to-jetpack-compose/references/android/develop/ui/compose/migrate/interoperability-apis/views-in-compose.md`
  - `jetpack-compose/migration/migrate-xml-views-to-jetpack-compose/references/android/develop/ui/compose/setup-compose-dependencies-and-compiler.md`
  - `jetpack-compose/migration/migrate-xml-views-to-jetpack-compose/references/identify-optimal-xml-candidate.md`
  - `jetpack-compose/migration/migrate-xml-views-to-jetpack-compose/references/xml-layout-migration.md`
- `jetpack-compose/theming/styles/SKILL.md`
  - `jetpack-compose/theming/styles/references/android/develop/ui/compose/designsystems/custom.md`
  - `jetpack-compose/theming/styles/references/android/develop/ui/compose/styles/fundamentals.md`
  - `jetpack-compose/theming/styles/references/android/develop/ui/compose/styles/state-animations.md`
  - `jetpack-compose/theming/styles/references/android/develop/ui/compose/styles/styles-vs-modifiers.md`
  - `jetpack-compose/theming/styles/references/android/develop/ui/compose/styles/theming.md`
- `navigation/navigation-3/SKILL.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/index.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/migration-guide.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/animations.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/basic.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/basicsaveable.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/bottomsheet.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/common-ui.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/conditional.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/deeplinks-advanced.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/dialog.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/material-listdetail.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/material-supportingpane.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/modular-hilt.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/multiple-backstacks.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/passingarguments.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/results-event.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/results-state.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/scenes-listdetail.md`
  - `navigation/navigation-3/references/android/guide/navigation/navigation-3/recipes/scenes-twopane.md`
  - `navigation/navigation-3/references/android/guide/navigation/type-safe-destinations.md`
- `performance/r8-analyzer/SKILL.md`
  - `performance/r8-analyzer/references/CONFIGURATION-ANALYZER.md`
  - `performance/r8-analyzer/references/CONFIGURATION.md`
  - `performance/r8-analyzer/references/KEEP-RULES-IMPACT-HIERARCHY.md`
  - `performance/r8-analyzer/references/REDUNDANT-RULES.md`
  - `performance/r8-analyzer/references/REFLECTION-GUIDE.md`
  - `performance/r8-analyzer/references/REPORT_FORMAT.md`
  - `performance/r8-analyzer/references/android/topic/performance/app-optimization/enable-app-optimization.md`
  - `performance/r8-analyzer/references/android/training/testing/other-components/ui-automator.md`
- `play/engage-sdk-integration/SKILL.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/faq.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/food.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/healthandfitness.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/listen.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/otherverticals.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/read.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/shopping.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/social.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/travel.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/tv/continue-watching/index.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/tv/entitlements.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/tv/getting-started.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/tv/recommendations.md`
  - `play/engage-sdk-integration/references/android/guide/playcore/engage/watch.md`
  - `play/engage-sdk-integration/references/clusters.md`
  - `play/engage-sdk-integration/references/common.md`
  - `play/engage-sdk-integration/references/patterns.md`
  - `play/engage-sdk-integration/references/schemas/food.md`
  - `play/engage-sdk-integration/references/schemas/listen.md`
  - `play/engage-sdk-integration/references/schemas/other.md`
  - `play/engage-sdk-integration/references/schemas/read.md`
  - `play/engage-sdk-integration/references/schemas/shopping.md`
  - `play/engage-sdk-integration/references/schemas/social.md`
  - `play/engage-sdk-integration/references/schemas/travel.md`
  - `play/engage-sdk-integration/references/schemas/tv.md`
  - `play/engage-sdk-integration/references/schemas/watch.md`
- `play/play-billing-library-version-upgrade/SKILL.md`
  - `play/play-billing-library-version-upgrade/references/android/google/play/billing/release-notes.md`
  - `play/play-billing-library-version-upgrade/references/migration-logic.md`
  - `play/play-billing-library-version-upgrade/references/version-checklist.md`
- `profilers/perfetto-sql/SKILL.md`
  - `profilers/perfetto-sql/references/perfetto-stdlib.md`
- `profilers/perfetto-trace-analysis/SKILL.md`
  - `profilers/perfetto-trace-analysis/references/hints_cpu.md`
  - `profilers/perfetto-trace-analysis/references/hints_graphics.md`
  - `profilers/perfetto-trace-analysis/references/hints_io.md`
  - `profilers/perfetto-trace-analysis/references/hints_ipc.md`
  - `profilers/perfetto-trace-analysis/references/hints_memory.md`
  - `profilers/perfetto-trace-analysis/references/hints_power.md`
  - `profilers/perfetto-trace-analysis/references/perfetto-stdlib.md`
  - `profilers/perfetto-trace-analysis/references/sql.md`
- `system/edge-to-edge/SKILL.md`
- `security/android-intent-security/SKILL.md`
- `testing/testing-setup/SKILL.md`
  - `testing/testing-setup/references/android/develop/ui/compose/testing/common-patterns.md`
  - `testing/testing-setup/references/android/studio/preview/compose-screenshot-testing.md`
  - `testing/testing-setup/references/android/training/dependency-injection/hilt-testing.md`
- `wear/wear-compose-m3/SKILL.md`
  - `wear/wear-compose-m3/references/android/training/wearables/compose/migrate-to-material3.md`
- `xr/display-glasses-with-jetpack-compose-glimmer/SKILL.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/design/ui/ai-glasses/guides/interaction/inputs.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/develop/xr/jetpack-xr-sdk/access-hardware-projected-context.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/develop/xr/jetpack-xr-sdk/jetpack-compose-glimmer/buttons.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/develop/xr/jetpack-xr-sdk/jetpack-compose-glimmer/cards.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/develop/xr/jetpack-xr-sdk/jetpack-compose-glimmer/focus.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/develop/xr/jetpack-xr-sdk/jetpack-compose-glimmer/icons.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/develop/xr/jetpack-xr-sdk/jetpack-compose-glimmer/text.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/develop/xr/jetpack-xr-sdk/jetpack-compose-glimmer/title-chips.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/android/develop/xr/jetpack-xr-sdk/request-hardware-permissions.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/button-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/card-samples-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/card-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/deptheffect-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/deptheffectlevels-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/glimmersansflextypography-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/glimmertheme-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/icon-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/iconbutton-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/iconsizes-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/list-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/listitem-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/material-hct-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/projectedcontext-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/stack-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/stackitemscope-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/stackstate-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/surface-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/titlechip-samples-source.md`
  - `xr/display-glasses-with-jetpack-compose-glimmer/references/titlechip-source.md`

## Compose Performance Skills Coverage

Repository: `https://github.com/skydoves/compose-performance-skills`

Top-level source docs:

- `<source-repo>/README.md`
- `<source-repo>/INDEX.md`
- `<source-repo>/CONTRIBUTING.md`
- `<source-repo>/docs/SPEC.md`
- `<source-repo>/docs/CORPUS.md`

Skill and reference coverage:

- `audit/auditing-compose-performance/SKILL.md`
- `build/configuring-r8-for-compose/SKILL.md`
- `hot-reload/iterating-with-ai-and-mcp/SKILL.md`
- `hot-reload/preserving-state-across-reloads/SKILL.md`
- `hot-reload/setting-up-compose-hotswan/SKILL.md`
- `hot-reload/understanding-hot-reload-limits/SKILL.md`
- `lists/configuring-lazy-prefetch/SKILL.md`
- `lists/optimizing-lazy-layouts/SKILL.md`
- `measurement/generating-baseline-profiles/SKILL.md`
  - `measurement/generating-baseline-profiles/references/macrobenchmark-harness.md`
- `measurement/testing-compose-in-release-mode/SKILL.md`
- `measurement/tracing-recompositions-at-runtime/SKILL.md`
- `modifiers/migrating-to-modifier-node/SKILL.md`
  - `modifiers/migrating-to-modifier-node/references/modifier-node-anatomy.md`
- `modifiers/ordering-modifier-chains/SKILL.md`
- `recomposition/avoiding-subcomposition-pitfalls/SKILL.md`
- `recomposition/choosing-derivedstateof/SKILL.md`
- `recomposition/debugging-recompositions/SKILL.md`
- `recomposition/deferring-state-reads/SKILL.md`
  - `recomposition/deferring-state-reads/references/three-phases.md`
- `recomposition/using-strong-skipping-correctly/SKILL.md`
  - `recomposition/using-strong-skipping-correctly/references/escape-hatches.md`
- `side-effects/collecting-flows-safely/SKILL.md`
- `side-effects/using-efficient-effects/SKILL.md`
- `stability/diagnosing-compose-stability/SKILL.md`
  - `stability/diagnosing-compose-stability/references/reading-classes-txt.md`
  - `stability/diagnosing-compose-stability/references/reading-composables-txt.md`
- `stability/enforcing-stability-in-ci/SKILL.md`
- `stability/stabilizing-compose-types/SKILL.md`
  - `stability/stabilizing-compose-types/references/stability-config-syntax.md`
- `stability/understanding-stability-inference/SKILL.md`
  - `stability/understanding-stability-inference/references/bitmask-encoding.md`
  - `stability/understanding-stability-inference/references/twelve-phase-algorithm.md`
- `stability/using-stability-analyzer-ide-plugin/SKILL.md`
- `stability/visualizing-recomposition-cascades/SKILL.md`

## Chris Banes Skills Coverage

Repository: `https://github.com/chrisbanes/skills`

Top-level source docs:

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `skills.schema.json`

Skill coverage:

- `skills/compose-animations/SKILL.md`
- `skills/compose-focus-navigation/SKILL.md`
- `skills/compose-modifier-and-layout-style/SKILL.md`
- `skills/compose-recomposition-performance/SKILL.md`
- `skills/compose-side-effects/SKILL.md`
- `skills/compose-slot-api-pattern/SKILL.md`
- `skills/compose-stability-diagnostics/SKILL.md`
- `skills/compose-state-authoring/SKILL.md`
- `skills/compose-state-deferred-reads/SKILL.md`
- `skills/compose-state-hoisting/SKILL.md`
- `skills/compose-state-holder-ui-split/SKILL.md`
- `skills/compose-ui-testing-patterns/SKILL.md`
- `skills/kotlin-coroutines-structured-concurrency/SKILL.md`
- `skills/kotlin-flow-state-event-modeling/SKILL.md`
- `skills/kotlin-multiplatform-expect-actual/SKILL.md`
- `skills/kotlin-types-value-class/SKILL.md`
- `skills/shepherd/SKILL.md`
- `skills/using-chrisbanes-skills/SKILL.md`

## Tao Agent OS Mapping

These Tao Agent OS cards consume this source coverage:

- `platforms/android/skills/android-module-structure/SKILL.md` for Android modularization,
  source-set, SDK-surface, toolchain, and package-boundary routing.
- `platforms/android/skills/android-compose-ui/SKILL.md` for Compose state, performance,
  layout, modifiers, effects, slots, focus, animation, previews, and testing.
- `platforms/android/skills/android-review/SKILL.md` for review acceptance criteria across
  Android module, Compose, performance, security, and SDK surfaces.
- `platforms/android/skills/android-architecture/SKILL.md` for app architecture, Navigation
  3, deep links, route contracts, and app-runtime boundaries.
- `platforms/kmp/skills/kmp-architecture/SKILL.md` and
  `platforms/kmp/skills/kmp-module-structure/SKILL.md` when Kotlin Multiplatform,
  expect/actual, common source sets, or platform adapters are involved.

When a source doc is missing from these mappings, update this manifest first,
then update the concise rule card that owns the recurring lesson.
