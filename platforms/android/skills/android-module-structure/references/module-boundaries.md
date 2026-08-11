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

For `api` / `impl` / `assertions` module families:

- `api` owns caller-facing contracts: route keys, deep-link specs, events,
  commands, public models, value types, repository ports, provider contracts,
  and entrypoint interfaces. Subpackage only when callers should import one
  contract family without seeing the others.
- `impl` owns execution: `NavEntry` or entry-provider builders, route-to-screen
  mapping, Activity launch adapters, ViewModels, screens, DI bindings, SDK
  adapters, mappers, and state holders. Subpackage by behavior owner or
  dependency, not by matching every API file.
- `assertions` owns reusable test contracts: fixtures, builders, recording
  fakes, assertion subjects, matchers, and contract tests. It depends on `api`
  and must not depend on production `impl` by default.

Minimal shape:

```text
feature/profile/api
  ProfileRoute.kt
  ProfileEvent.kt
  ProfileRepository.kt
  model/Profile.kt

feature/profile/impl
  ProfileRouteHolder.kt
  ProfileViewModel.kt
  ProfileScreen.kt
  mapper/ProfileUiMapper.kt
  di/ProfileModule.kt

feature/profile/assertions
  ProfileFixtures.kt
  RecordingProfileRepository.kt
  ProfileRouteSubject.kt
```

The `api` module exposes what callers need to compile. The `impl` module owns
how the feature runs. The `assertions` module owns reusable test helpers that
compile against `api` and avoid pulling app, DI, network, database, WebView,
camera, or other production implementations into tests.

## Feature API, UI, And Implementation Contract

`impl` owns Compose UI by default. It is the feature implementation boundary,
not an Activity-only wrapper. Keep `Route`, `ViewModel`, `UiState`, mapping, DI,
navigation execution, and the feature's `compose/` or `ui/` packages together in
`impl` until a real import boundary proves that one part must move.

Treat `api` and `ui` as independent optional promotions:

| Proven Need | Smallest Feature Shape |
| --- | --- |
| No outside contract or Compose consumer | `impl` |
| Stable caller or navigation contract only | `api` + `impl` |
| Concrete Compose reuse outside the implementation only | `ui` + `impl` |
| Both stable contracts and reusable Compose UI | `api` + `ui` + `impl` |

Ownership rules:

- `api` owns stable caller and navigation identity: route keys, arguments,
  deep-link specs, public events, entrypoint interfaces, and the smallest value
  types callers need. Keep it nonvisual by default. A Compose-capable abstract
  entry contract is the explicit exception described in
  [`compose-entry-contracts.md`](compose-entry-contracts.md); it must not become
  a duplicate home for the concrete reusable UI API.
- Extract `ui` only when a real named consumer outside the implementation must
  render, embed, preview, or Compose-test the concrete feature surface without
  importing `impl`. It owns reusable stateless composables, feature-specific UI
  models, callback or slot contracts, previews, and UI tests.
- `ui` must not own ViewModels, use cases, repositories, domain-to-UI loading
  orchestration, DI registration, `NavEntry` or entry-provider execution,
  Activities, manifests, `Intent` construction, or Activity result handling.
- `impl` owns execution. When `ui` is absent, it also owns `Screen`, feature
  components, and previews. When `ui` is present, `impl` adapts state and events
  to that surface and still owns route holders, ViewModels, mappers, DI,
  navigation registration, and Android entry adapters.
- An Activity that wraps Compose remains in `impl`. The Activity may render a
  surface from `ui`, but needing an Activity does not by itself justify a `ui`
  module.

Keep dependency direction explicit:

```text
app or navigation host -> feature api + selected feature impl
external Compose consumer -> feature ui
feature impl -> own feature api (when present) + own feature ui (when extracted)
feature ui -> own feature api only for stable value/event types when necessary
feature api -X-> feature ui or feature impl
feature ui -X-> feature impl
```

Tests and previews inside `impl` do not count as outside consumers. If the named
consumer disappears, collapse `ui` back into `impl`. If the reusable surface
becomes domain-free and broadly shared, promote it to the design system; keep a
feature-named or product-specific surface in the feature `ui` module.

Optional extracted shape:

```text
feature/profile/api
  ProfileRoute.kt
  ProfileEvent.kt

feature/profile/ui
  ProfileScreen.kt
  model/ProfileUiModel.kt
  component/ProfileCard.kt

feature/profile/impl
  ProfileRouteHolder.kt
  ProfileViewModel.kt
  mapper/ProfileUiMapper.kt
  navigation/ProfileEntryProvider.kt
  activity/ProfileActivity.kt       only when an Activity entry is required
  di/ProfileModule.kt
```

Example API contract:

```kotlin
@JvmInline
value class ProfileId(val value: String)

data class ProfileRoute(val id: ProfileId)

sealed interface ProfileEvent {
    data class OpenProfile(val id: ProfileId) : ProfileEvent
    data object Back : ProfileEvent
}

interface ProfileRepository {
    suspend fun loadProfile(id: ProfileId): Profile
}
```

Example implementation boundary:

```kotlin
class ProfileViewModel(
    private val repository: ProfileRepository,
    private val noticeSink: NoticeSink,
    private val routeSink: RouteEventSink<ProfileEvent>,
) : ViewModel() {
    fun onAction(action: ProfileAction) {
        when (action) {
            ProfileAction.BackClick -> routeSink.tryEmit(ProfileEvent.Back)
            ProfileAction.RetryClick -> load()
        }
    }
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
transferable lesson: keep route contracts pure; execute Activity launches in runtime
target boundary: feature/settings/api + feature/settings/impl + core/route/runtime
lowest acceptable ownership level: feature-local until a second caller needs route data
minimal file/module sketch: SettingsRouteKey in api, SettingsRouteHolder in impl,
  ActivityRouteLauncher in runtime
allowed imports: api -> Kotlin value types; impl -> own api + Compose; runtime -> Android
forbidden imports: api -> Activity, Context, Intent, NavController, Compose UI
first caller or test: app route coordinator imports SettingsRouteKey only
nearest verification: compile api/impl/runtime and run route assertion tests
collapse rule: if no caller needs SettingsRouteKey without impl, keep one feature module
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
| `feature-api` plus implementation | One route key/event or public port, one implementation file, one caller that should avoid implementation dependencies. | The API has no caller without the implementation. |
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
