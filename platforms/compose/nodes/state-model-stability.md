---
keyflow_id: sys_compose_node_state_model_stability
status: review
type: ai-generated
use_when: Designing or changing a Compose UiState type, its status model, its stability annotations, or deciding whether to split high-churn data into separate streams.
skip_when: The change does not add, remove or reshape any Compose-observed state model.
---

# Compose State Model And Stability

## Rules

Pick one state model per screen and keep the mapper, renderer and previews
consistent with it:

| Model | Use when | Shape |
| --- | --- | --- |
| Sealed status carrying content | A load fully replaces what the screen shows; no stale content during refresh or error. | `status: FooStatus` where `Content(data)` holds the payload |
| Always-present content + `LoadStatus` | Content stays visible while it refreshes, pages or fails (refresh, list plus error banner). | `content` with a non-null empty default plus `status: LoadStatus` |

- Make every state the flow can reach representable: loading, empty, error,
  permission denied, offline, disabled, submitting, submitted.
- Prefer immutable `data class` or sealed state over scattered mutable state
  and nullable fields. Map DTO/domain/storage models to UI models before the
  state reaches Compose.
- Give state a deterministic default owned by the model or a preview fixture.

Stability contract for Compose-observed state:

| Type | Annotation |
| --- | --- |
| Top-level screen state and display-model data classes whose public properties are all immutable and whose equality is the visible state | `@Immutable` |
| Sealed UI-state markers (`FooStatus`, `FooUiItem`) | `@Stable` only when every implementation keeps the contract; leaves get `@Immutable` |
| Actions and effects | unannotated unless the repo annotates them; still immutable values |
| Pure domain, repository or model modules | none; keep them structurally immutable and map to annotated UI models at the feature boundary |

- Treat `@Stable` and `@Immutable` as promises to the Compose compiler, not
  lint suppressions. Remove the annotation or fix the model when it is false.
- Use immutable or persistent collections for lists that cross into Compose;
  when the repo uses `kotlinx.collections.immutable`, prefer `ImmutableList`
  with `persistentListOf()` for defaults and mapper output.

```kotlin
@Immutable
data class ProfileUiState(
    val rows: ImmutableList<ProfileRow> = persistentListOf(),
    val status: LoadStatus = LoadStatus.Loading,
    val isSubmitting: Boolean = false,
)
```

Split state when update cadence, render cost, lifecycle owner, cache owner or
list-window ownership differs. A coarse screen `StateFlow<FooUiState>` keeps
top-level status, title, selected ids, form availability, banners and
submit/refresh state. Keep these in separate streams or smaller holders when
they would recompose unrelated UI:

- conversation messages, paging windows, delivery status, typing, presence
- playback progress, timers, sensor or live metric values, cursors, drag,
  scroll, focus, gesture and animation state
- large lazy list item models where only rows or a visible window update

Collect a separate stream at the route or section boundary that owns the
observation, then pass stable row models or plain values down. Messages and
similar items get stable immutable ids.

## Do Not

- Do not mix the two models: a nullable payload beside a status that can say
  `Content` generates impossible states.
- Do not put `var`, mutable collections or maps, arrays, raw SDK objects,
  platform objects, a `CoroutineScope`, repository references, callbacks or
  one-off commands inside `UiState`.
- Do not hide route decisions in booleans inside `UiState`.
- Do not add Compose runtime annotations to pure domain or data modules.
- Do not pass the state holder, a repository, a `Flow`, a callback bundle, a
  mutable collection or the whole screen state into repeated rows.
- Do not split state for ceremony. A small form or read-only page keeps one
  `UiState` when cadence and render cost are shared. When a split is justified,
  name the read or recomposition boundary that becomes smaller, and say
  "reduces broad invalidation risk" unless measurement proves a speedup.

## Verification

- Every reachable state has a representation and a renderer branch; mapper
  tests cover entity-to-`UiState` for each status.
- No annotated type contains a mutable or unstable property; the diff adds no
  annotation to a non-UI module.
- A state split names the recomposition boundary it narrows.
