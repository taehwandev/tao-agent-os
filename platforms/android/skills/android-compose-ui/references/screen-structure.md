---
keyflow_id: sys_android_compose_screen_structure
status: review
type: human-reviewed-needed
---

# Compose Screen And Package Structure

Use when building a new screen, choosing an architecture track, or deciding where composables, previews and modules live.

Split out of `current-guidance.md`, which keeps the Compose
authoring contract every UI change applies.

## Screen And Content Template

For a ViewModel-backed Compose screen, generate or review both the holder and the
stateless content. Replace `hiltViewModel()` with the repo's DI pattern.

```kotlin
@Composable
fun ProfileScreen(
    onBack: () -> Unit,
    onOpenEditor: (ProfileId) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ProfileViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    LifecycleStartEffect(viewModel) {
        val collectJob = this.lifecycleScope.launch {
            viewModel.effects.collect { effect ->
                when (effect) {
                    ProfileEffect.NavigateBack -> onBack()
                    is ProfileEffect.OpenEditor -> onOpenEditor(effect.id)
                    is ProfileEffect.ShowSnackbar -> {
                        snackbarHostState.showSnackbar(effect.message.text)
                    }
                }
            }
        }

        onStopOrDispose {
            collectJob.cancel()
        }
    }

    ProfileContent(
        state = state,
        onAction = viewModel::onAction,
        snackbarHostState = snackbarHostState,
        modifier = modifier,
    )
}
```

```kotlin
@Composable
fun ProfileContent(
    state: ProfileUiState,
    onAction: (ProfileAction) -> Unit,
    modifier: Modifier = Modifier,
    snackbarHostState: SnackbarHostState = remember { SnackbarHostState() },
) {
    Scaffold(
        modifier = modifier,
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { contentPadding ->
        when (val status = state.status) {
            ProfileStatus.Loading -> ProfileLoading(
                modifier = Modifier.padding(contentPadding),
            )
            ProfileStatus.Empty -> EmptyState(
                onRetryClick = { onAction(ProfileAction.RetryClick) },
                modifier = Modifier.padding(contentPadding),
            )
            is ProfileStatus.Error -> ErrorState(
                message = status.message,
                onRetryClick = { onAction(ProfileAction.RetryClick) },
                modifier = Modifier.padding(contentPadding),
            )
            ProfileStatus.PermissionDenied -> PermissionDeniedState(
                modifier = Modifier.padding(contentPadding),
            )
            is ProfileStatus.Content -> ProfileDetail(
                profile = status.profile,
                canEdit = state.canEdit,
                onBackClick = { onAction(ProfileAction.BackClick) },
                onEditClick = { onAction(ProfileAction.EditClick) },
                modifier = Modifier.padding(contentPadding),
            )
        }
    }
}
```

Rules for applying this template:

- The `Screen` holder may know ViewModel, lifecycle collection, navigation
  outputs, permission launchers, activity results, and snackbar/focus effects.
- `Content` must be previewable without DI, ViewModel, navigation, database,
  network, or platform services.
- Leaf components should receive the smallest model or values they need, not the
  whole screen `UiState`.
- If a callback count becomes noisy, introduce a typed `UiAction`; do not pass a
  ViewModel into the screen to reduce parameters.
- Keep `modifier` on the public composable and apply it to the root layout once.

## Architecture Tracks

Choose the smallest track that makes ownership clear:

| Track | Use When | Shape |
| --- | --- | --- |
| Simple Compose | Local interaction only, no async data or product workflow. | `Composable -> local remember state` |
| MVVM | Loading, forms, async fetch, permission state, navigation output, or reusable screen logic. | `Screen holder -> ViewModel -> Content` |
| Clean Architecture | Domain policy, offline/sync, auth/tenant/billing, multiple clients, or complex test boundary. | `Screen holder -> ViewModel -> UseCase -> Repository -> DataSource` |
| Reducer/MVI | Many events, replayable transitions, optimistic updates, or concurrency races. | `Screen holder -> ViewModel/Store -> Reducer -> Effects/UseCases` |

Do not add use cases, repositories, reducers, or modules only for ceremony. Add
them when they isolate a real product rule, side effect, or test boundary.

## Package Structure

Use package names that reveal ownership and dependency direction. A typical
feature implementation can use:

```text
feature/<name>/impl/src/main/.../<name>/
  <Name>Screen.kt       stateful holder and lifecycle wiring
  <Name>Content.kt      stateless screen content
  <Name>ViewModel.kt    UI state owner
  <Name>UiState.kt      state, actions, effects, UI models
  navigation/           binds the api destination to this content
  components/           feature-local reusable pieces
  preview/              shared preview providers only when reused across files
```

This `impl` layout is the default even when it contains `compose/` or `ui/`
packages. A separate `feature/<name>/ui` Gradle module is optional: create it
only when a named consumer outside the implementation must reuse the concrete
Compose surface. Move the stateless composables, their smallest visual models
and callbacks or slots, previews, and UI tests, and move the `Screen` holder,
`ViewModel`, and mapping as well when that consumer needs the working feature;
keep DI, the destination binding, Activity, and Intent/result handling in
`impl`. The destination type and its navigate action live in
`feature/<name>/api`, not here. The canonical module contract lives in
`../../android-module-structure/references/module-boundaries.md`.

Use `components/` for feature-local pieces and promote only stable visual
contracts to a shared design-system module. Shared design-system modules can use:

```text
core/designsystem/.../theme/
core/designsystem/.../tokens/
core/designsystem/.../components/
core/designsystem/.../components/<domain-free-group>/
core/designsystem/.../preview/
```

Keep generated resources, route contracts, domain models, repositories, and fake
services outside shared UI component packages unless the repo documents a more
specific boundary.

Design-system modules should own theme, semantic tokens, typography, shapes,
component defaults, accessibility semantics, and domain-free primitives. Feature
modules should own product copy, route events, analytics labels, permission
policy, domain-to-UI mapping, and feature-only cards or sections.

When a repo has design-system wrappers, feature modules should prefer those
wrappers over direct Material, platform, or third-party UI primitives. Direct
imports of raw UI primitives belong primarily inside the design system, or in a
feature-local one-off with a clear reason to avoid promotion.

## Reuse Decision

Before moving Compose UI into a shared package, ask:

- Is there a named module outside the feature implementation that must import
  this concrete Compose surface?
- Is this a design-system primitive, a feature product component, or just a local
  screen section?
- Can the component be named without the original screen or feature name?
- Are product copy, route events, analytics, permissions, and business rules
  still owned by the caller?
- Can previews demonstrate the reusable states without feature setup?
- Will extraction reduce duplicated fixes without creating a flag-heavy API?
- Does the shared API use semantic tokens and slots instead of leaking one
  feature's exact colors, padding, copy, or route policy?

If the answer is no, keep it local or in feature common rather than promoting it
to the design system.

When the surface remains feature-specific but has that outside consumer, put it
in the feature `ui` module. When it is domain-free and broadly reusable, put it
in the design system. When neither condition is true, keep it inside `impl`.
