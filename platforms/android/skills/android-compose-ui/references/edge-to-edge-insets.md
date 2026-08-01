---
keyflow_id: sys_android_compose_edge_to_edge_insets
status: review
type: ai-generated
---

# Compose Edge-To-Edge And IME Insets

Use when a Compose screen draws behind system bars, handles keyboard overlap,
or migrates legacy window system-bar configuration.

## Edge-To-Edge Ownership

- Call `enableEdgeToEdge()` from the owning `Activity.onCreate()` before
  `setContent` when the app should draw behind system bars. Treat this as the
  default path for modern fullscreen/edge-to-edge Compose screens, especially
  for apps targeting Android 15/API 35 or higher.
- Do not confuse edge-to-edge with immersive mode. `enableEdgeToEdge()` lets
  content draw behind transparent or translucent system bars; hiding system bars
  is a separate immersive-mode decision.
- Treat `enableEdgeToEdge()` as the single owner of decor-fits release,
  transparent system bars, contrast enforcement, and system-bar icon tone. On
  current target SDKs (API 35+) edge-to-edge is enforced and the legacy window
  APIs are deprecated no-ops: delete manual `setDecorFitsSystemWindows`,
  `statusBarColor`/`navigationBarColor`, contrast-enforced, and
  `isAppearanceLight*Bars` blocks that follow `enableEdgeToEdge()` instead of
  migrating them — they duplicate work the enable call already did. Force icon
  tone only through `enableEdgeToEdge(statusBarStyle = ...)`.
- Do not copy legacy manual system-bar configuration blocks from old
  Activities as reference patterns for new screens, even when they still
  compile.

## IME And Inset Handling

- Configure the Activity with `android:windowSoftInputMode="adjustResize"` when
  the screen needs IME insets so Compose can resize or pad content as the
  software keyboard appears and disappears.
- Use `Modifier.imePadding()` on the screen container, scroll container, or
  bottom action area that must move above the software keyboard. Do not rely on
  fixed `Dp` keyboard spacers or legacy `adjustResize` behavior alone.
- Prefer Compose inset modifiers such as `safeDrawingPadding`,
  `windowInsetsPadding`, `windowInsetsBottomHeight`, and `imePadding` over
  hand-rolled system bar or keyboard measurements. Avoid double-applying insets
  across parent and child layouts.
- For `LazyColumn` or other scrolling forms, verify the focused text field and
  bottom actions remain visible while the IME opens. Use inset-sized bottom
  spacers when needed instead of only `contentPadding`.
- Keep tappable controls and gesture targets out of unsafe system gesture areas
  unless the product intentionally owns that interaction and verifies it on
  gesture navigation and 3-button navigation.
