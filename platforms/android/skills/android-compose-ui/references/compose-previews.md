---
keyflow_id: sys_android_compose_previews
status: review
type: human-reviewed-needed
---

# Compose Previews

Use when adding, changing, or reviewing Compose previews.

Split out of `current-guidance.md`, which keeps the Compose
authoring contract every UI change applies.

## Preview Rule

Every named stateless composable that renders UI needs a colocated Compose
preview, with no omissions. This includes `Screen`, section, state surface, row,
card, dialog, empty/error/loading, and reusable component composables. Screenshot
tests, Compose UI tests, and manual smoke paths are additional verification, not
replacements for this preview requirement.

Previews should:

- Target stateless composables, not ViewModel-backed holders.
- Cover every named stateless UI composable directly. Do not count a parent
  preview as coverage for a separately named stateless child unless the child is
  inlined and no longer exists as its own visual owner.
- Keep one-off preview functions and preview-only sample state in the same
  Kotlin file as the stateless `Screen`, section, or leaf component they render.
  Reviewers should be able to open the component file and inspect the visual
  contract without jumping to a separate preview package.
- Use deterministic sample state from a same-file private preview owner by
  default. Use a separate `preview`, `sample`, or `fixture` owner only when the
  same states are reused by several composable files, a design-system module
  owns shared examples, or the sample setup would otherwise hide the component
  contract.
- Prefer `@PreviewParameter` with a private same-file
  `PreviewParameterProvider<T>` when one composable needs several deterministic
  states.
- Cover the changed states: at least content plus loading, empty, error,
  permission denied, offline, long text, or disabled when affected.
- Wrap content in the app theme or design-system theme.
- Avoid network, database, DI containers, real credentials, random data, current
  time, or device-only services.
- Stay small enough that agents and reviewers can quickly understand the visual
  contract.

If a named stateless UI composable cannot be previewed, refactor its parameters
until it is previewable or inline it into the nearest previewed parent instead
of keeping it as an unpreviewed function. Replacement verification is allowed
only for route holders, platform-service wrappers, or stateful integration
surfaces that are intentionally not stateless UI composables.

## Preview Implementation

Previews should be built from each stateless `Screen`, section, state surface,
or leaf component, with sample state owned by private preview-only values in the
same file. Keep sample data deterministic and domain-safe.

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

Preview requirements:

- Add at least one direct content preview for every named stateless UI
  composable, plus affected edge-state previews when the change touches loading,
  empty, error, permission, offline, disabled, or long text behavior.
- Add dark mode, font scale, small-width, or locale previews when the change is
  likely to break them and the repo already supports preview parameters or
  screenshot coverage.
- Keep preview functions, private preview data, and one-off
  `PreviewParameterProvider` classes beside the composable by default. Move them
  to `preview/` or `sample/` only with a reuse reason named in the change.
- Do not create a fake ViewModel only to make a preview work. Preview the
  stateless composable instead.
- Do not move one-off previews to a distant package just to keep the component
  file short. Split the production component first; keep the preview next to the
  composable it validates.
- Do not hide missing stateless UI previews behind "not runnable locally",
  screenshot tests, Compose UI tests, or manual smoke paths.
