---
keyflow_id: sys_compose_node_ui_previews
status: review
type: ai-generated
use_when: A change adds or meaningfully changes a renderable stateless composable, or a review checks preview coverage.
skip_when: The change touches only stateful screens, state holders or non-UI code and no stateless composable renders differently.
requires:
  - platforms/compose/nodes/ui-screen-structure.md
---

# Compose Previews

Previews are part of authoring, not a separate task. Rules hold for Jetpack
Compose and Compose Multiplatform previews; a platform reference adds its
tooling details.

## Rules

### Coverage

- Every named stateless composable that renders UI gets its own direct
  preview: screen content, section, state surface, row, card, dialog,
  empty/error/loading surface and reusable component. A parent preview does
  not cover a separately named child.
- Preview stateless composables, never state-holder-backed screens.
- Cover the changed states: content plus loading, empty, error, permission
  denied, offline, disabled or selected when the change affects them. Add
  dark, small-width or locale previews when the change is likely to break them
  and the repo already supports them.
- Screenshot tests, UI tests and manual smoke paths are extra verification,
  not replacements, and "not runnable locally" is not an exemption.

### Placement And Sample Data

- Keep one-off previews, private sample state and one-off parameter providers
  in the same file as the composable they render. Move them to a `preview`,
  `sample` or `fixture` owner only with a named reuse reason: several files
  share the states, or a design-system module owns shared examples.
- Use deterministic, domain-safe sample state from a private same-file owner.
  For several states of one composable, prefer a preview parameter provider.
- Wrap content in the app or design-system theme. Use the repo's preview
  theme wrapper when one exists, and keep layout (padding, background, size)
  out of that wrapper.
- No network, database, DI containers, real credentials, random data, current
  time or device-only services in a preview.

### Text Containers

When a change adds a text-bearing container (row, card, dialog, sheet, banner,
button with copy) or changes its size or copy, add unconditionally:

1. a preview with the longest realistic copy, including a long localized
   string when the repo ships more than one locale;
2. the same state at a font scale of 1.5 or larger.

### Platform Leaves And Window Containers

Never leave a stateless composable unpreviewed because one leaf breaks the
preview (an embedded platform view, media player, web or PDF renderer, DI
entry point). Keep the real leaf in the stateful screen and give the content
a slot the preview fills with a placeholder:

```kotlin
@Composable
fun VideoCardContent(
    title: String,
    player: @Composable (Modifier) -> Unit,
    modifier: Modifier = Modifier,
) { /* layout that calls player(Modifier.aspectRatio(16f / 9f)) */ }
// Preview: VideoCardContent(title = "Preview title", player = { Box(it.background(Color.Gray)) })
```

For window containers the preview cannot render directly (bottom sheets,
dialogs, popups), extract the inner content into a stateless composable and
preview that. Only stateful screens, platform-service wrappers and
integration surfaces are verified by other means instead of a preview.

## Do Not

- Create a fake state holder only to make a preview work.
- Move one-off previews to a distant package to shorten a component file;
  split the production component instead.
- Count a single short-copy, default-font-scale preview as text-container
  coverage.

## Verification

- Every new or changed named stateless composable in the diff has a direct
  preview in the same file, plus long-copy and large-font-scale previews for
  text containers.
- Previews render in the repo's preview or screenshot tooling; record any that
  could not be rendered and why.
