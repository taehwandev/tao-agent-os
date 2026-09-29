---
keyflow_id: sys_android_compose_edge_to_edge_insets
status: review
type: ai-generated
---

# Compose Edge-To-Edge And IME Insets

Read at step 5 of the [Compose UI steps](current-guidance.md#steps) for every screen
skeleton, and whenever a Compose screen draws behind system bars, handles
keyboard overlap, or migrates legacy window system-bar configuration. The
scaffold-level rules (bars in slots, body consumes inner padding, one IME
owner) are in
[Screen Skeleton](current-guidance.md#screen-skeleton).

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

- Treat `android:windowSoftInputMode="adjustResize"` as XML-layout-only
  configuration. The resize soft-input mode is deprecated, and its documented
  replacement is exactly the Compose path: a window that does not fit system
  windows plus an IME inset consumer.
- Do not add `adjustResize` for a Compose screen, and do not carry it forward
  when copying an existing Activity or manifest entry. Handle the software
  keyboard with `Modifier.imePadding()` instead.
- Keep `adjustResize` only on an Activity whose screens are XML layouts.
- An `adjustResize` that already exists at the app or Activity level may be a
  compatibility setting that delivers IME insets on older Android versions.
  Leave it in place during screen work. Removing it is a separate change that
  needs verification on a device at the app's minSdk, not part of a UI edit.
- When Compose hosts XML through `AndroidView` or another interop seam, the
  Compose tree still owns the layout, so use `Modifier.imePadding()` on the
  Compose container instead of adding `adjustResize` to that Activity.
- This is a deliberate Tao Agent OS divergence from the upstream
  `android/skills` `system/edge-to-edge/SKILL.md` step that adds the manifest
  attribute for every soft-keyboard Activity. Do not revert these rules by
  citing that upstream step.
- Target SDK 35 or higher makes edge-to-edge the platform default, so
  `enableEdgeToEdge()` plus `Modifier.imePadding()` is the baseline keyboard
  path. No manifest soft-input mode is needed to make it work, and an older
  runtime API level is not a reason to add one to a screen that lacks it.
- Apply the IME inset at one owner: `Modifier.imePadding()` on the root
  `Scaffold` (keeping `ime` out of its `contentWindowInsets`), `imePadding()` on
  the `bottomBar` content when only the bar should move, a repo scaffold wrapper
  that already does one of these, or a single content container when the
  screen has no scaffold. A stock Material3 `Scaffold`'s `contentWindowInsets`
  pads only the body and never lifts `bottomBar`, so it is not an IME owner for
  a bottom CTA. Put a bottom CTA or input bar that must follow the keyboard in
  the scaffold's `bottomBar`, not in a sibling overlay with its own
  `imePadding()`. Do not rely on fixed `Dp` keyboard spacers or a manifest
  soft-input mode alone.
- Place `Modifier.imePadding()` before `Modifier.verticalScroll()` in the
  modifier chain. After the scroll modifier it pads inside the scrolling
  content instead of moving the container above the keyboard.
- Give each screen exactly one IME owner. Do not add `Modifier.imePadding()`
  under a parent that already accounts for the IME through `Scaffold`
  `contentWindowInsets` or another inset consumer; two owners double the
  keyboard padding. Do not pre-consume the IME with
  `consumeWindowInsets(WindowInsets.ime)` under that owner either.
- Prefer Compose inset modifiers such as `safeDrawingPadding`,
  `windowInsetsPadding`, `windowInsetsBottomHeight`, and `imePadding` over
  hand-rolled system bar or keyboard measurements. Avoid double-applying insets
  across parent and child layouts, and do not wrap the whole root in
  `safeDrawingPadding()` when a scaffold already hands out inner padding.
- For `LazyColumn` or other scrolling forms, verify the focused text field and
  bottom actions remain visible while the IME opens, and that no extra bottom
  gap remains after it closes. Do not assume a shrunken viewport scrolls the
  focused field into view; verify it. Use inset-sized bottom spacers when needed instead
  of only `contentPadding`.
- Keep tappable controls and gesture targets out of unsafe system gesture areas
  unless the product intentionally owns that interaction and verifies it on
  gesture navigation and 3-button navigation.
