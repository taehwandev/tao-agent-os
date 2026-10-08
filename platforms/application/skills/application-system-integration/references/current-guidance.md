---
keyflow_id: sys_b9d08be59ef0
status: review
type: ai-generated
---

# Application System Integration

Use when touching windows, commands, files, file watchers, shell, clipboard,
notifications, background work, power assertions, menu bar/tray items, or app
updates on any desktop stack (Swift/macOS, Electron, Tauri, Compose
Multiplatform desktop on the JVM, or another native toolkit).

For privileged APIs, IPC, shell/file access, signing, notarization, or update
trust, also use `platforms/application/skills/application-security/SKILL.md`.
For command routing and state separation, use
`platforms/application/skills/application-command-ui/SKILL.md`.

## Defaults

- Window state and product state are separate.
- Menu, shortcut, tray, toolbar actions route through commands.
- System APIs stay behind adapters.
- Privileged APIs reachable from an untrusted surface (renderer, webview,
  embedded browser content, plugin, URL, or file input) are narrow and typed.
- Background work has cancellation, progress, retry, and user-visible error handling.
- Signing, permissions, first launch, and update flow need smoke coverage.
- Timers, event monitors, power assertions, background tasks, and OS handles are released on stop, failure, timeout, and app quit.
- Menu bar, shortcut, toolbar, and panel entry points share the same command path.

## File Watchers And App-Originated Writes

- File watchers, subscriptions, timers, monitors, and background tasks need a
  single owner and cleanup on stop, timeout, failure, cancellation, window
  close, and app quit.
- Writes made by the app must not trigger recursive watcher, sync, or
  normalization loops. Add an app-originated write guard (record the path and
  content hash or version the app just wrote and ignore the matching event),
  a debounce, or a normalization pause when a watcher observes files the app
  also writes.
- Save, refresh, external edits, and background or AI edits to the same file
  need one conflict rule; do not let each path overwrite the others silently.

## Check

- Can this action run from menu, shortcut, and UI consistently?
- What state survives app restart?
- Are file paths, tokens, and private data kept out of logs?
- What permission, signing, or OS resource does this action require?
- What cleanup happens if the app quits while the action is active?
- Can an app-originated write re-trigger its own watcher or sync path?

## Do Not

- Do not create separate menu, shortcut, tray, toolbar, and UI code paths for
  the same command. Route them through one command boundary.
- Do not expose broad shell, file, clipboard, notification, updater, or OS APIs
  directly to an untrusted surface: renderer, webview, embedded browser
  content, plugin, URL, or file input.
- Do not leave timers, event monitors, file handles, power assertions,
  background tasks, sockets, or observers alive after stop, failure, timeout, or
  app quit.
- Do not log private file paths, clipboard contents, tokens, command payloads,
  document contents, or update credentials as part of diagnostics.
- Do not treat signing, notarization, permissions, login items, update trust,
  or first-launch prompts as covered by a UI-only smoke check.
