---
keyflow_id: sys_android_module_boundaries
status: review
type: human-reviewed-needed
---

# Android Module Boundary Contracts

Use when deciding where an Android package, module, or source-set
boundary belongs, when distilling a reference app into the current
repo, or when a boundary name no longer tells callers what it owns.

## Package Boundary Artifact

Before creating or moving Android packages, source sets, modules, or
namespaces, write a package boundary note. It must name the owner, allowed
imports, forbidden imports, exported contracts, consumers, and focused
verification.

Android package splits fail review when they only mirror a reference app, create
one folder per type, or move every file into a new package without changing an
import rule. Prefer a flat cohesive package until behavior, dependency
direction, or test ownership requires another boundary.

For `api` / `impl` / `ui` / `assertions` module families:

- `api` owns caller-facing contracts, and navigation identity is one of them:
  the destination type and its arguments, deep-link specs, result types, public
  route events, the `navigateTo<Feature>` action, commands, public models, value
  types, repository ports, provider contracts, and entrypoint interfaces.
  Subpackage only when callers should import one contract family without seeing
  the others.
- `impl` owns feature execution by default: the stateful holder composable,
  ViewModel, screen state, stateless content, UI mappers, feature components,
  previews, UI tests, the destination-to-content binding, and the concrete
  Android entry when one exists — Activity, manifest declaration, Intent
  mapping, Activity result contract, launch handler, SDK entry adapter, and
  their platform DI bindings. It may depend on stable repository or domain
  ports.
- `ui` is the optional reuse extraction, created only when a named consumer
  outside `impl` must reuse the concrete feature surface. Move exactly what that
  consumer needs: the stateless content, its visual models, callbacks or slots,
  and previews when the consumer supplies its own state; the holder composable,
  ViewModel, state, and mappers as well when the consumer needs the working
  feature. It may depend on `api` and on stable ports, never on `impl`. Without
  that named consumer, keep this code in `impl`.
- `assertions` owns reusable test contracts: fixtures, builders, recording
  fakes, assertion subjects, matchers, and contract tests. It depends on `api`
  and must not depend on production `impl` by default.

Minimal shape:

```text
feature/profile/api
  ProfileRoute.kt                 destination type and arguments
  ProfileNavigation.kt            navigateToProfile and deep-link spec
  ProfileEvent.kt
  ProfileRepository.kt
  model/Profile.kt

feature/profile/impl
  ProfileScreen.kt                stateful holder
  ProfileViewModel.kt
  ProfileContent.kt               stateless rendering
  mapper/ProfileUiMapper.kt
  navigation/ProfileSection.kt    binds ProfileRoute to ProfileScreen
  ProfileActivity.kt              only when an Activity entry is required
  ProfileIntentFactory.kt
  ProfileActivityResultContract.kt
  di/ProfileActivityModule.kt

feature/profile/ui                only when a named consumer outside impl
  ProfileScreen.kt                must reuse the concrete surface
  ProfileViewModel.kt
  ProfileContent.kt
  mapper/ProfileUiMapper.kt

feature/profile/assertions
  ProfileFixtures.kt
  RecordingProfileRepository.kt
  ProfileRouteSubject.kt
```

The `api` module exposes what callers need to compile, including everything
required to navigate to the feature. The `impl` module runs it. The optional
`ui` module exists only to let a second consumer render the same surface. The
`assertions` module owns reusable test helpers that compile against `api` and
avoid pulling app, platform entry, network, database, WebView, camera, or other
production implementations into tests.

## Feature API, UI, And Implementation Contract

Do not treat `api`, `impl`, and `ui` as three layers that every feature must
have. `api` plus `impl` is the default pair; `ui` is an extraction, not a layer.
Choose the shape from the entry surface:

| Proven Need | Smallest Feature Shape |
| --- | --- |
| Feature stays local to one module | one unsplit feature module |
| Another module must navigate to, launch, or compile against the feature | `api` + `impl` |
| A named consumer outside `impl` must render the same concrete surface | `api` + `impl` + `ui` |

Ownership rules:

- `api` owns stable caller and navigation identity: the destination type, its
  arguments, deep-link specs, result types, public route events, the
  `navigateTo<Feature>` action, entrypoint interfaces, and the smallest value
  types callers need. Keep it nonvisual by default. A Compose-capable abstract
  entry contract is the explicit exception described in
  [`compose-entry-contracts.md`](compose-entry-contracts.md); it must not become
  a duplicate home for the concrete UI API.
- A module that only navigates to the feature must compile against `api` alone.
  If a caller has to import `impl` or `ui` to reach the destination type, its
  arguments, its deep link, or its result, the routing identity is in the wrong
  module. Splitting `api` out and then leaving navigation in the implementation
  gives callers the implementation dependency the split was supposed to remove.
- `impl` owns the feature as a complete screen-level unit: stateful holder
  composable, ViewModel, `UiState`, actions and effects, domain-to-UI mapping,
  stateless content, feature components, previews, UI/ViewModel tests, and the
  Android entry when one exists. Keep the leaf content composable stateless even
  though `impl` also owns the stateful holder and ViewModel.
- `impl` also owns the binding from the `api` destination to that content — the
  `composable<Route>`/`entry<Route>` builder and the section or entry-provider
  function that registers it. That binding is content, so it cannot live in
  `api`, but it is imported only by the app or host assembly point, never by a
  peer feature that merely navigates.
- `ui` exists only when a named consumer outside `impl` must reuse the same
  concrete surface: a second host, another form factor, a shared container, or
  a test target that must not pull in the Android entry. Whatever moves, `impl`
  delegates to it instead of keeping a second copy. An internal package, a
  preview, or the mere presence of an Activity wrapper is not that consumer.
- When `ui` exists, it is standalone from `impl`: a host can depend on
  `api + ui`, construct the ViewModel with real or fake ports, render previews,
  and run UI/ViewModel tests without importing an Activity, manifest, Intent
  builder, or Activity result adapter. Standalone does not mean the production
  ViewModel has no data dependencies; it means those dependencies are stable
  ports supplied without `impl`.

Keep dependency direction explicit:

```text
navigating caller -> feature api only
host assembly -> feature api + selected feature impl
feature impl -> own feature api + stable repository/domain ports
feature impl -> own feature ui when that ui was extracted
feature ui -> own feature api + stable repository/domain ports
feature api -X-> feature impl or feature ui
feature ui -X-> feature impl
```

A caller that navigates is not by itself a reason to extract `ui`; it is served
by `api`. If the surface becomes domain-free and broadly shared, promote it to
the design system; keep a feature-named or product-specific surface in the
feature module.

Default shape:

```text
feature/profile/api
  ProfileRoute.kt
  ProfileNavigation.kt
  ProfileEvent.kt
  ProfileRepository.kt

feature/profile/impl
  ProfileScreen.kt
  ProfileViewModel.kt
  model/ProfileUiState.kt
  ProfileContent.kt
  mapper/ProfileUiMapper.kt
  component/ProfileCard.kt
  navigation/ProfileSection.kt
  activity/ProfileActivity.kt             only when an Activity entry exists
  activity/ProfileIntentFactory.kt
  activity/ProfileResultContract.kt
  di/ProfileActivityModule.kt
```

Reuse extraction, only once a consumer outside `impl` is named. Move the
stateless half when the consumer brings its own state, and the working feature
when it does not:

```text
feature/profile/ui                      consumer supplies state
  ProfileContent.kt
  model/ProfileUiState.kt
  component/ProfileCard.kt

feature/profile/ui                      consumer needs the working feature
  ProfileScreen.kt
  ProfileViewModel.kt
  ProfileContent.kt
  model/ProfileUiState.kt
  mapper/ProfileUiMapper.kt
  component/ProfileCard.kt
```

`impl` keeps the destination binding and the Android entry, and calls into
`ui` instead of keeping a second copy of what moved.

## Destination And Holder Naming

`Route` is a noun and `navigate` is a verb. Pick one meaning for `Route` in a
repo and do not let the other one reuse the name:

| Owner | Name | Module |
| --- | --- | --- |
| Destination identity and arguments | `ProfileRoute` | `api` |
| Navigation action | `navigateToProfile()` | `api` |
| Deep-link spec, result, public events | `ProfileDeepLink`, `ProfileResult`, `ProfileEvent` | `api` |
| Destination-to-content binding | `profileSection()` / `profileEntries()` | `impl` |
| Stateful holder composable | `ProfileScreen` | `impl`, or `ui` when extracted |
| Stateless rendering surface | `ProfileContent` | `impl`, or `ui` when extracted |

On Navigation 3 the destination type implements the library's `NavKey`; the
name still says what it is, so `ProfileRoute : NavKey` reads correctly and a
separate `ProfileKey` type is redundant. Do not name a destination `NavigateX`
and do not name a composable `XRoute`: a repo that uses `Route` for both the
destination and the holder makes every import ambiguous to the reader, and the
ambiguity is worst in the app module, which imports both.

Example API contract:

```kotlin
@JvmInline
value class ProfileId(val value: String)

@Serializable
data class ProfileRoute(val id: ProfileId)

sealed interface ProfileEvent {
    data class OpenProfile(val id: ProfileId) : ProfileEvent
    data object Back : ProfileEvent
}

interface ProfileRepository {
    suspend fun loadProfile(id: ProfileId): Profile
}
```

The navigation action belongs beside the destination, still in `api`:

```kotlin
fun NavController.navigateToProfile(
    id: ProfileId,
    navOptions: NavOptions? = null,
) = navigate(route = ProfileRoute(id), navOptions = navOptions)
```

A feature that only sends the user to Profile now depends on `api` and nothing
else. Keeping this extension in the implementation module is the common way an
`api` split stops paying for itself.

Example UI state-owner boundary:

```kotlin
@HiltViewModel(assistedFactory = ProfileViewModel.Factory::class)
class ProfileViewModel @AssistedInject constructor(
    @Assisted private val route: ProfileRoute,
    private val repository: ProfileRepository,
    private val noticeSink: NoticeSink,
    private val routeSink: RouteEventSink<ProfileEvent>,
) : ViewModel() {
    private val _state = MutableStateFlow(ProfileUiState())
    val state = _state.asStateFlow()
    init {
        load(route.id)
    }

    fun onAction(action: ProfileAction) {
        when (action) {
            ProfileAction.BackClick -> routeSink.tryEmit(ProfileEvent.Back)
            ProfileAction.RetryClick -> load(route.id)
        }
    }

    private fun load(id: ProfileId) {
        viewModelScope.launch {
            _state.value = repository.loadProfile(id).toUiState()
        }
    }

    @AssistedFactory
    interface Factory {
        fun create(route: ProfileRoute): ProfileViewModel
    }
}
```

The ViewModel belongs beside the screen state it produces. Keep the stateless
surface below the holder boundary:

```kotlin
@Composable
fun ProfileScreen(
    route: ProfileRoute,
    onEvent: (ProfileEvent) -> Unit,
    viewModel: ProfileViewModel = hiltViewModel<
        ProfileViewModel,
        ProfileViewModel.Factory,
    >(
        creationCallback = { factory -> factory.create(route) },
    ),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ProfileContent(state = state, onAction = viewModel::onAction)
}
```

The destination type crosses the module boundary; the holder and the content do
not have to. `ProfileRoute` comes from `api`, and everything else in this file
stays in the module that owns the feature.

Example assertions boundary:

```kotlin
class RecordingProfileRepository : ProfileRepository {
    val requestedIds = mutableListOf<ProfileId>()
    var nextProfile: Profile = ProfileFixtures.profile()

    override suspend fun loadProfile(id: ProfileId): Profile {
        requestedIds += id
        return nextProfile
    }
}

object ProfileFixtures {
    fun profile(id: ProfileId = ProfileId("profile-1")) = Profile(id = id)
}
```

Do not put the fake in the production implementation module only because it is
small. Once more than one test boundary needs it, move it to `assertions` so
tests can depend on the contract and fake without importing the production
screen, DI graph, network stack, or app module.

If the package note cannot explain who imports the package and which import is
forbidden, keep the code in the existing package and only split files by
responsibility.

For external Android skill source routing, also read
`android-external-skill-source-coverage.md`. That manifest is the no-omission
list for source `SKILL.md` and reference documents from the Android, Compose
performance, and Kotlin/Compose skill repositories.

## Reference Project Drill

When using a large Android reference app, copy the boundary lesson, not the
whole shape. Distill the reference into the current repo's scale:

- Keep transferable boundaries such as included `build-logic`, convention
  plugins, feature `api`/implementation splits, design-system modules,
  repository API/implementation splits, domain use cases, and deterministic fake
  or assertion modules.
- Rename plugin ids, packages, modules, and generated namespaces to the target
  repo. Never keep source-project names in shared build or source contracts.
- Drop source-only dependencies such as ads, billing, Firebase, Hilt, KSP,
  generated factories, signing, flavors, analytics, domain-specific SDKs, or
  verification tooling unless the current task explicitly needs them.
- Collapse deep reference folder hierarchies when the target has only one
  product area. A small app often needs `app`, `core:designsystem`,
  `core:model`, `core:domain`, `core:data`, and one feature module before it
  needs dozens of feature/common/holder modules.
- Treat reference code as evidence for module direction and package naming, not
  as authority over state, DI, security, or product policy when repo-local rules
  differ.

## Example-First Boundary Documentation

When a task uses a large reference app or external codebase to design Android
module structure, write an example packet before asking another agent to
implement the shape. The packet must be concrete enough that the agent can copy
the boundary pattern without inventing source names, packages, modules, or
missing contracts.

Include all of these fields:

```text
transferable lesson:
target boundary:
lowest acceptable ownership level:
minimal file/module sketch:
allowed imports:
forbidden imports:
first caller or test:
nearest verification:
collapse rule:
```

Example packet:

```text
transferable lesson: keep the whole navigation contract in api and feature
  execution in impl, and extract ui only for a named outside consumer
target boundary: feature/settings/api + feature/settings/impl
lowest acceptable ownership level: feature-local until a second caller must navigate
minimal file/module sketch: SettingsRoute and navigateToSettings in api;
  SettingsScreen, SettingsViewModel, SettingsContent, settingsSection, and the
  optional SettingsActivity in impl
allowed imports: api -> Kotlin value types + navigation runtime; impl -> own api +
  stable ports + Compose + Android
forbidden imports: api -> Activity, Context, Intent, NavController host wiring,
  concrete screen content; navigating caller -> impl
first caller or test: app route coordinator imports SettingsRoute and
  navigateToSettings only
nearest verification: compile a navigating caller against api alone, then compile
  impl and run its UI/ViewModel tests
collapse rule: if no cross-module caller needs SettingsRoute, keep one feature
  module; add ui only when a named consumer outside impl renders the surface
```

Stop instead of generating structure when the packet cannot name a real caller,
forbidden import, verification path, and collapse rule. In that case keep the
code local, add a TODO with the missing evidence, or ask for the source example
that proves the split. Do not fill gaps by copying a reference app's full module
tree, broad base classes, generated registries, DI graph, or source-specific
package names.

Use examples at these boundaries before creating shared modules:

| Boundary | Minimum Example Required | Collapse Or Stop When |
| --- | --- | --- |
| `feature-api` plus `impl` | One destination/event or public port, the navigate action beside it, one `impl` holder or Activity adapter, and one caller that navigates using `api` alone. | The API has no cross-module caller, or the feature can remain unsplit. |
| Extracted `feature-ui` | The named consumer outside `impl`, the surface it renders, and the reason it must not depend on the Android entry. | Only `impl` renders the surface, or the "consumer" is a preview, an internal package, or the Activity wrapper itself. |
| Repository `api` plus implementation | One stable entity or repository port, one DTO/cache mapper kept inside implementation, one feature or use case caller. | Callers would still import DTOs, SDK types, or concrete data sources. |
| `assertions` module | Fixture, recording fake, and assertion subject that depend on `api` only. | Only one test needs the helper, or the fake imports production `impl`. |
| App-runtime helper | One small contract, one runtime adapter/host, and one caller that should not know Android/Compose details. | The helper starts owning product route policy, repositories, analytics, or screen state. |
| Activity/deep-link route execution | Pure route or plan object, runtime launcher or entry mapping, and explicit Back/Up/result expectation. | The design hides parsing, planning, and execution inside `BaseActivity`. |
| Convention plugin | Two modules sharing the same build setup and one before/after dependency sketch. | Only one module needs the setup or the plugin would encode product behavior. |

## Android Boundary Naming Stops

Module family names are examples, not required names. Do not keep `app`,
`core-app`, `core-ui`, `core-runtime`, `base`, `runtime`, `common`, `shared`, or
"feedback" as a broad Android bucket unless the repo's package layout and
public exports make the concrete capability clear.

Stop and rename or split when any of these happen:

- A caller cannot tell whether a module provides route contracts, route
  execution, Activity launchers, deep-link parsing, notice rendering,
  permissions, WebView runtime, design-system components, or base lifecycle
  setup.
- Pure Kotlin contracts and Android/Compose runtime APIs live in the same
  stable import surface.
- A notice/toast/snackbar/dialog/alert/error surface is hidden behind a vague
  "feedback" module name.
- A `BaseActivity` or `BaseViewModel` becomes the place for product route
  registration, feature screen mapping, repository calls, analytics, permission
  policy, network error copy, and visual component ownership.
- Test fixtures, fakes, assertion subjects, and Activity or repository
  recorders are exported from one catch-all testing file.

Accept broad module names only when the next level is precise. For example, an
existing `core-app` module may contain capability packages such as `activity`,
`route`, `notice`, `permission`, `environment`, `webview`, or `launcher`, but it
must not make all of them available through one grab-bag import.
