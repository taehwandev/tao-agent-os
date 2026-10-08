---
keyflow_id: sys_android_compose_previews
status: review
type: human-reviewed-needed
requires:
  - platforms/compose/nodes/ui-previews.md
---

# Compose Previews

Read at step 7 of the [Compose UI steps](current-guidance.md#steps) whenever a change
adds or meaningfully changes a renderable stateless composable, and when
reviewing previews. Previews are part of authoring, not a separate task.

## Preview Rule

Every named stateless composable that renders UI needs a colocated Compose
preview, with no omissions. Coverage, same-file placement, deterministic
sample data, text-container (long copy and large font scale) and
platform-leaf slot rules are in `platforms/compose/nodes/ui-previews.md`.

Android tooling specifics:

- The large-font-scale text-container preview is `@Preview(fontScale = 1.5f)`
  or larger.
- Leaves that break the IDE preview include `AndroidView`, media players, PDF
  or web renderers and Hilt entry points; put them behind a slot as the node
  describes. `ModalBottomSheet` and `Dialog` content is extracted and
  previewed as a stateless composable.

## Preview Implementation

Use the official Compose preview parameter APIs for multi-state previews:
`@PreviewParameter` can annotate a parameter of an `@Preview`, and the provider
class supplies a `Sequence<T>` of values. Use the annotation's `limit` argument
when a provider exposes more values than the current preview needs. Override
`PreviewParameterProvider.getDisplayName(index)` only after confirming the
repo's `androidx.compose.ui:ui-tooling-preview` version supports it; otherwise
use explicit `@Preview(name = ...)` functions for named states.

```kotlin
private object ProfilePreviewData {
    val content = ProfileUiState(
        status = ProfileStatus.Content(
            ProfileViewData(
                id = ProfileId("preview"),
                name = "Ada Lovelace",
                subtitle = "Long subtitle that verifies wrapping and spacing",
                avatarUrl = null,
            ),
        ),
        canEdit = true,
    )

    val loading = ProfileUiState(status = ProfileStatus.Loading)
    val empty = ProfileUiState(status = ProfileStatus.Empty)
    val error = ProfileUiState(
        status = ProfileStatus.Error(UiMessage("Unable to load profile")),
    )
}

private class ProfileContentPreviewProvider : PreviewParameterProvider<ProfileUiState> {
    override val values = sequenceOf(
        ProfilePreviewData.content,
        ProfilePreviewData.loading,
        ProfilePreviewData.empty,
        ProfilePreviewData.error,
    )
}

@Preview(name = "Profile states")
@Composable
private fun ProfileContentPreview(
    @PreviewParameter(ProfileContentPreviewProvider::class)
    state: ProfileUiState,
) {
    AppTheme {
        ProfileContent(
            state = state,
            onAction = {},
        )
    }
}
```

- Do not create a fake ViewModel only to make a preview work. Preview the
  stateless composable instead.
