---
keyflow_id: sys_android_compose_edge_to_edge_insets
status: review
type: ai-generated
---

# Compose Edge-To-Edge And IME Insets

Use when a Compose screen draws behind system bars, handles keyboard overlap,
or migrates legacy window system-bar configuration.

## Edge-To-Edge Ownership

- Treat this as Android application-window guidance. The owning app Activity or
  full-screen dialog controls its window policy; a library, feature module, or
  reusable composable must not silently change the host window.
- Call `enableEdgeToEdge()` from the owning `Activity.onCreate()` before
  `setContent` when the app should draw behind system bars. Treat this as the
  default path for modern fullscreen/edge-to-edge Compose screens, especially
  for apps targeting Android 15/API 35 or higher.
- Do not confuse edge-to-edge with immersive mode. `enableEdgeToEdge()` lets
  content draw behind transparent or translucent system bars; hiding system bars
  is a separate immersive-mode decision.
- Treat `enableEdgeToEdge()` as the app Activity's baseline owner for
  edge-to-edge opt-in and backward-compatible system-bar defaults. It does not
  make every manual appearance or contrast decision redundant. Before deleting
  an existing window call, check the app's target SDK, runtime API, navigation
  mode, and the background actually drawn behind that bar.
- Prefer `enableEdgeToEdge(statusBarStyle = ..., navigationBarStyle = ...)` for
  a stable Activity-wide icon style. Keep or add a focused
  `WindowInsetsControllerCompat` update, including
  `isAppearanceLightStatusBars` or `isAppearanceLightNavigationBars`, when the
  app changes the background at runtime and the icons need explicit contrast.
- Treat `isNavigationBarContrastEnforced` as a three-button navigation policy,
  not as a deprecated no-op. It controls the platform scrim for three-button
  navigation and does not affect gesture navigation. Verify both navigation
  modes before changing it.
- Do not classify all deprecated system-bar APIs as no-ops. Their behavior
  differs by API and bar; remove a legacy call only after the version-specific
  Android documentation and app behavior show that it is ineffective or fully
  replaced.
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
