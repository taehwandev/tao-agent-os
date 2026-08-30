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

For `api` / `ui` / `impl` / `assertions` module families:

- `api` owns caller-facing contracts: route keys, deep-link specs, events,
  commands, public models, value types, repository ports, provider contracts,
  and entrypoint interfaces. Subpackage only when callers should import one
  contract family without seeing the others.
- `ui` owns Compose execution: `NavEntry` or entry-provider builders for the
  Compose destination, holder `Route` composables, ViewModels, screen state,
  screens, UI mappers, feature components, previews, UI tests, and the narrow
  DI wiring needed to construct those UI owners. It may depend on stable
  repository or domain ports, but not on the feature's platform `impl`.
- `impl` is the optional platform-entry adapter: concrete Activities, manifest
  declarations, Intent mapping, Activity result contracts, launch handlers,
  SDK entry adapters, and their platform DI bindings. It may depend on `api`
  and `ui`; `ui` must be able to compile and run without it.
- `assertions` owns reusable test contracts: fixtures, builders, recording
  fakes, assertion subjects, matchers, and contract tests. It depends on `api`
  and must not depend on production `impl` by default.

Minimal shape:

```text
feature/profile/api
  ProfileKey.kt
  ProfileEvent.kt
  ProfileRepository.kt
  model/Profile.kt

feature/profile/ui
  ProfileRoute.kt
  ProfileViewModel.kt
  ProfileScreen.kt
  mapper/ProfileUiMapper.kt
  navigation/ProfileEntryProvider.kt

feature/profile/impl              only when an Activity entry is required
  ProfileActivity.kt
  ProfileIntentFactory.kt
  ProfileActivityResultContract.kt
  di/ProfileActivityModule.kt

feature/profile/assertions
  ProfileFixtures.kt
  RecordingProfileRepository.kt
  ProfileRouteSubject.kt
```

The `api` module exposes what callers need to compile. The `ui` module owns the
complete Compose feature. The optional `impl` module lets Android enter that
feature through an Activity or another platform shell. The `assertions` module
owns reusable test helpers that compile against `api` and avoid pulling app,
platform entry, network, database, WebView, camera, or other production
implementations into tests.

## Feature API, UI, And Implementation Contract

Do not treat `api`, `ui`, and `impl` as three layers that every feature must
have. Choose the shape from the entry surface:

| Proven Need | Smallest Feature Shape |
| --- | --- |
| Feature stays local to one module | one unsplit feature module |
| Host navigates directly to a reusable Compose feature | `api` + `ui` |
| Host launches an Activity and there is no reusable Compose surface | `api` + `impl` |
| Activity wraps a Compose feature that other hosts can also use | `api` + `ui` + `impl` |

Ownership rules:

- `api` owns stable caller and navigation identity: route keys, arguments,
  deep-link specs, public events, entrypoint interfaces, and the smallest value
  types callers need. Keep it nonvisual by default. A Compose-capable abstract
  entry contract is the explicit exception described in
  [`compose-entry-contracts.md`](compose-entry-contracts.md); it must not become
  a duplicate home for the concrete reusable UI API.
- `ui` owns the reusable Compose feature as a complete screen-level unit:
  holder `Route`, ViewModel, `UiState`, actions and effects, domain-to-UI
  mapping, `Screen`, feature components, Compose entry or `NavEntry` mapping,
  previews, and UI/ViewModel tests. Keep the leaf `Screen` stateless even
  though the `ui` module also owns the stateful holder and ViewModel.
- `ui` is standalone from the feature's `impl`: a Compose host can depend on
  `api + ui`, navigate to the feature, construct the ViewModel with real or
  fake ports, render previews, and run UI/ViewModel tests without importing an
  Activity, manifest, Intent builder, or Activity result adapter. Standalone
  does not mean the production ViewModel has no data dependencies; it means
  those dependencies are stable ports supplied without `impl`.
- `impl` owns only the additional platform entry. An Activity-backed
  implementation reads or writes Intents and results, owns the manifest and
  platform DI binding, and delegates the actual screen to `ui` when that UI is
  reusable. It must not become a second home for the ViewModel or screen.
- When no Compose surface exists, `api + impl` is sufficient. When Compose is
  the direct entry and no Activity is needed, `api + ui` is sufficient.

Keep dependency direction explicit:

```text
Compose host -> feature api + feature ui
Activity host -> feature api + selected feature impl
feature impl -> own feature api + own feature ui when it wraps Compose
feature ui -> own feature api + stable repository/domain ports
feature api -X-> feature ui or feature impl
feature ui -X-> feature impl
```

The host that navigates directly to the Compose feature is a valid `ui`
consumer; it does not need an Activity wrapper merely to justify the module.
If the surface becomes domain-free and broadly shared, promote it to the design
system; keep a feature-named or product-specific surface in the feature `ui`
module.

Optional extracted shape:

```text
feature/profile/api
  ProfileKey.kt
  ProfileEvent.kt
  ProfileRepository.kt

feature/profile/ui
  ProfileRoute.kt
  ProfileViewModel.kt
  model/ProfileUiState.kt
  ProfileScreen.kt
  mapper/ProfileUiMapper.kt
  component/ProfileCard.kt
  navigation/ProfileEntryProvider.kt

feature/profile/impl              only when an Activity entry is required
  activity/ProfileActivity.kt
  activity/ProfileIntentFactory.kt
  activity/ProfileResultContract.kt
  di/ProfileActivityModule.kt
```

Example API contract:

```kotlin
@JvmInline
value class ProfileId(val value: String)

data class ProfileKey(val id: ProfileId)

sealed interface ProfileEvent {
    data class OpenProfile(val id: ProfileId) : ProfileEvent
    data object Back : ProfileEvent
}

interface ProfileRepository {
    suspend fun loadProfile(id: ProfileId): Profile
}
```

Example UI state-owner boundary:

```kotlin
@HiltViewModel(assistedFactory = ProfileViewModel.Factory::class)
class ProfileViewModel @AssistedInject constructor(
    @Assisted private val key: ProfileKey,
    private val repository: ProfileRepository,
    private val noticeSink: NoticeSink,
    private val routeSink: RouteEventSink<ProfileEvent>,
) : ViewModel() {
    private val _state = MutableStateFlow(ProfileUiState())
    val state = _state.asStateFlow()
    init {
        load(key.id)
    }

    fun onAction(action: ProfileAction) {
        when (action) {
            ProfileAction.BackClick -> routeSink.tryEmit(ProfileEvent.Back)
            ProfileAction.RetryClick -> load(key.id)
        }
    }

    private fun load(id: ProfileId) {
        viewModelScope.launch {
            _state.value = repository.loadProfile(id).toUiState()
        }
    }

    @AssistedFactory
    interface Factory {
        fun create(key: ProfileKey): ProfileViewModel
    }
}
```

The ViewModel belongs beside the screen state it produces. Keep the stateless
screen below the holder boundary:

```kotlin
@Composable
fun ProfileRoute(
    key: ProfileKey,
    onEvent: (ProfileEvent) -> Unit,
    viewModel: ProfileViewModel = hiltViewModel<
        ProfileViewModel,
        ProfileViewModel.Factory,
    >(
        creationCallback = { factory -> factory.create(key) },
    ),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    ProfileScreen(state = state, onAction = viewModel::onAction)
}
```

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
transferable lesson: keep navigation identity in api, Compose execution in ui,
  and optional Activity execution in impl
target boundary: feature/settings/api + feature/settings/ui + feature/settings/impl
lowest acceptable ownership level: feature-local until a second caller needs route data
minimal file/module sketch: SettingsKey in api, SettingsRoute and SettingsViewModel
  in ui, SettingsActivity and Intent mapping in impl
allowed imports: api -> Kotlin value types; ui -> own api + stable ports + Compose;
  impl -> own api + own ui + Android
forbidden imports: api -> Activity, Context, Intent, NavController, Compose UI
first caller or test: app route coordinator imports SettingsKey only
nearest verification: compile api/ui, run UI/ViewModel tests, and compile impl only
  when the Activity entry is selected
collapse rule: if no cross-module caller needs SettingsKey, keep one feature module;
  if no Activity entry exists, omit impl
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
| `feature-api` plus UI or platform implementation | One key/event or public port, one `ui` Route/ViewModel or `impl` Activity adapter, and one caller that should avoid the other implementation boundary. | The API has no cross-module caller, or the feature can remain unsplit. |
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
