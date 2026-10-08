---
keyflow_id: sys_kmp_node_desktop_shell
status: review
type: ai-generated
use_when: Creating or changing a Compose Multiplatform desktop window, menu bar, tray, keyboard shortcut, window state persistence, or app quit behavior on the JVM.
skip_when: The change is inside a screen's content with no window, menu, tray, shortcut or quit behavior, or the app has no desktop target.
refines:
  - platforms/application/skills/application-command-ui/references/current-guidance.md
verified_by:
  - platforms/kmp/nodes/desktop-review.md
---

# KMP Desktop Shell

The parent card owns the command rule and the shell/UI/product/filesystem
state split. This node adds the Compose desktop mechanics.

## Rules

- Only the app target calls `application { }` and creates `Window`,
  `DialogWindow`, `Tray` and `MenuBar`. Screens receive sizes, focus requests
  and callbacks; never a `FrameWindowScope`, `ApplicationScope` or AWT
  `Window`.
- Menu items, tray items and shortcuts dispatch the same command object the
  screen button uses. Keep one shortcut table (`KeyShortcut` values) that the
  `MenuBar` and the window's `onPreviewKeyEvent` both read, so a shortcut
  cannot exist in one entry point only.
- Shortcut precedence is explicit: a focused text field or embedded terminal
  gets keys first, the window's `onPreviewKeyEvent` handles only app-level
  chords, and every swallowed key returns `true` deliberately.
- Window state (`WindowState` position, size, placement) is shell state.
  Persist it on change, restore it before the first frame, and clamp it to the
  current screens on restore: a window saved on a disconnected display must
  reopen on a visible one.
- Decide the last-window-closed policy once in the app target: quit, or stay
  alive in the tray or macOS dock. `exitApplication()` runs only after
  app-scope cleanup (sessions, processes, persistence flush) completes or
  times out.
- On macOS, put About, Settings and Quit where the platform expects them
  (`Desktop.getDesktop()` handlers for about/preferences/quit) and route them
  to the same commands.
- `Dispatchers.Main` on desktop is the Swing event thread. Never block it with
  file, process, network or database work; move that behind a suspend API on
  an IO dispatcher.
- Multi-window apps keep one state owner per window keyed by a stable window
  id; closing a window cancels that owner's scope only.

## Do Not

- Do not read or write window placement from feature code or store it in
  product state.
- Do not register a second key handler for an action that already has a menu
  item; reuse the shortcut table.
- Do not call `exitProcess` or `System.exit` from UI code; quit through the
  app-target command so cleanup runs.
- Do not run `runBlocking` on the Swing thread during close to "finish quickly".

## Verification

- A UI or integration test (or a recorded manual check) proves the command
  runs identically from the menu item, the shortcut and the button.
- Restore check: move the window, quit, relaunch, and confirm placement; then
  restore with a saved position outside every current screen and confirm the
  window is clamped onto a visible display.
- Quit check: quit with active background work and confirm cleanup ran (no
  orphan child processes, persisted state flushed) before the JVM exits.
