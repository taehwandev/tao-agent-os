---
keyflow_id: sys_android_di_build_logic
status: review
type: human-reviewed-needed
requires:
  - common/nodes/gradle-convention-plugins.md
  - common/nodes/di-composition-root.md
---

# Android DI And Build Convention Plugins

Use when adding or changing Gradle convention plugins in
`build-logic`, or when placing Hilt bindings, multibindings, and
graph assembly across Android modules.

## Convention Plugin Shape

Shared convention-plugin rules (ownership, test plugins, static-analysis config,
no task without a caller) live in `common/nodes/gradle-convention-plugins.md`.
Android fallback plugin ids when the repo has none:

```text
<repo>.android.application
<repo>.android.library
<repo>.android.library.compose
<repo>.kotlin.library
```

Android specializations to add only after repeated setup proves the need:
repository, Room, test-fixture, screenshot, or feature-implementation
conventions. Android plugins also own SDK versions, namespaces, and Compose
enablement; the Android test convention pairs with a JVM/Kotlin test convention.

## Cleanup Procedure

Follow the cleanup procedure in `common/nodes/gradle-convention-plugins.md`.

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
core/<capability>            runtime bindings such as ActivityRouteLauncher
feature/<name>/impl          feature-owned @IntoSet entries and adapters
core/domain or feature/api   pure contracts with no Hilt dependency
build-logic                  the <repo>.android.hilt convention only
```

Composition-root rules (multibinding over manual lists, injectable set
consumers, qualifiers, searching existing bindings before direct construction,
and that a binding never hides a forbidden edge) live in
`common/nodes/di-composition-root.md`. Apply the Dependency Edge Verification in
[`module-layout.md`](module-layout.md). For single-implementation entry
bindings see [`compose-entry-contracts.md`](compose-entry-contracts.md).

Hilt adoption should remove app-shell manual construction, not only add
annotations to a few handlers. Put environment, network, repository, auth, and
runtime graph decisions in Hilt modules at the boundary that owns the concrete
implementation:

```text
app/di                       BuildConfig config, app-wide repository selection,
                             auth gateway selection, qualified network clients
core/<capability>/di         runtime adapters that need Android APIs
feature/<name>/impl/di       feature-owned @IntoSet handlers and route entries
feature/api or core/domain   pure contracts, no Hilt annotations
```

Activity/AppRoot code follows the entry-code rule in the composition-root node:
inject a small set of coordinators and let Hilt create `@HiltViewModel`
instances through the default Compose/ViewModel integration.

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
- construct production ViewModelProvider factories in the Activity or app root
  after Hilt is the repo baseline
- add Metro beside Hilt without a repo-level migration plan and equivalence test

## Verification

Use the verification order in `common/nodes/gradle-convention-plugins.md`. The
representative module families on Android are application, library, Compose
library, Kotlin library, Hilt, and test, using flavor-qualified task names
where flavors exist.
