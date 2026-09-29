---
keyflow_id: sys_platforms_android_android_state_data_md_skill
status: review
type: ai-generated
---

# Android State And Data

This card decides where data work sits in the layer flow, how request/response
DTOs and their fields are declared, how mappers convert and fail, what a
repository exposes, and which persistence store to use.

## Steps

Follow these in order for any change that adds or edits a DTO, mapper,
repository, data source, or persisted value.

1. **Detect the repo's conventions.** Read two or three neighbouring DTOs,
   mappers, and repositories and record the serializer, the result/failure
   convention, and the naming. MUST read
   [Detect The Repo's Conventions First](references/current-guidance.md#detect-the-repos-conventions-first).
   A small fix or endpoint addition keeps the existing path.
2. **Place the work in the layer flow.** Decide which layer owns each new type
   and keep the view free of DTOs, rows, and envelopes. MUST read
   [Clean Architecture Data Flow](references/current-guidance.md#clean-architecture-data-flow)
   and [Model Names And Boundaries](references/current-guidance.md#model-names-and-boundaries).
   If the change creates or moves a module, or changes api/impl ownership,
   MUST also read [android-module-structure](../android-module-structure/SKILL.md).
3. **Split Request and Response.** One class never serves both directions; a
   Request carries only server-consumed fields. MUST read
   [Request And Response DTOs](references/current-guidance.md#request-and-response-dtos).
4. **Classify every response field required or optional before declaring it.**
   Required: non-null, no default, with a decoder that enforces it (reflection
   decoders need the Deserializer Classes rule). Optional: nullable. Display
   defaults do not go in the DTO. MUST read
   [Field Classification](references/current-guidance.md#field-classification-required-or-optional).
5. **Write the mapper one way, and fail on missing required fields.** Response
   -> Entity -> UiState; input -> Request. A missing required field becomes a
   typed failure with a safe diagnostic. `.orEmpty()` and enum fallbacks apply
   to optional fields only. MUST read
   [One-Way Conversion](references/current-guidance.md#one-way-conversion),
   [Missing Required Fields Become Typed Failures](references/current-guidance.md#missing-required-fields-become-typed-failures),
   and [Deserializer Classes](references/current-guidance.md#deserializer-classes).
6. **Define the repository contract.** Expose interfaces and entities only,
   normalize transport failures once into the repo's existing result
   convention. MUST read
   [Repository Boundaries](references/current-guidance.md#repository-boundaries).
   If the change also touches a ViewModel, `UiState`, or effects, MUST read
   [android-viewmodel-state](../android-viewmodel-state/SKILL.md).
7. **Choose persistence.** Before adding or changing DataStore, MUST read
   [android-datastore.md](references/android-datastore.md). For Room, caches,
   source of truth, or cleanup on logout/account switch, MUST read
   [data-persistence-sync](../../../../common/skills/data-persistence-sync/SKILL.md).
8. **Map server presentation hints** as contract data, never as UI commands,
   when the response carries them. MUST read
   [Network Presentation Hints](references/current-guidance.md#network-presentation-hints).
9. **Test the mapper**, including a missing-required-field case and an
   optional-field-absent case.

## Source Map

| Need | Source |
| --- | --- |
| Repo convention detection, defaults | [current-guidance: Detect](references/current-guidance.md#detect-the-repos-conventions-first) |
| Layer direction and model roles | [current-guidance: Data Flow](references/current-guidance.md#clean-architecture-data-flow) |
| Request/Response split | [current-guidance: DTOs](references/current-guidance.md#request-and-response-dtos) |
| Required vs optional nullability | [current-guidance: Field Classification](references/current-guidance.md#field-classification-required-or-optional) |
| Mapper failure and null defense | [current-guidance: Missing Required Fields](references/current-guidance.md#missing-required-fields-become-typed-failures) |
| Repository and module boundary | [current-guidance: Repository](references/current-guidance.md#repository-boundaries), [android-module-structure](../android-module-structure/SKILL.md) |
| ViewModel, UiState, error-to-UI | [android-viewmodel-state](../android-viewmodel-state/SKILL.md) |
| DataStore | [android-datastore.md](references/android-datastore.md) |
| Room, cache, source of truth | [data-persistence-sync](../../../../common/skills/data-persistence-sync/SKILL.md) |

## Do Not

- Reuse one class as both Request and Response, or send a Response back as a
  body.
- Hide a missing required field behind `""`, `0`, `false`, or `emptyList()`.
- Put display defaults or placeholder copy in a DTO.
- Add a reverse conversion (Entity -> Response, UiModel -> Request).
- Expose DTOs, serializer annotations, rows, or HTTP types from a repository
  API or to a ViewModel.
- Add a second failure model (throwing beside an existing result type, or the
  reverse).
- Let a server hint name Android classes, components, commands, or raw HTML.

## Stop If

- The API contract does not say whether a field the change depends on is
  required or optional, and neighbouring code does not settle it: ask before
  choosing a default.
- The repo's serializer or result convention cannot be determined from
  existing code.
- The change would restructure the network/error stack while the task is a
  fix or an endpoint addition.

## Verification

- Mapper unit tests cover the happy path, a missing required field (typed
  failure), and absent optional fields.
- No feature module imports a repository implementation package or a DTO.
- Run the target repo's narrowest compile and unit-test tasks for the edited
  modules.

## Report

- Conventions detected (serializer, result type, naming) and whether any
  default was applied instead.
- New or changed DTOs with each field's required/optional classification.
- How a missing required field fails and what diagnostic it records.
- Persistence choice and migration impact, if any.
- Tests run or not run.

When changing this card, keep links resolvable from this file.
