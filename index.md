---
keyflow_id: sys_a0cda107d0b0
status: stable
type: ai-generated
---

# Agent Index

Pick the smallest relevant document set. Repo-local guidance wins over this shared library.

## Common

- Agent operating baseline: `common/skills/agent-operating-skill/SKILL.md`
- User questions, approvals, status updates, and handoff messages: `common/skills/agent-interaction/SKILL.md`
- Request clarity, model/effort routing, token controls, Grill-Me: `common/skills/task-intake-effort-routing/SKILL.md`
- All coding work: `common/skills/llm-coding-discipline/SKILL.md`
- Code conventions, naming, comments, formatting: `common/skills/code-conventions/SKILL.md`
- SOLID design principles, ISP contract/module splits, dependency inversion, and DDD/domain-modeling fit: `common/skills/solid-design-principles/SKILL.md`
- Code structure, file/module ownership, api/impl split: `common/skills/code-structure-ownership/SKILL.md`
- Reusable code design, extraction, shared module/package contracts: `common/skills/reusable-code-design/SKILL.md`
- Component API design, reusable view/hook/widget contracts: `common/skills/component-api-design/SKILL.md`
- Stack, package manager, framework, runtime, and command discovery: `common/skills/stack-discovery/SKILL.md`
- Project, app, repo, package, module, CLI, and service naming: `common/skills/project-naming/SKILL.md`
- Change size and reviewable diff scope: `common/skills/change-size-policy/SKILL.md`
- Existing checkout and user-owned diff safety: `common/skills/worktree-hygiene/SKILL.md`
- Dependencies, SDKs, packages, build plugins: `common/skills/dependency-policy/SKILL.md`
- Generated files, lockfiles, snapshots, build artifacts: `common/skills/generated-files-policy/SKILL.md`
- API, DTO, route, event, webhook contract compatibility: `common/skills/api-contract-compatibility/SKILL.md`
- Asset upload, URL, publish, cleanup, and embedded reference lifecycle: `common/skills/asset-lifecycle/SKILL.md`
- Defensive handling for external, persisted, generated, cached, or user-provided values: `common/skills/defensive-boundaries/SKILL.md`
- Environment-specific runtime URL configuration, callback URLs, CORS origins, webhook endpoints, API origins, and asset hosts: `common/skills/runtime-url-configuration/SKILL.md`
- Release, deployment, packaging, rollback: `common/skills/release-deployment/SKILL.md`
- Release version, tag, artifact, build number, and deployment id scheme: `common/skills/release-versioning/SKILL.md`
- Web deployment versioning, public release version versus deploy id, and continuous deployment release history: `common/skills/web-deployment-versioning/SKILL.md`
- Accessibility, localization, dates, numbers, units, measurements, display values, UI text: `common/skills/accessibility-i18n/SKILL.md`
- Human-authored prose, voice fidelity, and AI-writing signal cleanup: `common/skills/human-authored-writing/SKILL.md`
- Blog/article draft workspace, publishing-target separation, and shared writing source-of-truth: `common/skills/writing-workspace/SKILL.md`
- Tao Agent OS card anatomy, anti-rationalization, red flags, and evidence sections: `common/skills/agent-skill-card-anatomy/SKILL.md`
- Tao Agent OS skill bundle migration, `SKILL.md` plus `references/`structure, and duplicate source-of-truth cleanup: `docs/skills/tao-skill-bundle-migration/SKILL.md`
- Architecture choice/change: `common/skills/architecture-selection/SKILL.md`
- Architecture design: `common/skills/architecture-design/SKILL.md`
- Source-driven framework, SDK, platform, API, and external-doc decisions: `common/skills/source-driven-development/SKILL.md`
- Doubt-driven challenge pass for high-risk assumptions: `common/skills/doubt-driven-development/SKILL.md`
- Incremental implementation and verified slice planning: `common/skills/incremental-implementation/SKILL.md`
- New feature or product ambiguity: `common/skills/product-spec-to-implementation/SKILL.md`
- LLM-readable wiki, knowledge-base, runbook, or durable documentation: `common/skills/llm-wiki-documentation/SKILL.md`
- Public discovery, SEO, AI search visibility, sitemap, metadata, previews, and canonical URLs: `common/skills/public-discovery/SKILL.md`
- App boundary/state/data shape: `common/skills/app-architecture/SKILL.md`
- State modeling, UiState, effects, reducers, stores, ViewModels, hooks: `common/skills/state-modeling/SKILL.md`
- Refactor: `common/skills/refactoring/SKILL.md`
- Testing or bug regression: `common/skills/testing/SKILL.md`
- Scenario-driven test design and QA flow coverage: `common/skills/scenario-driven-testing/SKILL.md`
- Verification evidence: `common/skills/verification-policy/SKILL.md`
- Bulk mechanical change transforms and verification reliability: `common/skills/bulk-change-verification/SKILL.md`
- Completion checklist and Definition of Done: `common/skills/definition-of-done/SKILL.md`
- Tool, compiler, lint, test, and command failure recovery: `common/skills/tool-failure-recovery/SKILL.md`
- Local tools, AI CLIs, runtime, usage telemetry: `common/skills/local-tools/SKILL.md`
- File editing safety, secrets, external state: `common/skills/agent-editing-safety/SKILL.md`
- Design system or shared UI rules: `common/skills/design-system/SKILL.md`
- UI visual and interaction verification: `common/skills/ui-visual-verification/SKILL.md`
- Secure development, secrets, client keys, open-source-safe setup: `common/skills/secure-development-baseline/SKILL.md`
- Security/privacy/secrets/tenant risk: `common/skills/security-privacy-review/SKILL.md`
- Persistence, cache, sync, migration: `common/skills/data-persistence-sync/SKILL.md`
- Server-rendered/API/edge/database caching and invalidation: `common/skills/server-side-caching/SKILL.md`
- Errors, logs, audit, diagnostics: `common/skills/observability-error-handling/SKILL.md`
- CI/CD automation, workflow files, release checks, publishing and deployment automation: `common/skills/ci-cd-automation/SKILL.md`
- Deprecation, migration, removal, compatibility windows, and zero-usage cleanup: `common/skills/deprecation-migration/SKILL.md`
- All-platform performance proof, release-like measurement, diagnostic-only evidence: `common/skills/performance-verification/SKILL.md`
- Web performance evidence, Core Web Vitals, bundle/runtime measurement: `common/skills/web-performance-verification/SKILL.md`
- Browser runtime testing, console/network/DOM/accessibility inspection: `common/skills/browser-runtime-testing/SKILL.md`
- Error modeling, typed failures, retryability, user-visible failure states: `common/skills/error-modeling/SKILL.md`
- Code review: `common/skills/code-review/SKILL.md`
- Commit review: start with code review, then add `common/skills/commit-review/SKILL.md`
- Branch strategy and branch naming: `common/skills/branch-strategy/SKILL.md`
- Commit creation, branch/PR/push safety, staged diff policy: `common/skills/commit-workflow/SKILL.md`
- Merged-branch and worktree cleanup safety gates: `common/skills/branch-cleanup/SKILL.md`
- Git history investigation, blame noise filtering, origin-commit tracing: `common/skills/git-history-investigation/SKILL.md`

## Platform

- Android architecture: `platforms/android/skills/android-architecture/SKILL.md`
- Android module/package structure: `platforms/android/skills/android-module-structure/SKILL.md`
- Android external skill source coverage and no-omission manifest: `platforms/android/skills/android-external-skill-source-coverage/SKILL.md`
- Android external skill source entrypoint and distilled source rules: `platforms/android/skills/source-coverage/SKILL.md`
- Android ViewModel, UiState, Flow, repository, persistence, one-off events: `platforms/android/skills/android-viewmodel-state/SKILL.md`
- Android Compose UI structure, stateful/stateless split, previews, packages: `platforms/android/skills/android-compose-ui/SKILL.md`
- Android state/data: `platforms/android/skills/android-state-data/SKILL.md`
- Android DataStore persistence reference: `platforms/android/skills/android-state-data/references/android-datastore.md`
- Android background work: `platforms/android/skills/android-background-work/SKILL.md`
- Android memory and lifecycle ownership: `platforms/android/skills/android-memory-lifecycle/SKILL.md`
- Android security: `platforms/android/skills/android-security/SKILL.md`
- Android review: `platforms/android/skills/android-review/SKILL.md`
- KMP architecture: `platforms/kmp/skills/kmp-architecture/SKILL.md`
- KMP module/source-set structure: `platforms/kmp/skills/kmp-module-structure/SKILL.md`
- KMP Compose Multiplatform UI: `platforms/kmp/skills/kmp-compose-ui/SKILL.md`
- KMP state/data: `platforms/kmp/skills/kmp-state-data/SKILL.md`
- KMP platform integration: `platforms/kmp/skills/kmp-platform-integration/SKILL.md`
- KMP security: `platforms/kmp/skills/kmp-security/SKILL.md`
- KMP review: `platforms/kmp/skills/kmp-review/SKILL.md`
- Flutter architecture: `platforms/flutter/skills/flutter-architecture/SKILL.md`
- Flutter project/package structure: `platforms/flutter/skills/flutter-project-structure/SKILL.md`
- Flutter widget UI: `platforms/flutter/skills/flutter-widget-ui/SKILL.md`
- Flutter state/data: `platforms/flutter/skills/flutter-state-data/SKILL.md`
- Flutter platform integration: `platforms/flutter/skills/flutter-platform-integration/SKILL.md`
- Flutter security: `platforms/flutter/skills/flutter-security/SKILL.md`
- Flutter review: `platforms/flutter/skills/flutter-review/SKILL.md`
- Swift architecture: `platforms/swift/skills/swift-architecture/SKILL.md`
- Swift package/target/file structure: `platforms/swift/skills/swift-code-structure/SKILL.md`
- Swift design system, tokens, primitives, component variants, and previews: `platforms/swift/skills/swift-design-system/SKILL.md`
- Swift review: `platforms/swift/skills/swift-review/SKILL.md`
- iOS architecture: `platforms/ios/skills/ios-architecture/SKILL.md`
- iOS target/package structure: `platforms/ios/skills/ios-module-structure/SKILL.md`
- iOS SwiftUI UI structure, ViewModel contracts, UiState, previews, packages: `platforms/ios/skills/ios-swiftui-ui/SKILL.md`
- iOS UIKit UI structure, coordinators, view controllers, lists, forms: `platforms/ios/skills/ios-uikit-ui/SKILL.md`
- iOS state/concurrency: `platforms/ios/skills/ios-state-concurrency/SKILL.md`
- iOS security: `platforms/ios/skills/ios-security/SKILL.md`
- iOS review: `platforms/ios/skills/ios-review/SKILL.md`
- Web/React architecture: `platforms/web/skills/web-architecture/SKILL.md`
- Web file/feature structure and import boundaries: `platforms/web/skills/web-code-structure/SKILL.md`
- Web/React UI implementation, container/screen split, hooks, UiState: `platforms/web/skills/web-react-ui/SKILL.md`
- Web/React state/data: `platforms/web/skills/web-state-data/SKILL.md`
- Web design system, tokens, primitives, component variants, and styling: `platforms/web/skills/web-design-system/SKILL.md`
- Web accessibility/i18n: `platforms/web/skills/web-accessibility-i18n/SKILL.md`
- Web security: `platforms/web/skills/web-security/SKILL.md`
- Web review: `platforms/web/skills/web-review/SKILL.md`
- Server architecture: `platforms/server/skills/server-architecture/SKILL.md`
- Server API implementation: `platforms/server/skills/server-api-implementation/SKILL.md`
- Server data/jobs: `platforms/server/skills/server-data-jobs/SKILL.md`
- Server security: `platforms/server/skills/server-security/SKILL.md`
- Server review: `platforms/server/skills/server-review/SKILL.md`
- Application architecture: `platforms/application/skills/application-architecture/SKILL.md`
- Application command/UI implementation: `platforms/application/skills/application-command-ui/SKILL.md`
- Application React desktop renderer structure: `platforms/application/skills/application-react-desktop/SKILL.md`
- Application system integration: `platforms/application/skills/application-system-integration/SKILL.md`
- Application security: `platforms/application/skills/application-security/SKILL.md`
- Application review: `platforms/application/skills/application-review/SKILL.md`

## Product Pattern

- Auth/RBAC/permissions: `product-patterns/skills/auth-rbac-permissions/SKILL.md`
- Auth/RBAC implementation: `product-patterns/skills/auth-rbac-implementation/SKILL.md`
- Invitation flows: `product-patterns/skills/invitation-workflows/SKILL.md`
- Invitation implementation: `product-patterns/skills/invitation-implementation/SKILL.md`
- Billing/entitlements/quota: `product-patterns/skills/billing-entitlements/SKILL.md`
- Billing/entitlements implementation: `product-patterns/skills/billing-entitlements-implementation/SKILL.md`
- Agent credential broker ideation: `product-patterns/skills/agent-credential-broker-ideation/SKILL.md`

## Workflow

- Workflow script command list: `<TAO_LAUNCHER> workflow list`
- Lifecycle aliases supported by the workflow router: `spec`, `plan`, `build`, `test`, `review`, `webperf`, `code-simplify`, and `ship`. These aliases map to Tao Agent OS routes and must not replace the router with a second active command framework.
- Canonical lifecycle start (once per task): `<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command <command> --request "<USER_REQUEST>"`
- After start succeeds, open every route `required_docs` entry directly. Run the review hook after meaningful changes and the finish hook before final report, commit, release, or handoff.
- `workflow.py route`, `agent-preflight.py`, and `agent-finish-check.py` are lower-level diagnostics or compatibility fallbacks when the hook is unavailable; do not run them as a second lifecycle for the same task.
- Agent task lifecycle: `workflows/skills/agent-task-lifecycle/SKILL.md`
- Request triage: `workflows/skills/request-triage/SKILL.md`
- Agent handoff/continuation: `workflows/skills/agent-handoff-continuation/SKILL.md`
- Session continuation protocol: `workflows/skills/session-continuation-protocol/SKILL.md`
- Scripted workflow routing: `workflows/skills/scripted-agent-workflow/SKILL.md`
- Cycle contract: `workflows/skills/cycle-contract/SKILL.md`
- Ambiguity gate: `workflows/skills/ambiguity-gate/SKILL.md`
- PRD creation: `workflows/skills/prd-creation/SKILL.md`
- Product architecture delivery: `workflows/skills/product-architecture-delivery/SKILL.md`
- Development cycle: `workflows/skills/development-cycle/SKILL.md`
- Multi-agent collaboration: `workflows/skills/multi-agent-collaboration/SKILL.md`
- Multi-perspective review: `workflows/skills/multi-perspective-review/SKILL.md`
- Retrospective learning: `workflows/skills/retrospective-learning/SKILL.md`
- Planning/research: `workflows/skills/planning-research/SKILL.md`
- Documentation update: `workflows/skills/documentation-update/SKILL.md`
- Feature implementation: `workflows/skills/feature-implementation/SKILL.md`
- Bugfix/debugging: `workflows/skills/bugfix-debugging/SKILL.md`
- Refactor cleanup: `workflows/skills/refactor-cleanup/SKILL.md`
- Release readiness: `workflows/skills/release-readiness/SKILL.md`
- Review and commit: `workflows/skills/review-and-commit/SKILL.md`

## Loading Rule

For any multi-step agent task, start with `workflows/skills/agent-task-lifecycle/SKILL.md`. Run `<TAO_LAUNCHER> start` once to classify, route, audit, and create the parent evidence. Open every route `required_docs` entry directly before work, keep the route gate ledger current, run the review hook after meaningful changes, and run the finish hook before final report, commit, release, or handoff. If the hook is unavailable, the lower-level router/preflight/finish wrappers are a compatibility fallback, not a second lifecycle. Missing start, gate, review, or finish evidence is non-compliant.

For any new request, first classify clarity, effort, and model tier with `common/skills/task-intake-effort-routing/SKILL.md`. Do not use the strongest model, longest reasoning, or full-document loading by default. Use quick/fast for exact low-risk requests, standard/balanced for scoped implementation, and deep/frontier only for ambiguous, broad, high-risk, or cross-boundary work. Runtime bridges may map the abstract tier to concrete model ids such as Codex Luna, Terra, or Sol; non-Codex runtimes must use their own mapping or keep the current model.

Before running project commands, adding dependencies, or using framework-specific APIs, use `common/skills/stack-discovery/SKILL.md`. When a command fails, use `common/skills/tool-failure-recovery/SKILL.md` before retrying or changing code. When the agent needs to ask a blocker question or approval, use `common/skills/agent-interaction/SKILL.md`.

For PRD-only work, use `workflows/skills/prd-creation/SKILL.md` and select the PRD command at the canonical start:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command prd --request "<USER_REQUEST>" --platform <platform> --concern <concern>
```

For product or feature work that needs PRD -&gt; ARD -&gt; implementation -&gt; verification gates, use `workflows/skills/product-architecture-delivery/SKILL.md` and run the product command at the canonical start:

```text
<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command product --request "<USER_REQUEST>" --platform <platform> --concern <concern>
```

Use this `product` route, not the lower-level `feature` route, when the request is broad app-building, product delivery, a new multi-screen flow, architecture, data/auth/billing/release behavior, or a "show me how to build it" request that will continue into code. The `feature` route is only for scoped slices where the PRD/ARD gate is already satisfied or clearly unnecessary.

For lower-level multi-step development work, continue with `workflows/skills/development-cycle/SKILL.md`. For vague or risky requests, use `workflows/skills/ambiguity-gate/SKILL.md` before PRD, ARD, task breakdown, or implementation. After a task, incident, handoff, repeated mistake, or missed signal, use `workflows/skills/retrospective-learning/SKILL.md` only when there is a reusable lesson. For coding, read `common/skills/agent-operating-skill/SKILL.md`, `common/skills/llm-coding-discipline/SKILL.md`, and `common/skills/code-conventions/SKILL.md` first. Then read one platform architecture card. Add platform detail, common, or product-pattern cards only when the task touches that concern.

For documentation-only work, use `workflows/skills/documentation-update/SKILL.md`. For wiki, knowledge-base, source-grounded/living/generated docs, runbook, onboarding, durable architecture, or operational docs that humans and agents will read, also use `common/skills/llm-wiki-documentation/SKILL.md`. For documentation review, use `<TAO_LAUNCHER> start --project <TARGET_REPO> --rules <TAO_ROOT> --command docs-review --request "<USER_REQUEST>" --concern wiki`or manually combine `workflows/skills/review-and-commit/SKILL.md`, `workflows/skills/documentation-update/SKILL.md`, and `common/skills/llm-wiki-documentation/SKILL.md`. For planning, research, comparison, or recommendations before implementation, use `workflows/skills/planning-research/SKILL.md`. For interrupted, long-running, or transferred work, use `workflows/skills/agent-handoff-continuation/SKILL.md`; when the work must survive the session process itself ending, add `workflows/skills/session-continuation-protocol/SKILL.md`.

For delegated or parallel agent work, use `workflows/skills/multi-agent-collaboration/SKILL.md`. For non-trivial reviews, release candidates, or changes that need product, UX, architecture, reliability, security, and QA lenses, use `workflows/skills/multi-perspective-review/SKILL.md`.

For new project scaffolds, app names, repo names, package ids, modules, CLIs, services, slugs, bundle ids, or renames, read `common/skills/project-naming/SKILL.md`.

For broad diffs, refactors, PR review, or commit preparation, also read `common/skills/change-size-policy/SKILL.md`. When the worktree already contains changes or the task includes commit preparation, also read `common/skills/worktree-hygiene/SKILL.md`. For branch creation, push, PR, tag, or release publication, discover repo-local policy first; shared guidance does not assume `main`, `master`, `develop`, or `trunk` semantics. When deciding file layout, package layout, module ownership, public contracts, or `api`/`impl` splits, also read `common/skills/code-structure-ownership/SKILL.md`. Do not make `api`/`impl` modules by default. Choose that split only when a stable external contract, navigation/deep-link/registration boundary, implementation swap, dependency isolation, ownership split, or cycle/build coupling pressure exists. When code is extracted into shared modules, reused by multiple callers, or promoted into a package/API, also read `common/skills/reusable-code-design/SKILL.md`. When designing reusable UI components, hooks, widgets, controls, or other caller-facing component APIs, also read `common/skills/component-api-design/SKILL.md`. For dependency, SDK, package, build plugin, or lockfile work, read `common/skills/dependency-policy/SKILL.md`. For codegen, generated clients, lockfiles, snapshots, build artifacts, translations, or generated assets, read `common/skills/generated-files-policy/SKILL.md`.

For API, DTO, route, event, webhook, shared fixture, or generated client changes, read `common/skills/api-contract-compatibility/SKILL.md`. For packaging, deployment, publishing, signing, migration rollout, or rollback-sensitive work, read `common/skills/release-deployment/SKILL.md`. For release version, package version, app version, build number, tag, artifact name, or deployment id changes, also read `common/skills/release-versioning/SKILL.md`. For user-facing text, forms, controls, dates, numbers, units, measurements, display values, media, or localization, read `common/skills/accessibility-i18n/SKILL.md`.

For prose, documentation tone, release notes, marketing copy, emails, or AI-writing signal cleanup, read `common/skills/human-authored-writing/SKILL.md`. For UI text, forms, localized copy, or accessibility-sensitive content, also read `common/skills/accessibility-i18n/SKILL.md`.

For uploads, downloads, generated files, media, attachments, signed or temporary URLs, public/private asset movement, asset cleanup, or asset references embedded in persisted content, read `common/skills/asset-lifecycle/SKILL.md`.

For sitemap, robots, metadata, Open Graph previews, short links, public search, AI search visibility, AEO/GEO claims, canonical URLs, link previews, structured data, or public discovery feeds, read `common/skills/public-discovery/SKILL.md`.

For code that consumes external, persisted, generated, cached, platform, or user-provided values, read `common/skills/defensive-boundaries/SKILL.md`.

For UI, application, async, cache, reducer, store, ViewModel, hook, or state machine work, read `common/skills/state-modeling/SKILL.md`.

For error handling, typed failures, retries, and user-visible failure states, read `common/skills/error-modeling/SKILL.md`. Add `common/skills/observability-error-handling/SKILL.md`when logs, metrics, diagnostics, support traces, or audits are touched.

For UI layout, visible state, interaction, text overflow, responsive behavior, or accessibility-visible changes, read `common/skills/ui-visual-verification/SKILL.md`.

For server-rendered data, API response caching, framework data cache, request-level memoization, edge/CDN cache, database query cache, materialized read models, or cache invalidation, read `common/skills/server-side-caching/SKILL.md`.

For Android work touching background execution, release builds, exported components, deep links, WebView, permissions, or secrets, load the Android background/security cards instead of relying only on the architecture card.

For Android Compose screen or component work, load `platforms/android/skills/android-compose-ui/SKILL.md` before implementation. This includes stateful/stateless boundaries, previews, component package structure, and design-system promotion decisions.

For Android module, package, feature API, repository API, build-logic, or shared-core ownership work, load `platforms/android/skills/android-module-structure/SKILL.md` before implementation.

For Android ViewModel, `UiState`, Flow, repository, persistence, or one-off event work, load `platforms/android/skills/android-viewmodel-state/SKILL.md` before implementation.

For KMP or Compose Multiplatform work, load `platforms/kmp/skills/kmp-architecture/SKILL.md`. For shared modules, source-set hierarchy, umbrella frameworks, Gradle module splits, or KMP package ownership, also load `platforms/kmp/skills/kmp-module-structure/SKILL.md`; for shared Compose UI, also load `platforms/kmp/skills/kmp-compose-ui/SKILL.md`; for shared state, repositories, coroutines, persistence, or adapters, load `platforms/kmp/skills/kmp-state-data/SKILL.md`; for source sets, `expect`/`actual`, native interop, files, shell, clipboard, permissions, or target capabilities, load `platforms/kmp/skills/kmp-platform-integration/SKILL.md`.

For Flutter work, load `platforms/flutter/skills/flutter-architecture/SKILL.md`. For feature folders, local packages, package exports, plugin package shape, or federated plugin splits, also load `platforms/flutter/skills/flutter-project-structure/SKILL.md`; for widgets, forms, routes, design-system components, or golden/widget tests, also load `platforms/flutter/skills/flutter-widget-ui/SKILL.md`; for state owners, streams, repositories, storage, or async effects, load `platforms/flutter/skills/flutter-state-data/SKILL.md`; for MethodChannel, EventChannel, plugins, permissions, lifecycle, isolates, desktop, mobile, or web target behavior, load `platforms/flutter/skills/flutter-platform-integration/SKILL.md`.

For Swift or Apple-platform work, load `platforms/swift/skills/swift-architecture/SKILL.md`. For Swift Package Manager layout, Xcode targets, package products, public APIs, access control, target membership, resources, or file ownership, also load `platforms/swift/skills/swift-code-structure/SKILL.md`. For SwiftUI, UIKit, or AppKit design-system tokens, styles, primitives, reusable controls, variants, previews, or visual QA, load `platforms/swift/skills/swift-design-system/SKILL.md`. For Swift review, load `platforms/swift/skills/swift-review/SKILL.md`.

For iOS targets, local Swift packages, package exports, access control, feature contracts, or target membership work, load `platforms/ios/skills/ios-module-structure/SKILL.md` before implementation.

For iOS SwiftUI screen or component work, load `platforms/ios/skills/ios-swiftui-ui/SKILL.md` before implementation. This includes route/screen/section boundaries, ViewModel contracts, explicit `UiState`, architecture tracks, previews, and design-system promotion decisions.

For iOS UIKit screen or component work, load `platforms/ios/skills/ios-uikit-ui/SKILL.md`before implementation. This includes coordinator/view-controller boundaries, typed UI state, lists, forms, navigation, and UI tests.

For iOS work touching Keychain, Universal Links, URL schemes, app extensions, WebViews, permissions, entitlements, signing, release builds, or secrets, load the iOS security card instead of relying only on the architecture card.

For desktop/application work touching menu bar/tray controls, shell, file, clipboard APIs, power assertions, IPC, signing, notarization, updates, or first launch, load the application system/security cards.

For desktop/application UI, commands, windows, panels, shortcuts, menu bar/tray, background tasks, or renderer bridges, load `platforms/application/skills/application-command-ui/SKILL.md`.

For React-based desktop app work, such as Tauri, Electron, WebView, or a native shell with an embedded React renderer, load `platforms/application/skills/application-react-desktop/SKILL.md` together with the matching application command/system/security cards and the relevant web React structure cards.

For macOS Swift apps, combine the Swift cards with the Application cards: Swift owns package, state, design-system, and architecture boundaries; Application owns window/panel/menu bar/tray commands, OS resources, IPC, privileged APIs, packaging, signing, and updates.

For server API, GraphQL, RPC, webhook, route handler, validation, use case, repository, response shape, or API error work, load `platforms/server/skills/server-api-implementation/SKILL.md`.

When the task touches keys, auth, permissions, user data, logs, analytics, external integrations, local config, release config, or a public/open-source repo, read `common/skills/secure-development-baseline/SKILL.md` before implementation.

For React/web feature work, usually read:

```text
common/skills/llm-coding-discipline/SKILL.md
common/skills/code-conventions/SKILL.md
platforms/web/skills/web-architecture/SKILL.md
platforms/web/skills/web-react-ui/SKILL.md
platforms/web/skills/web-state-data/SKILL.md when state/data/storage is touched
platforms/web/skills/web-accessibility-i18n/SKILL.md when UI text, forms, menus, dialogs,
or localization are touched
```

For review, read `common/skills/code-review/SKILL.md` first. Then read the matching platform review card. Add `common/skills/security-privacy-review/SKILL.md` and product-pattern cards only for affected auth, invite, billing, tenancy, or security concerns.

Stop reading when you can answer:

- What is the state owner?
- What are the UI, domain, data, and platform boundaries?
- What security, permission, persistence, or billing risks exist?
- What verification proves the goal?
- Which project-specific rules live in the repo?
