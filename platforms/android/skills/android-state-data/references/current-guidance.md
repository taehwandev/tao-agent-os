---
keyflow_id: sys_aea75f7837ca
status: review
type: ai-generated
---

# Android State And Data

Rules for the data side of an Android feature: layer direction, model roles,
request/response DTOs, field nullability, mappers, repository contracts,
persistence choice, and server presentation hints.

Related cards (paths resolve from this file):

- ViewModel, `UiState`, Flow, effects, and error-to-UI mapping:
  [android-viewmodel-state](../../android-viewmodel-state/SKILL.md).
- Module splits, API/implementation boundaries, DTO/entity package ownership:
  [android-module-structure](../../android-module-structure/SKILL.md).
- Jetpack DataStore persistence, migration, corruption handling:
  [android-datastore.md](android-datastore.md).
- Cross-platform persistence, cache, source of truth, storage tiers, cleanup:
  [data-persistence-sync](../../../../../common/skills/data-persistence-sync/SKILL.md).

## Detect The Repo's Conventions First

Before writing a DTO, mapper, or repository method, read two or three
neighbouring examples and record:

- **Serializer**: kotlinx.serialization, Moshi (codegen or Kotlin reflection
  adapter), or Gson. This decides whether non-null declarations are enforced at
  decode time (see [Deserializer Classes](#deserializer-classes)).
- **Result convention**: an existing typed result wrapper (`Result`, an
  app-specific `ApiResult`/`NetworkResult`, `Either`) or typed exceptions.
- **Naming and packages**: `XxxRequest`/`XxxResponse`/`XxxDto`, `Entity` vs
  `DomainModel`, where mappers live.

Follow what exists. The defaults below apply only where the repo has no
convention, and a small fix or endpoint addition keeps the current path even if
it differs from these defaults. Redesign the stack only when the task is about
it.

## Defaults

- Composable renders state and sends actions; ViewModel owns durable UI state
  and lifecycle-aware work.
- Model loading, empty, error, and permission-denied outcomes visibly; choose
  the status shape with the decision in
  [android-viewmodel-state](../../android-viewmodel-state/SKILL.md).
- Separate one-off effects from persistent state.
- Repository owns data-source coordination and failure normalization.
- Room, DataStore, files, permissions, notifications stay behind adapters.
- Platform or heavy resources created by ViewModels, repositories, workers, or
  adapters need an owner and cleanup path for success, failure, cancellation,
  logout, account switch, or permission revoke when relevant.
- Inject dispatchers or schedulers for coroutine tests.
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
  -> ViewModel maps entity or typed failure into UiState and Effect
```

Use fewer layers for simple UI, but keep the same direction. The view never
sees request/response DTOs, raw transport responses, database rows, SDK models,
or server error envelopes. Domain code does not import Android UI, Compose,
transport DTOs, persistence rows, or platform SDK types.

## Model Names And Boundaries

Use repo-local naming first, but keep these roles separate:

| Role | Owns | Must Not Own |
| --- | --- | --- |
| `Action` / `UiAction` | User intent from view to ViewModel. | Transport payloads, repositories, direct platform calls. |
| `Request` DTO | Outgoing wire body: exactly the fields the server needs. | Response parsing, app-local or UI fields, display defaults. |
| `Response` DTO | Incoming wire body in the server's shape. | Request serialization, UI state, domain policy, display defaults, Compose annotations. |
| `Entity` / domain model | Stable product data crossing repository/domain boundaries. | Raw HTTP handles, serializer annotations, database row annotations unless explicitly a persistence entity, UI callbacks. |
| `UiState` | Durable visible state and interaction availability. | Raw exceptions, DTOs, repositories, one-off commands. |
| `Effect` / `SideEffect` | One-time output such as navigation, snackbar, dialog, permission launch, share. | Durable screen data or business rules. |

If a repo uses "entity" for Room rows, name the domain boundary differently
(`DomainModel`, `RepositoryModel`, or a product noun) so persistence rows do not
leak into ViewModels or use cases.

## Request And Response DTOs

**One class never serves as both a Request and a Response.** A shared class is
how DTOs drift into lenient all-nullable shapes that hide contract breaks.

| Situation | Decision |
| --- | --- |
| Fields received from a GET are sent back in a PUT/POST body. | Separate `Request` class with only the fields the server needs. |
| Request and response fields are identical today. | Still separate. They change independently when the API changes. |
| A small value object (address, date range, money) appears in both. | A shared value class is fine; reusing the Request/Response class itself is not. |
| The call sends one primitive or a plain list. | Pass it as a parameter; no wrapper class. |
| One `XxxDto` mixes request-only and response-only fields. | Split into `XxxRequest` and `XxxResponse` when you touch it. |

Request rules:

- Contains only fields the server consumes. No local state, UI-model fields,
  or values the server never reads.
- Required request fields are non-null; only fields the API documents as
  optional are nullable or defaulted.
- Serialize-out only; never used to parse a response.

Response rules:

- Mirrors the server's shape. Do not reshape it into what the screen wants;
  that is the mapper's job.
- Deserialize-in only; never sent as a request body.
- Holds no presentation types, `@Immutable`/`@Stable`, or UI defaults.
- Stays inside the data implementation; it is not part of a repository API
  module's public contract.

## Field Classification: Required Or Optional

Classify **every** response field before writing the DTO or its mapper. This
decision comes first; nullability, defaults, and mapper behaviour follow from
it.

| Question about the field | Classification | DTO declaration | Mapper behaviour |
| --- | --- | --- | --- |
| Without it, does entity identity, the screen's primary copy, the next API call, or a submit payload break? | Required | Non-null, **no default**, with a decoder that enforces it (reflection decoders: see [Deserializer Classes](#deserializer-classes)) | Missing value is a contract failure. |
| Does operations need to know when it goes missing? | Required | Non-null, no default | Contract failure plus a diagnostic. |
| Does the API document it as nullable or omittable, or can older servers leave it out? | Optional | Nullable, `= null` (or an empty collection) | Map `null` to an absent domain value or a documented neutral value. |
| Does the server sometimes omit it while the user's goal is still met? | Optional | Nullable | Neutral value; add a warning diagnostic only if repeated misses matter. |
| Is it user-facing fallback copy or a placeholder? | Not a DTO concern | — | Lives in the presentation mapper or UI, never in the DTO. |

Display defaults (`""` titles, placeholder images, "Unknown" labels) belong to
the presentation mapper or UI. Never hide a missing required field behind `""`,
`0`, `false`, or `emptyList()`.

## One-Way Conversion

Reads and writes use different types. No type does both directions.

```text
Read  (server -> screen):
  XxxResponse (data impl)
    -> mapper in data/repository impl
    -> XxxEntity (domain, plain Kotlin)
    -> ViewModel
    -> UiState / UiModel (presentation mapper)

Write (screen -> server):
  user input / form values (Action parameters)
    -> repository method parameters or an input value object
    -> XxxRequest built inside the data impl
    -> API service
```

- There is no reverse direction: no `Entity -> Response`, no
  `UiModel -> Request`, no `Response` reused as a `Request`.
- Entities are produced by mappers, not constructed ad hoc from DTOs in
  ViewModels.

## Missing Required Fields Become Typed Failures

A required field that is missing, null, or malformed on a 2xx response is a
payload contract violation, not an empty value:

1. Detect it at the network/data boundary (the decoder with an enforcing
   serializer, the mapper otherwise).
2. Return it as a typed failure through the repo's result convention (a
   malformed-response case in the existing result type, or a typed contract
   exception when the repo uses exceptions). Keep the original cause.
3. Let the ViewModel map that failure to the normal user-facing failure UI and
   block any next action that would use the missing value.
4. Record a diagnostic with safe fields only: endpoint or operation name, DTO
   and field path, reason, and request/trace id. Never log payload values,
   tokens, or personal data.

```kotlin
// Reflection-deserializer path: non-null is not enforced at decode time,
// so the DTO admits null and the mapper enforces the classification.
data class ProfileResponse(
    val id: String?,           // required
    val displayName: String?,  // required
    val bio: String? = null,   // optional
)

internal fun ProfileResponse.toEntity(): ProfileEntity {
    val id = id?.takeIf { it.isNotBlank() }
        ?: throw PayloadContractException("profile", field = "id")
    val name = displayName
        ?: throw PayloadContractException("profile", field = "displayName")
    return ProfileEntity(id = ProfileId(id), displayName = name, bio = bio)
}
// If the repo has a result wrapper, return its malformed-response failure
// instead of throwing; the classification step is the same.
```

Keep the exception or failure type in the data layer or domain error model the
repo already uses; do not invent a second failure model beside an existing one.

## Deserializer Classes

Classify the decode path before choosing a null defense:

- **Enforcing decoders** (kotlinx.serialization, Moshi codegen or its Kotlin
  reflection adapter): a missing non-null field without a default fails the
  decode. Declare required fields non-null with no default and let that failure
  flow through the repo's result convention. No mapper null defense is needed.
- **Reflection decoders that bypass Kotlin constructors** (Gson): fields
  declared non-null can still be null at runtime. Follow the repo's existing
  declaration style, then apply the rules below in the mapper.

Rules for reflection-decoder mappers, in this order:

1. **Required fields**: validate and turn a missing value into a typed failure
   as shown above. Never `.orEmpty()` or default a required field.
2. **Optional fields only**:
   - `String` and `List`: `.orEmpty()` when empty is a valid domain meaning;
     otherwise map to an absent value.
   - Enums: an explicit fallback (`?: Unknown`) or an unknown case.
   - Nested objects: nullable-receiver mapping (`fun Foo?.toEntity()`),
     starting the `?.` chain at the receiver; guarding only inner fields still
     throws one level deeper.
3. **Primitives** (`Int`, `Long`, `Boolean`) are silently filled with
   `0`/`false`. If the field is required, declare it as a nullable wrapper type
   or validate it so a silent zero cannot pass as real data.

## Minimal Mapping Sample

```kotlin
// data/network boundary (enforcing serializer)
@Serializable
data class ProfileResponse(
    val id: String,                            // required: no default
    val displayName: String,                   // required: no default
    val notice: NoticeHintResponse? = null,    // optional
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

The mapper from `Response` to entity lives in the data or repository
implementation. The mapper from entity/failure to `UiState` and `Effect` lives
in the ViewModel, reducer, or a presentation mapper owned by the feature. Do not
expose `ProfileResponse`, raw HTTP response handles, database rows, SDK models,
or server envelopes to the ViewModel or UI.

## Repository Boundaries

- When repositories are split into `api` and implementation modules, the `api`
  module exposes interfaces and stable entities only: no DTOs, serializer
  annotations, or HTTP client types.
- Repository implementation modules own API services, DAOs, DataStore, files,
  SDK clients, request/response DTOs, cache records, and mappers.
- Normalize HTTP response handles, error-body parsing, conversion failures, and
  transport exceptions once at the API or data-source boundary, into the repo's
  existing result convention. Only when the repo has none, use typed exceptions
  as described in
  [android-viewmodel-state Error Handling](../../android-viewmodel-state/references/current-guidance.md#error-handling).
- Feature modules depend on repository APIs or domain use cases, not repository
  implementation packages.
- Map DTO/cache/database models into repository entities before data crosses
  the module boundary.
- Put flavor, dev, fake, or assertion implementations in explicit
  flavor/dev/testing/assertion modules instead of branching through production
  repository contracts.
- Use a domain use case when multiple repositories or product policy must be
  orchestrated; do not add pass-through use cases for one repository call.

## DataStore Summary

- `Preferences DataStore`: key-value settings without a stable schema.
- Typed DataStore: Proto, JSON, or another serializer for one immutable typed
  settings object.
- Room instead of DataStore: large/complex data, partial updates, joins,
  referential integrity, or query-heavy storage.

DataStore belongs behind repository/data-source boundaries. Compose observes
ViewModel state; it does not create, read, or write production DataStore
instances. Before adding or changing a DataStore, read
[android-datastore.md](android-datastore.md) for instance ownership,
multi-process choice, migrations, and corruption handling.

## Network Presentation Hints

Server APIs may return client-safe presentation hints such as `none`,
`inline`, `toast`/`snackbar`, `alert`, `full_page`, retry metadata, message
keys, safe fallback text, or an allowlisted deep-link action.

- Treat hints as API contract data, not direct UI commands.
- Parse the envelope at the network/data boundary and map it to typed failures,
  metadata, or domain results.
- Let the ViewModel or reducer decide whether the current screen maps the hint
  to `UiState`, an `Effect`, or no visible output.
- Keep localization, accessibility behavior, platform control choice, and route
  validity on the client.
- Do not let a server envelope name Android classes, Compose components,
  executable commands, raw HTML, arbitrary JavaScript, or feature
  implementation types.
- Preserve required state updates even when the hint is `none`.

## Check

- Did the change follow the repo's existing serializer, result, and naming
  conventions?
- Is every response field classified required or optional, with required
  fields non-null and without defaults?
- Does a missing required field reach a typed failure with a safe diagnostic
  instead of `""`, `0`, or `emptyList()`?
- Are display defaults in the presentation mapper or UI, not in DTOs?
- Do Request and Response use separate classes, with the Request carrying only
  server-consumed fields?
- Does conversion run one way only (Response -> Entity -> UiState;
  input -> Request)?
- Are repository entities separate from DTOs, database rows, SDK models, and
  UI display models, and does no feature import a repository implementation?
- Is the DTO-to-entity mapper tested, including a missing-required-field case?
- Does collection respect lifecycle, and can process recreation restore needed
  state?
- Does logout, account switch, or permission change clear cached state?
- Are Room migrations, DataStore changes, and offline cache invalidation
  covered?
- Are server presentation hints mapped by the state owner rather than rendered
  directly by network/data code?
