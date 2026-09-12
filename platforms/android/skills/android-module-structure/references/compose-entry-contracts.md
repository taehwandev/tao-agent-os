---
keyflow_id: sys_android_compose_entry_contracts
status: review
type: human-reviewed-needed
---

# Android Compose And Entry Contract Boundaries

Use when an Android `api` module exposes a Compose or Android entry
contract, or when completing a route, Compose entrypoint, Activity
entrypoint, provider, or plugin contract end to end.

## Compose-Capable API Boundaries

`api` describes the caller-facing contract; it does not automatically mean
pure Kotlin. Choose the API module type from the imports that the public
contract intentionally exposes:

| API Boundary | Public Surface | Module Rule |
| --- | --- | --- |
| Pure contract API | Destination types, navigate actions, events, value types, repository ports, deep-link specs. | Keep Kotlin-only and free of Android, Compose, Hilt, and Dagger, or add only the navigation runtime the destination type and navigate action require. |
| Compose entry API | A narrow `@Composable` entrypoint interface or composable slot type that callers intentionally compile against. | Apply the Compose compiler plugin and expose only the minimal Compose runtime dependency required by the public signature. |
| Android entry API | Activity route/request keys or another Android capability contract that genuinely needs framework types. | Use an Android library only when the public contract cannot remain platform-free; keep concrete Activities, manifests, and launch execution in implementation. |

A Compose entry API is valid when another module must render, register, swap,
or test a feature surface without importing its concrete Compose UI. The
contract should be an interface or role-sized entry object. A top-level
`@Composable` function with a concrete body is implementation, not merely an
API declaration; keep it in the feature's `impl` (or its extracted `ui`),
feature-common, or design-system owner.

Example caller contract in a Compose-capable API boundary:

```kotlin
interface ComposeRouteEntry {
    val routeKey: String

    @Composable
    fun Content(
        route: ComposeRoute,
        onRouteEvent: (RouteEvent) -> Unit,
    )
}
```

Keep the contract narrow. Prefer a feature-specific entrypoint when a generic
contract would require a fat host context, unrelated callbacks, unsafe casts,
or cross-feature state. Do not pass `Activity`, `Context`, `NavController`,
repositories, DI containers, service locators, or product graph policy merely
to make every screen fit one interface.

If `@Composable`, `Modifier`, or another Compose type appears in a public
signature, the declaring API module must be Compose-enabled. Consumers that
declare or call composable code also need the Compose compiler plugin, and every
consumer needs the minimal Compose annotation/runtime types on its compile
classpath when they are part of the ABI. Export that minimal dependency through
the build system, but do not expose Material, navigation, lifecycle, ViewModel,
or concrete UI/platform implementation dependencies unless the contract requires
them.

## Optional Feature UI Module

A Compose-capable `api` contract and a feature `ui` module solve different
problems. Use the `api` contract when a host must discover, register, swap, or
invoke an abstract entry. Use `ui` only when a named consumer outside `impl`
must render the same concrete screen-level surface.

By default there is no `ui` module: the holder, ViewModel, content, and the
destination-to-content binding all live in `impl` beside the Android entry.

When a second consumer forces the extraction:

- Move what that consumer reuses into `ui`: the stateless content, visual UI
  models, callbacks or slots, and previews when it supplies its own state; the
  holder composable, ViewModel, UI state/actions/effects, UI mapping, and
  UI/ViewModel tests as well when it needs the working feature.
- Keep destination types, arguments, deep-link specs, navigate actions, public
  route events, and abstract registry entry contracts in `api`.
- Keep the destination-to-content binding, the Compose `NavEntry` or entry
  provider, and the Android platform entry in `impl`: concrete Activity,
  manifest, Intent/request/result mapping, Activity launcher, SDK entry adapter,
  and platform DI.
- Let `ui` depend on `api` and stable repository/domain ports. Let `impl`
  depend on both `api` and `ui`. Neither `api` nor `ui` may depend on `impl`.

Do not copy the same composable signature into both `api` and `ui`. The module
that owns the content owns the concrete Compose API. Keep a Compose-capable
interface in `api` only when the host needs an abstract registry or replacement
seam. An Activity wrapper stays in `impl` and delegates; it does not own a
second holder or ViewModel.

The default packet is:

```text
api destination + navigate action + result
  + impl holder Screen + ViewModel + stateless Content + entry binding
  -> a navigating caller compiles against api alone
  -> focused API compile + UI run/render + optional Activity integration verification
```

The extraction packet adds one step and changes no dependency direction:

```text
api destination + navigate action + result
  + ui holder Screen + ViewModel + stateless Content
  + impl entry binding + Activity/Intent/result execution, calling ui
  -> the named second consumer compiles against api + ui without impl
```

## Entry Contract Completion Packet

Do not call a new route, Compose entrypoint, Activity entrypoint, provider, or
plugin contract complete after adding only the API declaration. For every
production entry contract, implement the smallest end-to-end packet:

```text
api contract
  -> concrete Compose entry in impl, or in ui once extracted
  -> selected Compose host depends on api + the module that owns the entry
  -> Activity implementation depends on api and on ui when one exists
  -> focused contract + UI + optional platform integration verification
```

For an additive Compose registry, the content module contributes its entry
object and keeps the holder beside the ViewModel:

```kotlin
class FeedComposeRouteEntry @Inject constructor() : ComposeRouteEntry {
    override val routeKey: String = FeedRoute.ROUTE_KEY

    @Composable
    override fun Content(
        route: ComposeRoute,
        onRouteEvent: (RouteEvent) -> Unit,
    ) {
        require(route.route == routeKey)
        FeedScreen(onRouteEvent = onRouteEvent)
    }
}

@Module
@InstallIn(ActivityComponent::class)
abstract class FeedComposeRouteEntryModule {
    @Binds
    @IntoSet
    abstract fun bindFeedComposeRouteEntry(
        impl: FeedComposeRouteEntry,
    ): ComposeRouteEntry
}
```

The host injects a registry or `Set<ComposeRouteEntry>` from the selected
content modules and hands that object to the Compose navigation boundary. Hilt creates the entry
objects; Compose still invokes their `@Composable` methods during composition.
Do not describe this as DI constructing or directly calling a composable
function.

Prefer `@IntoMap` when a stable unique route key can be encoded as a compile-time
Dagger map-key annotation value, such as `@StringKey("feed")` or a custom
`@MapKey`. A runtime `routeKey` property cannot itself provide the Dagger map
key. Use `@IntoSet` when keys are available only at runtime, then have the
registry immediately index exact keys and reject duplicate registrations. Never
depend on `Set` iteration order or silently choose the first matching entry.
Missing and duplicate entry keys need explicit failure behavior and tests.

## Navigation 3 Entry Provider Contract

When the project uses Navigation 3, do not hand-roll the registry above. The
library owns the contribution seam and fixes its shape. The destination type
stays in `api`, and the feature contributes entries through an extension on
`EntryProviderScope<NavKey>` that lives with the content:

```kotlin
// feature/profile/api
@Serializable
data class ProfileRoute(val id: ProfileId) : NavKey

// feature/profile/impl, or feature/profile/ui once extracted
// androidx.navigation3.runtime.EntryProviderScope
// androidx.navigation3.runtime.NavKey

fun EntryProviderScope<NavKey>.profileEntries(
    onResult: (ProfileResult) -> Unit,
) {
    entry<ProfileRoute> { route ->
        ProfileScreen(route = route, onResult = onResult)
    }
}
```

Only the host that assembles the graph imports `profileEntries`. A peer feature
that sends the user to Profile imports `ProfileRoute` from `api` and nothing
else.

`entry<Route>` performs the destination dispatch, so the duplicate-key indexing
the hand-rolled registry needs is the library's job here. Collect contributions
as function values rather than as entry objects:

```kotlin
@Module
@InstallIn(ActivityRetainedComponent::class)
object ProfileNavigationModule {
    @IntoSet
    @Provides
    fun provideProfileEntries(): EntryProviderScope<NavKey>.() -> Unit = {
        profileEntries(onResult = {})
    }
}
```

A result callback that depends on host state does not belong in this provider.
Pass it where the host composes `entryProvider`, not through the DI graph.

The host supplies `backStack`, `onBack`, `entryDecorators`, and `entryProvider`.
`onBack` takes no argument:

```kotlin
NavDisplay(
    backStack = backStack,
    onBack = { backStack.removeLastOrNull() },
    entryDecorators = listOf(
        rememberSaveableStateHolderNavEntryDecorator(),
        rememberViewModelStoreNavEntryDecorator(),
    ),
    entryProvider = entryProvider {
        profileEntries(onResult = ::onProfileResult)
    },
)
```

Decorator order is a contract, not a style choice. Unless a decorator supplies
its own `SaveableStateProvider`,
`rememberSaveableStateHolderNavEntryDecorator()` must be first in the list.
`rememberViewModelStoreNavEntryDecorator()` is what gives each entry its own
`ViewModelStore`; without it, entries share one store and a per-key ViewModel is
not per-key. It ships in `androidx.lifecycle:lifecycle-viewmodel-navigation3`,
a dependency separate from the navigation3 runtime. The two mistakes fail at
different times and are diagnosed differently: an absent dependency makes the
function an unresolved reference and the module stops compiling, while a present
dependency whose decorator was never added to `entryDecorators` compiles and
then shares one store at runtime. Check the dependency and the registration as
two separate things.

The `NavKey` type belongs to the navigation library, so an `api` module that
declares the destination takes a dependency on the navigation runtime. When the
public contract must stay free of it, keep a plain Kotlin value in `api` and let
an app adapter convert it; either way the destination must not reference
`Activity`, `Intent`, `NavController` host wiring, or concrete screen content.

### Module Naming Against The Official Guide

The official modularization guide places the destination in `api` and both the
`NavEntry` and its content in `impl`. This skill agrees:

```text
official guide: impl(content) -> api
this skill:     impl(content, Activity) -> api
                impl -> ui(content) -> api, only after a reuse consumer is named
```

Do not migrate a project only to rename modules. Check instead that the
destination contract imports no content, that a navigating caller compiles
against `api` alone, and that any Activity adapter sits outside the screen
content rather than beside it.

Verification for a Navigation 3 entry packet:

- compile a navigating caller against `api` alone
- compile the feature's entry extension against `api + impl`, or against
  `api + ui` with no `impl` once the reuse extraction exists
- prove each destination reaching one host has exactly one `entry<Route>`
- prove `rememberSaveableStateHolderNavEntryDecorator()` is first wherever a
  ViewModel store decorator is used
- prove a per-key ViewModel is not shared between two entries of different keys,
  which is a runtime check and not answered by the module compiling

For Activity-backed entries:

- Keep the destination type, request data, and the launch action in the API
  boundary, so a caller that only starts the Activity never imports it.
- Keep the concrete `Activity`, manifest declaration, `Intent` construction,
  result handling, and `ActivityRouteLaunchHandler` in the implementation.
- Let Android create the Activity. Mark it `@AndroidEntryPoint` when it needs
  injected dependencies; do not bind or construct the Activity as a normal DI
  service.
- Use `ActivityComponent` for Activity-dependent handlers or adapters that need
  Activity context or window access. Component scope controls injected object
  lifetime; it does not make the component a `LifecycleOwner`, Compose state
  owner, or Activity Result registration owner. Keep lifecycle-bound state,
  cleanup, and result registration with the actual Activity or composition
  lifecycle owner. Use process scope only for pure registries or factories that
  retain no Activity/Compose state.
- Inject a factory or registrar when Activity Result registration is required;
  register the launcher from the Activity/Compose lifecycle owner at the
  lifecycle-safe time instead of injecting a pre-registered launcher globally.
- Ensure the selected app/host includes the implementation dependency so Hilt
  aggregation and manifest merging can discover the binding and Activity.

Standalone navigation access means any caller can depend on `api` alone and
reach the surface through the destination and navigate contract without the
feature's `impl`. Standalone *UI* access is the narrower property the extracted
`ui` module adds: a second consumer can depend on `api + ui` and render the
surface without the Activity entry. The ViewModel may still require repository
or domain ports; the host provides production bindings and previews or tests
provide fakes. Fail clearly when a production host omits a required port or
entry.

Minimum verification for a new entry packet:

- compile the API module with its declared public Compose/Android surface
- compile a navigating caller against `api` alone
- compile the content module and the smallest Compose host that selects it
- prove the DI graph contains the entry and ViewModel dependencies
- test registry behavior for a known route, unknown route, and duplicate key
- render/preview or Compose-test the concrete composable entry when UI changed
- test Activity route-to-Intent/handler behavior and manifest inclusion when an
  Activity entry changed
- confirm callers import the API contract rather than the concrete Activity
  class or the content module
