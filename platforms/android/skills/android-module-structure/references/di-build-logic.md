---
keyflow_id: sys_android_di_build_logic
status: review
type: human-reviewed-needed
---

# Android DI And Build Convention Plugins

Use when adding or changing Gradle convention plugins in
`build-logic`, or when placing Hilt bindings, multibindings, and
graph assembly across Android modules.

## Convention Plugin Shape

Use `build-logic` to remove repeated Gradle setup, not to hide product behavior.
A small Android repo usually needs only a few additive convention plugins:

```text
<repo>.android.application
<repo>.android.library
<repo>.android.library.compose
<repo>.kotlin.library
```

Add specialized plugins only after repeated module setup proves the need, such
as repository, Room, test-fixture, screenshot, or feature-implementation
conventions. Keep convention plugins responsible for:

- Android SDK versions, Java/Kotlin targets, test options, namespaces, and
  Compose enablement
- shared dependency bundles already used by multiple modules
- debug-only dependencies such as Compose tooling
- static analysis and test wiring when the repo has those tools configured
- optional Compose compiler reports or metrics when the repo uses them for
  stability diagnosis; keep them opt-in or scoped so normal builds are not noisy

Do not put product routes, DI graph decisions, repository bindings, signing
secrets, flavor policy, generated module discovery, or one-off module behavior
inside a shared convention plugin.

Expose shared test dependency bundles and test runner setup as dedicated test
convention plugins — one for Android modules and one for JVM/Kotlin modules —
rather than as shared configure functions. Higher-level convention plugins
apply the test convention plugin instead of calling the configure helper
directly.

Keep static-analysis rule config at an explicit repo-root tool-config path
(for example `config/<tool>/<tool>.yml`) as the single source of truth, with
per-module baseline files owned by each module. Register rule-set plugin
dependencies in exactly one build-logic owner; do not duplicate them across
plugins or place shared tool config inside the app or a feature module.

## Android DI Build Logic

When an Android repo chooses Hilt, treat it as the default Android DI baseline
until the repo explicitly migrates. Do not mix Hilt and Metro in one object
graph. Metro can be recorded as a future migration candidate only after the repo
accepts the ecosystem, annotation-processing, and migration risk.

Apply DI through a small additive convention plugin instead of repeating Gradle
setup in each module:

```text
<repo>.android.hilt
```

That plugin may own only DI tool wiring:

- apply the Hilt Gradle plugin
- apply the active annotation processor plugin, usually KSP for AGP built-in
  Kotlin projects and KAPT only when the repo already supports KAPT
- add `hilt-android` and the matching Hilt compiler dependency

Keep product bindings out of `build-logic`. Product graph decisions still live
in app, runtime, data, or feature implementation modules through Hilt modules.

Use this placement:

```text
app                         @HiltAndroidApp, @AndroidEntryPoint activities
core/runtime or core-app     runtime bindings such as ActivityRouteLauncher
feature/<name>/impl          feature-owned @IntoSet entries and adapters
core/domain or feature/api   pure contracts with no Hilt dependency
build-logic                  the <repo>.android.hilt convention only
```

Prefer Hilt multibindings for additive registrations such as activity route
launch handlers, route event handlers, deep-link specs, app initializers,
notice renderers, and route entry providers. The app shell should inject a
`Set<Handler>` or registry contract instead of manually constructing
`listOf(FeatureHandler())`.

When a handler set is injected, keep the owner that consumes the set injectable
too. Use a route graph, router factory, coordinator, or registry class with an
`@Inject` constructor instead of a Kotlin `object` that reaches into static
state. Pure route keys and deep-link specs can be `object` values; product graph
assembly and runtime creation should not be object singletons.

Hilt adoption should remove app-shell manual construction, not only add
annotations to a few handlers. Put environment, network, repository, auth, and
runtime graph decisions in Hilt modules at the boundary that owns the concrete
implementation:

```text
app/di                       BuildConfig config, app-wide repository selection,
                             auth gateway selection, qualified network clients
core/runtime/di              runtime adapters that need Android APIs
feature/<name>/impl/di       feature-owned @IntoSet handlers and route entries
feature/api or core/domain   pure contracts, no Hilt annotations
```

Activity/AppRoot code must not call constructors for network clients,
repositories, auth gateways, token providers, credential providers, route
graphs, router factories, or production ViewModel factories. It should inject a
small set of coordinators and let Hilt create `@HiltViewModel` instances through
the default Compose/ViewModel integration. If tests need direct construction,
keep that constructor test-friendly while production still uses Hilt.

Use qualifiers for same-type values such as API URLs, `String` client ids,
network clients, and dispatchers. A module that provides two `NetworkClient`
instances without qualifiers is incomplete even when it compiles by accident in
the current app shape.

Before constructing a configured collaborator directly — `Foo()`,
`Foo { ... }`, or stashed in an `object`, `companion object`, or top-level
`private val` — search for existing bindings of that type: `@Inject`
constructors, `@Provides`, `@Binds`, qualifiers, and current injection
callers. If a binding exists, do not reuse it on type identity alone; verify
the binding's owner and qualifier semantics match the current capability. A
qualifier that owns network-payload serialization policy must not be injected
into an unrelated capability such as a WebView bridge. When the owner differs,
the current implementation owns its own qualified binding or a narrower
encoder/parser contract instead of borrowing another capability's binding.
Only when no binding exists, judge direct creation: a pure value or leaf with
no configuration, identity, lifecycle, I/O, or test-replacement point may be
created at the nearest owner; when configuration changes behavioral meaning or
multiple callers must share one policy, the owning capability provides a
qualified binding; when the type owns lifecycle, resources, or an execution
environment, inject it at the appropriate scope. Wrapping in `private`,
`internal`, or a Kotlin `object` does not make a configured collaborator a
pure value, and locally recreating an already-DI-managed type creates
configuration divergence and test blind spots. Prefer a narrow pure API over a
full configured instance when only one small operation is needed.

Example:

```kotlin
@Module
@InstallIn(ActivityComponent::class)
abstract class ActivityRouteLauncherModule {
    @Binds
    abstract fun bindActivityRouteLauncher(
        impl: DefaultActivityRouteLauncher,
    ): ActivityRouteLauncher
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

Do not:

- make every `core` module a Kotlin-only module by default when the capability
  requires Android context, Activity, Compose, resource, or lifecycle APIs
- put Hilt annotations in pure API modules
- use a singleton object or manual service locator to avoid multibinding
- keep the product route graph or router factory as a Kotlin `object` while
  only the handlers are DI-managed
- keep a central app-shell `listOf(...)` that casts every feature route event
  family, Activity route handler, initializer, or route-entry provider; that
  list becomes a module-boundary failure as soon as growth is expected
- construct network clients, repositories, auth gateways, token providers,
  credential providers, route graphs, router factories, or production
  ViewModelProvider factories in the Activity or app root after Hilt is the
  repo baseline
- add Metro beside Hilt without a repo-level migration plan and equivalence test

