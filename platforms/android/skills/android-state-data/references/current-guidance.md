---
keyflow_id: sys_aea75f7837ca
status: review
type: ai-generated
---

# Android State And Data

Use when touching Compose state, ViewModel, Flow, clean architecture layers,
repository contracts, request/response DTOs, entities/domain models,
persistence, network error mapping, server presentation hints, or permissions.

For detailed ViewModel, `UiState`, Flow, repository, use case, persistence, and
one-off event implementation rules, also use `android-viewmodel-state.md`.

For repository module splits, API/implementation boundaries, and DTO/entity
package ownership, also use `android-module-structure.md`.

For Jetpack DataStore persistence, migration, corruption handling, and
Preferences-vs-typed-vs-Room decisions, also read
`android-datastore.md`.

For cross-platform persistence, cache, source-of-truth, storage-tier, migration,
and cleanup rules, also use `common/skills/data-persistence-sync/SKILL.md`.

## Defaults

- Composable renders state and sends events.
- ViewModel owns durable UI state and lifecycle-aware work.
- Use sealed/state models for loading, empty, error, permission denied.
- Separate one-off events from persistent state.
- Repository owns data source coordination and error mapping.
- Room, DataStore, files, permissions, notifications stay behind adapters.
- Platform or heavy resources created by ViewModels, repositories, workers, or
  adapters need an owner and cleanup path for success, failure, cancellation,
  logout, account switch, or permission revoke when relevant.
- Inject dispatchers or schedulers for coroutine tests.
- Use lifecycle-aware collection for UI-observed Flow.
- Version persisted data that can survive app upgrades.
- Use DataStore only for small preference-like or typed settings/state. Use
  Room for large or relational datasets, partial updates, queryable entities,
  or referential integrity.

## Clean Architecture Data Flow

Use this flow when the feature has domain, data, network, cache, permission, or
multi-client pressure:

```text
View emits Action
  -> ViewModel handles Action
  -> UseCase applies product rule when needed
  -> Repository coordinates data sources
  -> DataSource/Network sends Request DTO and receives Response DTO
  -> Mapper converts DTO/cache/database rows into Entity/domain model
  -> ViewModel maps entity or typed failure into UiState and SideEffect
```

Use fewer layers for simple UI, but keep the same direction. The view should not
see request/response DTOs, raw transport responses, database rows, SDK models,
or server error envelopes. Domain code should not import Android UI, Compose,
transport DTOs, persistence rows, or platform SDK types.

## Model Names And Boundaries

Use repo-local naming first, but keep these roles separate:

| Role | Owns | Must Not Own |
| --- | --- | --- |
| `Action` / `UiAction` | User intent from view to ViewModel. | Transport payloads, repositories, direct platform calls. |
| `Request` / `Response` DTO | Network or API wire contract. | UI state, domain policy, Compose annotations. |
| `Entity` / domain model | Stable product data crossing repository/domain boundaries. | Raw HTTP handles, database row annotations unless explicitly a persistence entity, UI callbacks. |
| `UiState` | Durable visible state and interaction availability. | Raw exceptions, DTOs, repositories, one-off commands. |
| `SideEffect` / `Effect` | One-time output such as navigation, snackbar/toast, alert/dialog, permission launch, share, or external activity. | Durable screen data or business rules. |

If a repo uses "entity" for Room rows, name the domain boundary differently
(`DomainModel`, `RepositoryModel`, or a product noun) so persistence rows do not
leak into ViewModels or use cases.

Minimal mapping sample:

```kotlin
// data/network boundary
@Serializable
data class ProfileResponse(
    val id: String,
    val displayName: String,
    val notice: NoticeHintResponse? = null,
)

// repository/domain boundary
data class ProfileEntity(
    val id: ProfileId,
    val displayName: String,
    val noticeHint: NoticeHint? = null,
)

internal fun ProfileResponse.toEntity(): ProfileEntity =
    ProfileEntity(
        id = ProfileId(id),
        displayName = displayName,
        noticeHint = notice?.toDomain(),
    )

// presentation boundary
@Immutable
data class ProfileUiState(
    val title: String,
    val canEdit: Boolean,
)
```

The mapper from `Response` to entity lives in data or repository implementation.
The mapper from entity/failure to `UiState` and `SideEffect` lives in the
ViewModel, reducer, or a presentation mapper owned by the feature
implementation. Do not expose `ProfileResponse`, raw HTTP response handles,
database rows, SDK models, or server envelopes to the ViewModel or UI.

## Repository Boundaries

- Repository `api` modules expose interfaces and stable entities only.
- Repository implementation modules own Retrofit APIs, Room DAOs, DataStore,
  files, SDK clients, request/response DTOs, cache records, and mappers.
- HTTP client response handles, error-body parsing, conversion failures, and
  transport exceptions should be normalized at the API or data-source boundary
  instead of repeated in every feature or ViewModel.
- Feature modules depend on repository APIs or domain use cases, not repository
  implementation packages.
- Map DTO/cache/database models into repository entities before data crosses the
  module boundary.
- Put flavor, dev, fake, or assertion implementations in explicit
  flavor/dev/testing/assertion modules instead of branching through production
  repository contracts.
- Use a domain use case when multiple repositories or product policy must be
  orchestrated; do not add pass-through use cases for one repository call.

## Reflection Deserializer Null Defense

Reflection-based deserializers such as Gson construct objects without running
Kotlin constructors, so DTO fields declared non-null can still be null at
runtime when the server omits or nulls them. Mappers on those paths must
defend non-null declarations:

- `String` and `List` fields: `.orEmpty()`.
- Enum fields: fall back to an explicit default (`?: Default`).
- Nested objects: nullable-receiver mapping (`fun Foo?.toEntity()`), starting
  the `?.` chain at the receiver. Guarding only inner fields still throws one
  level deeper.
- Primitives (`Int`, `Long`, `Boolean`) are filled with `0`/`false` and do not
  throw, but a silent zero can still hide a broken contract; treat suspicious
  zeros as contract questions, not safe values.

Do not use these defaults to hide required-contract violations. When a
required field is missing on a success response, normalize the mapping into a
typed failure with diagnostics instead of papering over it with defaults.
Deserializers that enforce Kotlin nullability at decode time, such as
kotlinx.serialization, do not need this defense; classify the path first.

## DataStore Summary

Use three practical choices:

- `Preferences DataStore`: key-value settings without a stable schema.
- Typed DataStore: Proto, JSON, or another serializer for one immutable typed
  settings object.
- Room instead of DataStore: large/complex data, partial updates, joins,
  referential integrity, or query-heavy storage.

DataStore belongs behind repository/data-source boundaries. Compose observes
ViewModel state; it should not create, read, or write production DataStore
instances directly. Use one DataStore instance per file per process, make the
stored type immutable, decide single-process versus multi-process up front, and
configure migrations/corruption handling when data can survive app upgrades.

## Network Presentation Hints

Server APIs may return client-safe presentation hints such as `none`,
`inline`, `toast`/`snackbar`, `alert`, `full_page`, retry metadata, message keys,
safe fallback text, or an allowlisted deep-link action.

Rules:

- Treat hints as API contract data, not direct UI commands.
- Parse the envelope at the network/data boundary and map it to typed failures,
  metadata, or domain results.
- Let the ViewModel or reducer decide whether the current screen maps the hint
  to `UiState`, a `SideEffect`, or no visible output.
- Keep localization, accessibility behavior, platform control choice, and route
  validity on the client.
- Do not let a server envelope name Android classes, Compose components,
  executable commands, raw HTML, arbitrary JavaScript, or feature implementation
  types.
- Preserve required state updates even when the hint is `none`.

## Check

- Does collection respect lifecycle?
- Can process recreation restore needed state?
- Are navigation args parsed away from business rules?
- Does logout, account switch, or permission change clear cached state?
- Are Room migrations, DataStore changes, and offline cache invalidation covered?
- Are StateFlow, SharedFlow, Channel, and one-off events chosen intentionally?
- Are repository entities separate from DTOs, database rows, SDK models, and UI
  display models?
- Does any feature import a repository implementation package instead of the API
  contract?
- Is the request/response DTO to entity/domain mapper tested?
- Does each ViewModel action produce explicit `UiState` and/or `SideEffect`
  outputs instead of hidden callbacks or raw envelopes?
- Are server presentation hints mapped by the state owner rather than rendered
  directly by network/data code?
