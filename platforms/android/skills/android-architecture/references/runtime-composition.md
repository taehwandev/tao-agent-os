---
keyflow_id: sys_android_runtime_composition
status: review
type: ai-generated
---

# Android Runtime Composition

Use when wiring Hilt scopes, modules, qualifiers, or the entry points that assemble Compose screens and activities.

Split out of `current-guidance.md`, which keeps the boundary
contract every Android change applies.

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
