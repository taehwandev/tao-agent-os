---
keyflow_id: sys_kmp_node_desktop_swing_interop
status: review
type: ai-generated
use_when: Embedding a Swing or AWT component (terminal widget, editor, browser view, native panel) in Compose desktop with SwingPanel, or hosting Compose inside Swing.
skip_when: The UI is pure Compose with no Swing or AWT component, or the target is not the JVM desktop.
requires:
  - platforms/compose/nodes/lifecycle-resource-ownership.md
verified_by:
  - platforms/kmp/nodes/desktop-review.md
---

# KMP Desktop Swing Interop

`SwingPanel` places a heavyweight-like AWT component inside Compose. It is a
platform leaf: keep it small, owned, and isolated from shared UI code.

## Rules

- Wrap each Swing component in one desktop-source-set composable that owns
  creation (`factory`), updates (`update`) and disposal. Shared or common code
  sees a slot or an `expect` leaf, never the Swing type.
- Create the component once per stable key; pass state changes through
  `update` instead of recreating it. Dispose listeners, timers and native
  resources in a `DisposableEffect` keyed by the same identity.
- All Swing calls run on the Swing event thread. Compose desktop's main
  dispatcher already is that thread; background callbacks must hop with
  `withContext(Dispatchers.Main)` or `SwingUtilities.invokeLater`.
- Z-order: Compose content does not draw over a `SwingPanel`. Popups,
  dropdowns, tooltips and dialogs that must overlap it use a separate window
  layer (`Popup`/`DialogWindow` with their own window) or are placed outside
  its bounds. Test overlap explicitly.
- Focus is shared between two systems. Request focus on the Swing component
  through its API when the slot becomes active, give it first claim on keys
  while focused, and return focus to Compose explicitly on exit; app-level
  shortcuts are handled in the window's preview key handler.
- Theme sync: map design-system tokens (colors, font family and size, cursor,
  selection) into the component's settings object, and push updates when the
  theme changes; do not hardcode a second palette inside the Swing component.
- Size and scale: read density from Compose and apply it to the component's
  font and metrics so HiDPI screens do not render blurry or tiny text. Verify
  rendering on a Retina display.
- Graphics pipeline flags (for example the Java2D renderer on macOS) are
  app-target launch configuration, chosen once and verified visually; do not
  set them from library code.

## Do Not

- Do not hold a Swing component in a state holder, `UiState`, or a singleton
  outliving its window.
- Do not create Swing components inside composition without `remember` and a
  disposal path.
- Do not call Swing APIs from `Dispatchers.IO` or a PTY reader thread.
- Do not assume a Compose overlay will cover the embedded component.

## Verification

- Open, hide, reopen and close the hosting pane repeatedly; confirm no leaked
  listeners or threads (heap or thread dump, or a disposal counter in tests).
- Capture the window on a HiDPI display and inspect text sharpness after any
  renderer, scale or font change.
- Check keyboard focus round-trips: shortcut works while the component is
  focused, typing reaches the component, and focus returns to Compose.
