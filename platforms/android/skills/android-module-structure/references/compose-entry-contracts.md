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
| Pure contract API | Route keys, events, value types, repository ports, deep-link specs. | Keep Kotlin-only and free of Android, Compose, Hilt, and Dagger. |
| Compose entry API | A narrow `@Composable` entrypoint interface or composable slot type that callers intentionally compile against. | Apply the Compose compiler plugin and expose only the minimal Compose runtime dependency required by the public signature. |
| Android entry API | Activity route/request keys or another Android capability contract that genuinely needs framework types. | Use an Android library only when the public contract cannot remain platform-free; keep concrete Activities, manifests, and launch execution in implementation. |

A Compose entry API is valid when another module must render, register, swap,
or test a feature surface without importing the feature implementation. The
contract should be an interface or role-sized entry object. A top-level
`@Composable` function with a concrete body is implementation, not merely an
API declaration; keep it in the feature implementation, feature-common, or
design-system owner unless that module intentionally ships reusable UI.

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
or feature implementation dependencies unless the contract actually requires
them.

## Dedicated Feature UI Module

A Compose-capable `api` contract and a feature `ui` module solve different
problems. Use the `api` contract when a host must discover, register, swap, or
invoke an abstract entry without importing its implementation. Use `ui` when a
named consumer outside `impl` must directly reuse the concrete Compose surface.

When `ui` exists:

- Put public stateless composables, visual UI models, callback or slot
  contracts, previews, and UI tests in `ui`.
- Keep route keys, arguments, deep-link specs, public route events, and abstract
  registry entry contracts in `api` when callers need them.
- Keep the entry object implementation, `NavEntry` or provider registration,
  `Route`, `ViewModel`, state loading, mapping, DI, Activity, manifest, Intent,
  and result handling in `impl`.
- Let `impl` depend on `ui`; let `ui` depend on `api` only for stable value or
  event types that are genuinely part of the visual contract. Neither `api`
  nor `ui` may depend on `impl`.

Do not copy the same composable signature into both `api` and `ui`. A dedicated
`ui` module owns the concrete reusable Compose API. Keep a Compose-capable
interface in `api` only when the host needs the abstract registry or replacement
seam itself. An Activity wrapper remains in `impl`; it may call `ui`, but the
wrapper does not make `ui` an Android entry module.

The optional reusable-UI packet is:

```text
api navigation/entry identity (only when cross-module callers need it)
  + ui concrete reusable Compose surface (only when an outside consumer exists)
  -> impl route holder, entry-provider/DI registration, or Activity adapter
  -> selected host depends on impl for execution
  -> focused API compile + UI render + implementation integration verification
```

## Entry Contract Completion Packet

Do not call a new route, Compose entrypoint, Activity entrypoint, provider, or
plugin contract complete after adding only the API declaration. For every
production entry contract, implement the smallest end-to-end packet:

```text
api contract
  -> concrete implementation in impl
  -> implementation-owned DI binding or generated registration
  -> selected host/app variant depends on the implementation module
  -> injected registry/coordinator consumes the binding
  -> focused contract + integration/compile verification
```

For an additive Compose registry, the implementation module can contribute its
entry object while keeping the composable body private to the implementation:

```kotlin
class FeedComposeRouteEntry @Inject constructor() : ComposeRouteEntry {
    override val routeKey: String = FeedRoute.route

    @Composable
    override fun Content(
        route: ComposeRoute,
        onRouteEvent: (RouteEvent) -> Unit,
    ) {
        require(route.route == routeKey)
        FeedRouteHolder(onRouteEvent = onRouteEvent)
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

The host injects a registry or `Set<ComposeRouteEntry>` and hands that object to
the Compose route/holder boundary. Hilt creates the entry objects; Compose still
invokes their `@Composable` methods during composition. Do not describe this as
DI constructing or directly calling a composable function.

Prefer `@IntoMap` when a stable unique route key can be encoded as a compile-time
Dagger map-key annotation value, such as `@StringKey("feed")` or a custom
`@MapKey`. A runtime `routeKey` property cannot itself provide the Dagger map
key. Use `@IntoSet` when keys are available only at runtime, then have the
registry immediately index exact keys and reject duplicate registrations. Never
depend on `Set` iteration order or silently choose the first matching entry.
Missing and duplicate entry keys need explicit failure behavior and tests.

For Activity-backed entries:

- Keep route/request data and stable lookup keys in the API boundary.
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

Standalone access means a host can depend on the API plus one selected
implementation and reach the surface through the route/entry contract. It does
not mean a feature API can execute without an implementation on the runtime
classpath. Provide fake or preview implementations for tests when useful, and
fail clearly when a production host omits a required entry.

Minimum verification for a new entry packet:

- compile the API module with its declared public Compose/Android surface
- compile the implementation and the smallest host that selects it
- prove the DI graph contains the implementation binding
- test registry behavior for a known route, unknown route, and duplicate key
- render/preview or Compose-test the concrete composable entry when UI changed
- test Activity route-to-Intent/handler behavior and manifest inclusion when an
  Activity entry changed
- confirm callers import the API/registry contract rather than the concrete
  screen or Activity class
