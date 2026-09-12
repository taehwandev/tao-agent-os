---
keyflow_id: sys_android_structure_baseline
status: review
type: ai-generated
---

# Android Structure Baseline

Use when creating a module or feature slice, or when deciding where a new runtime boundary belongs.

Split out of `current-guidance.md`, which keeps the boundary
contract every Android change applies.

## Concrete Structure Baseline

For a product-sized Compose app, start with this concrete structure and shrink it when the repo is smaller:

```text
app                         Activity, app startup, top-level navigation, DI wiring
core/designsystem            theme, semantic tokens, component wrappers, previews
core/model                   pure Kotlin product models and ids
core/domain                  use cases, repository contracts, product policies
core/data                    repository implementations, DTO/cache mapping, fakes
core-app/<area>              Android/Compose app-runtime helpers
feature/<name>/api           destinations, navigate actions, entrypoints, events
feature/<name>/impl          Screen holder, ViewModel, UiState, Content, components
core/<area>/assertions       reusable fakes, fixtures, and assertion helpers
build-logic                  convention plugins and shared build settings
```

Keep the `app` module thin. Put reusable visual primitives in the design system, pure business data in model/domain, source coordination in data, and screen orchestration in feature implementations. Skip `api` modules, use cases, or repository splits until another module, test boundary, platform dependency, or replaceable implementation needs the contract.

The baseline intentionally keeps Compose UI in `feature/<name>/impl`. Add an
optional `feature/<name>/ui` only when a named consumer outside `impl` must reuse
the concrete feature surface; keep Activity and entry-binding execution in
`impl`. Add `api` for the whole navigation contract — destination type,
arguments, deep link, result, and `navigateTo<Feature>` — so a module that only
navigates never depends on the implementation. See
`../../android-module-structure/references/module-boundaries.md` for the
canonical ownership and dependency rules.

When a repo intentionally uses `api` plus implementation modules as its baseline
architecture, keep the same SOLID meaning: `api` exposes role-sized contracts,
events, route keys, repository ports, and stable entities; implementation
modules own screens, ViewModels, adapters, mappers, platform calls, and concrete
runtime wiring. The split exists so callers import interfaces and contracts
instead of concrete implementations, not to add ceremony.

Do not copy this baseline as literal module names. It is a shape for ownership
and dependency direction. If a repo's `app`, `core-app`, `core-ui`, `runtime`,
or `base` name is too broad for a caller to infer the capability, either split
the capability into a precise module or keep a precise package/export boundary
under the existing module.

Use `core-app` when shared code needs Android or Compose runtime APIs but should
remain feature-policy free. Good candidates are notice or alert hosts,
permission adapters, ActivityRoute launch adapters, reusable WebView runtime,
resources, and app-shell helpers. Keep feature copy, product route policy,
analytics policy, repositories, and screen-specific state in the app or feature
owner.

Do not put reusable Compose Activity templates, route execution, deep-link
handoff, notice/toast/dialog rendering, permission launchers, reusable WebView
runtime, design-system components, repositories, and feature policy into one
`core-app` or `app` bucket. A shared app-runtime module still needs package
boundaries named by capability, such as activity, route, notice, permission,
environment, or platform adapter.

Do not modernize old Android bases by recreating broad `BaseActivity`,
`BaseFragment`, or universal `BaseViewModel` hierarchies. Prefer small
Compose-first runtime contracts such as app environment, app root, route
coordinator, notice host, permission host, and platform adapter interfaces.
A Compose `BaseActivity` is acceptable only when it owns a narrow lifecycle
template such as `enableEdgeToEdge`, content installation, intent/deep-link
handoff, environment access, and extension hooks. It must not own product route
registration, feature screen mapping, repositories, ViewModel construction,
analytics policy, or screen-specific UI state.

## Runtime Boundary Example Stops

Shared Android runtime design needs at least one small example before
implementation. Add the example to the task doc, skill card, PRD, or review
summary whenever the design introduces a reusable Activity/AppRoot template,
route coordinator, ActivityRoute launcher, notice host, permission host, WebView
runtime, credential adapter, or generated DI/route discovery.

The example must show:

- the pure contract a ViewModel, feature, or app coordinator imports
- the Android/Compose runtime adapter that implements the contract
- the feature or app caller that benefits from the split
- the Android/framework imports that are forbidden in the pure contract
- the verification path for state, route, permission, notice, or launcher behavior

Minimal runtime contract example:

```kotlin
interface ActivityRouteLauncher {
    fun launch(request: ActivityRouteRequest)
}

data class ActivityRouteRequest(
    val route: ActivityRoute,
    val resultKey: String? = null,
)
```

Minimal runtime implementation boundary:

```kotlin
class AndroidActivityRouteLauncher(
    private val activity: ComponentActivity,
) : ActivityRouteLauncher {
    override fun launch(request: ActivityRouteRequest) {
        activity.startActivity(request.route.toIntent(activity))
    }
}
```

Keep `ActivityRouteLauncher` free of `Activity`, `Context`, `Intent`, Compose,
and `NavController` when it is meant to be a pure caller contract. Keep
`AndroidActivityRouteLauncher` in an app, app-runtime, or Android-specific
implementation boundary. If the design cannot show a caller, a forbidden import,
and a focused verification path, keep the launch local to the feature or ask for
the missing source example instead of inventing a shared runtime module.

When the repo uses Hilt, register feature-owned launch adapters with
multibindings instead of constructing them manually in the Activity or app root.
The Activity should inject one launcher or coordinator; feature implementation
modules contribute only their own handlers.

Example:

```kotlin
class DefaultActivityRouteLauncher @Inject constructor(
    @param:ActivityContext private val context: Context,
    private val handlers: Set<@JvmSuppressWildcards ActivityRouteLaunchHandler>,
) : ActivityRouteLauncher {
    override fun launch(request: ActivityRouteRequest) {
        handlers.firstOrNull { it.canHandle(request.route) }?.launch(request)
    }
}

@Module
@InstallIn(ActivityComponent::class)
abstract class WebViewActivityRouteModule {
    @Binds
    @IntoSet
    abstract fun bindWebViewActivityRouteLaunchHandler(
        impl: WebViewActivityRouteLaunchHandler,
    ): ActivityRouteLaunchHandler
}
```

Use `ActivityComponent` when the launcher needs an Activity context or Activity
lifecycle. Use `SingletonComponent` only for pure registries that do not hold
Activity, window, launcher, or Compose state. Do not make route handlers global
singletons simply to reduce Activity boilerplate.

Apply the same rule to route event planning. A product shell may own the route
graph, host/base-path policy, and cross-feature stack shape, but it must not
grow a hand-written list that casts every feature event type. Each feature or
product-slice implementation should contribute its own `RouteEventHandler` via
DI multibinding, and the app/root coordinator should consume only
`Set<RouteEventHandler>` or a registry abstraction.

The route graph or product route factory should also be a DI-managed class,
factory, or coordinator. Do not leave product route graphs as Kotlin `object`
singletons after adopting DI; otherwise the handler set is injectable but the
route policy remains a hidden service locator. Destination types and stateless
`DeepLinkSpec` values may stay as plain immutable `object` or `data class`
contracts, but graph assembly, route planning, handler-set composition, and
runtime factory creation should be injected.

Example:

```kotlin
class FeedRouteEventHandler @Inject constructor() : RouteEventHandler {
    override fun planFor(event: RouteEvent): RoutePlan? {
        return when (event) {
            is FeedRouteEvent.ClipRequested -> RoutePlan.compose(
                RouteStack.of(FeedRoute, ClipDetailRoute(event.clipId)),
            )
            else -> null
        }
    }
}

@Module
@InstallIn(ActivityComponent::class)
abstract class FeedRouteEventModule {
    @Binds
    @IntoSet
    abstract fun bindFeedRouteEventHandler(
        impl: FeedRouteEventHandler,
    ): RouteEventHandler
}
```

Use an explicit list only inside a small unit-test fixture or temporary
prototype. Stop and introduce multibinding or code-generated discovery when the
app shell would otherwise add one entry per feature, route event family,
initializer, deep-link contributor, or launch handler. If handler order can
change behavior, make the contract exact-type-only or add explicit priority
metadata; do not depend on incidental `Set` iteration order.

## Feature Implementation Checklist

For a non-trivial Compose feature, expect these pieces unless the repo has a more specific pattern:

```text
<Feature>Screen.kt     stateful holder, ViewModel wiring, effects, navigation
<Feature>Content.kt    stateless screen rendering and user intent callbacks
<Feature>UiState.kt    immutable state, actions, effects, UI display models
<Feature>ViewModel.kt  state owner, action handling, coroutine ownership
components/            feature-local stateless pieces
preview/               preview fixtures and sample UI states
```

Implementation order:

1. Define the screen contract: state, user actions, one-off effects, and route outputs.
2. Create or update the stateless `Content` and previews for visible states.
3. Add the `Screen` holder that collects state lifecycle-aware and handles effects.
4. Add ViewModel/use-case/repository boundaries only where data, policy, cache, permission, or platform APIs require ownership.
5. Verify state transitions and the visible UI path with repo-local tests, previews, screenshots, or manual smoke evidence.

Module decision:

- Keep the feature in one module when no caller needs a stable route or contract.
- Add `feature-api` when navigation, holder registration, route data, or another module needs the feature contract without implementation dependencies. Put the destination type, arguments, deep link, result, and navigate action there together; a navigate action left in the implementation hands every navigating caller the dependency the split was meant to remove.
- Add `feature-ui` only when another module must reuse the concrete Compose
  surface without importing `impl`; an internal `compose/` package, preview, or
  Activity wrapper is not sufficient reason.
- Add repository `api`/implementation split when features need stable repository interfaces/entities but must not see DTOs, Retrofit/Room/DataStore, SDKs, or cache internals.
- Add `assertions` modules only when reusable fakes, fixtures, recording helpers, or assertion DSLs need to compile against stable API contracts without importing production implementation modules.
- Add `core-app` only for shared Android/Compose app-runtime helpers that are free of feature copy, route policy, analytics policy, repository calls, and screen-specific state.
- Add shared/core modules only for stable, repeated contracts with clear ownership; do not create catch-all common modules.
