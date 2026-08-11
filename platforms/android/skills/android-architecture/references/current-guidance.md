---
keyflow_id: sys_f6093ac42517
status: review
type: ai-generated
---

# Android Architecture

Use for Compose/ViewModel/Flow, data, and Android platform boundary work.

For Compose state, Flow, repository, persistence, permissions, or lifecycle details, also use `android-state-data.md`.

For ViewModel, `UiState`, Flow, repository, use case, persistence, and one-off event implementation details, also use `android-viewmodel-state.md`.

For Compose screen/component structure, stateful/stateless split, previews, or package layout, also use `android-compose-ui.md`.

For Gradle module boundaries, `api`/implementation splits, package layout, and feature/common/core ownership, also use `android-module-structure.md`.

For credentials, deep links, exported components, WebView, or release builds, also use `android-security.md`.

For WorkManager, foreground services, alarms, notifications, sync, uploads, or downloads, also use `android-background-work.md`.

For Android work that touches official skill surfaces such as Navigation 3,
CameraX, AppFunctions, Credential Manager verified email, Play Engage, Play
Billing, AGP, R8, Perfetto, Wear, XR/Glimmer, or Android CLI/device tooling,
also use `android-external-skill-source-coverage.md` and
`skills/source-coverage/SKILL.md`.

## Boundaries

```text
Screen/Composable/Fragment -> Action -> ViewModel
  -> effect interfaces/delegates for notice, routing, deep links, permissions, launchers
  -> Use Case -> Repository -> Data Source/Platform Adapter
```

Module boundaries should support this dependency direction instead of fighting
it. UI feature modules depend on repository/domain contracts, not repository
internals; shared core/design-system modules do not depend on feature
implementations.

Treat SOLID as the reason for these boundaries. Interface Segregation keeps
ViewModels talking to small capability interfaces for alert, toast/snackbar,
router, deep-link, permission, and launcher effects. Dependency Inversion keeps
those interfaces in API/core contracts while concrete implementations live in
app, runtime, data, or feature implementation modules. Delegates are a
composition pattern for sharing those capabilities without inheriting from broad
base ViewModels.

Minimal effect contract shape:

```kotlin
interface NoticeSink {
    fun showNotice(request: NoticeRequest)
}

interface RouteEventSink<E : Any> {
    fun tryEmit(event: E)
}

class NoticeDelegate(
    private val sink: MutableSharedFlow<NoticeRequest>,
) : NoticeSink {
    override fun showNotice(request: NoticeRequest) {
        sink.tryEmit(request)
    }
}
```

Use this shape when a ViewModel needs alert, snackbar/toast, router, deep-link,
permission, or external launcher behavior without depending on Android UI
classes. The delegate exists to compose a capability; it must not become a
hidden base ViewModel, global service locator, product policy owner, or screen
state owner.

Do not:

- Inject `Activity`, `Context`, `NavController`, `SnackbarHostState`, `Toast`,
  `AlertDialog`, `ActivityResultLauncher`, or SDK clients into ViewModels.
- Put every effect into one broad `UiEffectManager`.
- Emit server presentation hints directly from the network layer to Android UI.
- Hide route registration, deep-link parsing, repository calls, or analytics in
  a reusable Activity base.

## Concrete Structure Baseline

For a product-sized Compose app, start with this concrete structure and shrink it when the repo is smaller:

```text
app                         Activity, app startup, top-level navigation, DI wiring
core/designsystem            theme, semantic tokens, component wrappers, previews
core/model                   pure Kotlin product models and ids
core/domain                  use cases, repository contracts, product policies
core/data                    repository implementations, DTO/cache mapping, fakes
core-app/<area>              Android/Compose app-runtime helpers
feature/<name>/api           route contracts, entrypoints, public events
feature/<name>/impl          Route, ViewModel, UiState, Screen, feature components
core/<area>/assertions       reusable fakes, fixtures, and assertion helpers
build-logic                  convention plugins and shared build settings
```

Keep the `app` module thin. Put reusable visual primitives in the design system, pure business data in model/domain, source coordination in data, and screen orchestration in feature implementations. Skip `api` modules, use cases, or repository splits until another module, test boundary, platform dependency, or replaceable implementation needs the contract.

The baseline intentionally keeps Compose UI in `feature/<name>/impl`. Add an
optional `feature/<name>/ui` only when a named consumer outside `impl` must reuse
the concrete feature surface; keep Activity and navigation execution in
`impl`. Add `api` independently for stable caller or navigation contracts. See
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
route policy remains a hidden service locator. Route keys and stateless
`DeepLinkSpec` values may stay as `object` values when they are pure immutable
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

## Hilt Runtime Composition

When a repo has adopted Hilt, the Activity or app root should not manually
compose runtime dependencies. It may connect injected coordinators to Compose
content, but Hilt modules own environment-backed choices and concrete object
creation.

Move these out of Activity/AppRoot code:

- BuildConfig-backed runtime config and flavor/environment selection
- network clients and qualified clients for separate backends
- repositories, data-source selection, and fake/static/API implementation
  switches
- auth gateways, token providers, credential adapters, and secure storage
  adapters
- route graphs, router factories, launch-handler registries, deep-link
  registries, and app initializers
- ViewModel factories for ViewModels that can be constructor-injected

Use `@HiltViewModel` for app or feature ViewModels that need repositories,
use cases, effect delegates, dispatchers, or runtime policies. Keep a direct
constructor only when tests need to pass recording fakes; production should use
Hilt's default ViewModel factory instead of a hand-written
`ViewModelProvider.Factory` in the Activity.

Example:

```kotlin
@Module
@InstallIn(SingletonComponent::class)
object RuntimeModule {
    @Provides
    @Singleton
    fun provideContentRepository(
        source: ContentSource,
        @Api client: NetworkClient,
    ): ContentRepository {
        return when (source) {
            ContentSource.Static -> StaticContentRepository()
            ContentSource.Api -> ApiContentRepository(client)
        }
    }
}

@HiltViewModel
class FeedViewModel @Inject constructor(
    private val repository: ContentRepository,
    @IoDispatcher private val ioDispatcher: CoroutineDispatcher,
) : ViewModel()

@AndroidEntryPoint
class MainActivity : BaseActivity() {
    @Inject lateinit var routerFactory: AppRouterFactory

    @Composable
    override fun Content() {
        val viewModel: FeedViewModel = viewModel()
        val router = rememberAppRouter(routerFactory)
        AppRoot(router = router, state = viewModel.state)
    }
}
```

Use qualifiers when multiple clients, dispatchers, URLs, or string config values
share the same Kotlin type. Prefer `SingletonComponent` for process-wide
clients, repositories, and config; `ActivityComponent` for Activity-dependent
adapters and collaborators; and `ViewModelComponent` for ViewModel-scoped
collaborators. A Hilt component scopes injected objects; it does not replace an
Android or Compose lifecycle owner.

Manual construction can remain local for UI state that is inherently Compose or
Activity-owned, such as `SnackbarHostState`, `ToastHostState`, camera/webview
controllers created with `remember`, and activity-result launchers. Those
objects are not graph services. Do not use this exception for repositories,
network clients, auth providers, route graphs, or ViewModel creation.

## DI-Assembled Compose And Activity Entries

Use an injected feature-entry registry only when feature renderers must be
independently registered, selected, or replaced. This is an architectural seam
between the product shell and leaf features, not a reason to move the product
route graph into DI.

The product shell owns cross-feature topology, auth gates, synthetic stacks,
and fallback policy. A selected feature entry owns its route holder, ViewModel
acquisition, feature state/effects, and stateless screen. Compose runtime still
owns composition, while Android remains responsible for creating
manifest-declared Activities.

The canonical rules for choosing a pure, Compose-capable, or Android API
boundary; completing implementation and DI registration; validating registry
keys; and preserving Activity/Compose lifecycle ownership live in
`../../android-module-structure/references/current-guidance.md`.

## Reusable WebView Surface

For WebView-backed destinations, make the reusable surface Compose content first
and let execution shells wrap it.

Use this shape when the same web destination may appear from an Activity route,
a Compose navigation entry, a modal/sheet, or a future app-shell wrapper:

```text
WebViewRouteData
  -> reusable Compose WebView content/controller
  -> Activity wrapper for external task, result, or manifest ownership
  -> Compose route wrapper when the app navigation stack owns the destination
```

Rules:

- Keep URL validation, allowlists, JavaScript policy, file access policy, and
  external-browser fallback in the WebView runtime or feature owner before a
  page is loaded.
- Keep the WebView body reusable as a Composable or controller-backed surface.
  An Activity should install that content; it should not fork a second WebView
  implementation.
- Use an Activity-backed route when the destination needs manifest metadata,
  task/back-stack isolation, Activity result integration, external app entry, or
  a WebView lifecycle boundary that should outlive the app Compose stack.
- Use a Compose route when the destination is part of the in-app navigation
  stack and does not need a separate Activity contract.
- Keep `Intent`, `Activity`, `WebView`, `WebSettings`, JavaScript bridges, and
  AndroidX Activity Result types out of pure route contracts. Put them in the
  runtime adapter, Activity wrapper, or Android-specific feature implementation.
- Do not put product copy, network error mapping, auth policy, or feature route
  registration into a generic WebView base.

If a WebView design cannot show the route data, reusable Compose content,
Activity or Compose wrapper, security policy, and verification path, keep the
WebView local until that example exists.

## Navigation 3 Advanced Deep Links

For Navigation 3-style Compose apps, treat deep links as an app-entry concern
that creates navigation state, not as a screen-local shortcut.

Use this flow:

```text
Activity intent data
  -> app deep-link request
  -> host/scheme/base-path validation
  -> feature route/deep-link contract
  -> synthetic back stack or route plan
  -> Compose entry mapping and/or ActivityRoute launch request
```

Rules:

- The Activity is the external deep-link entrypoint. It may read `ACTION_VIEW`
  intent data, but it should pass a normalized request into the route
  coordinator instead of parsing feature paths inline.
- The app route coordinator builds the synthetic back stack before Compose
  rendering. Feature implementation screens emit callbacks or route events;
  they do not reconstruct deep-link paths.
- Compose route keys belong to feature API or router API contracts. The app,
  feature implementation, or app-shell module owns the entry builder that maps
  those keys to Compose content.
- Activity-backed destinations are execution requests. An Activity may own its
  own local Navigation 3 back stack, but the top-level router should not mix
  that local stack into the app Compose stack.
- Treat current-task and new-task deep-link launches as separate behavior. Back
  and Up expectations must be explicit and covered by tests or smoke evidence
  whenever both entry paths are supported.
- Keep AndroidX Navigation types out of pure router API modules until the app
  intentionally adopts Navigation 3 as the execution engine. Put the bridge in
  the app, app-shell, or Android-specific router boundary.
- Keep the Activity/base layer responsible for receiving intents and forwarding
  normalized deep-link requests. Keep route planning and synthetic back-stack
  construction in the route coordinator or app-shell runtime. Keep product
  route eligibility and feature entry mapping in app or feature owners.
  Do not hide all three responsibilities in a `BaseActivity`.

## Feature Slice Baseline

Start every Android feature by naming the smallest architecture track that fits the behavior:

| Track | Use When | Required Shape |
| --- | --- | --- |
| Local UI | Local interaction only; no async data, persistence, permission, or navigation side effect. | Stateless composable plus local `remember` state where needed. |
| MVVM | Screen loads data, submits forms, handles permission state, emits navigation, or has testable UI logic. | `Route -> ViewModel -> Screen`; ViewModel owns `UiState`, actions, and effects. |
| Clean Architecture | Domain policy, offline/cache, auth/tenant/billing, sync, multiple clients, or risky side effects. | `Route -> ViewModel -> UseCase -> Repository -> DataSource/Adapter`. |
| Reducer/MVI | Many actions, optimistic updates, replayable transitions, concurrency races, or complex undo/retry. | `Route -> ViewModel/Store -> Reducer -> Effects/UseCases`. |

Do not add use cases, repositories, reducers, or modules only for ceremony. Add them when they protect a product rule, platform side effect, cache boundary, permission boundary, or test boundary.

## Rules

- Composable renders state and sends events.
- Split ViewModel-backed holder composables from stateless screen/content composables.
- ViewModel owns UI state and lifecycle-aware work.
- Model loading, empty, error, permission denied explicitly.
- Keep one-off events separate from persistent state.
- Wrap API, Room, DataStore, file, permission, notification APIs.
- Keep background work behind Worker/use-case boundaries.
- Validate exported components, deep links, and release build security surfaces.
- Follow the repo's existing DI style.

## Feature Implementation Checklist

For a non-trivial Compose feature, expect these pieces unless the repo has a more specific pattern:

```text
<Feature>Route.kt      stateful holder, ViewModel wiring, effects, navigation
<Feature>Screen.kt     stateless screen rendering and user intent callbacks
<Feature>UiState.kt    immutable state, actions, effects, UI display models
<Feature>ViewModel.kt  state owner, action handling, coroutine ownership
components/            feature-local stateless pieces
preview/               preview fixtures and sample UI states
```

Implementation order:

1. Define the screen contract: state, user actions, one-off effects, and route outputs.
2. Create or update the stateless `Screen` and previews for visible states.
3. Add the `Route` holder that collects state lifecycle-aware and handles effects.
4. Add ViewModel/use-case/repository boundaries only where data, policy, cache, permission, or platform APIs require ownership.
5. Verify state transitions and the visible UI path with repo-local tests, previews, screenshots, or manual smoke evidence.

Module decision:

- Keep the feature in one module when no caller needs a stable route or contract.
- Add `feature-api` when navigation, holder registration, route data, or another module needs the feature contract without implementation dependencies.
- Add `feature-ui` only when another module must reuse the concrete Compose
  surface without importing `impl`; an internal `compose/` package, preview, or
  Activity wrapper is not sufficient reason.
- Add repository `api`/implementation split when features need stable repository interfaces/entities but must not see DTOs, Retrofit/Room/DataStore, SDKs, or cache internals.
- Add `assertions` modules only when reusable fakes, fixtures, recording helpers, or assertion DSLs need to compile against stable API contracts without importing production implementation modules.
- Add `core-app` only for shared Android/Compose app-runtime helpers that are free of feature copy, route policy, analytics policy, repository calls, and screen-specific state.
- Add shared/core modules only for stable, repeated contracts with clear ownership; do not create catch-all common modules.

## Boundary Placement

- Parse route arguments at the `Route` or navigation adapter boundary, then pass typed values into the ViewModel.
- Keep `Context`, `Activity`, `NavController`, permission launchers, `ActivityResultLauncher`, clipboard, files, notifications, sensors, and SDK calls out of stateless composables.
- Keep domain models free of Compose rendering types. Map domain to UI display models before the state reaches `Screen`.
- Keep repositories out of ViewModels only when a use case owns real product orchestration; pass-through use cases are optional, not mandatory.
- Keep data sources behind repositories or adapters. Room, DataStore, Retrofit, files, permissions, and SDK objects should not reach UI state directly.

## Refactor Signals

- Composable directly calls repository or API.
- ViewModel is tied to too many Android framework types.
- UI state is nullable values plus many flags.
- Navigation parsing and business rules are mixed.
- Background work is launched directly from UI without retry or cancellation policy.
- Exported components, WebView bridges, or deep links are added without a security review.
- A feature adds ViewModel state without previews or a visible-state test.
- A shared composable accepts product policy, routes, repositories, or a full screen `UiState` when smaller values would preserve reuse.
