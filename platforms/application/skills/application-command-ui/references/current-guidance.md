---
keyflow_id: sys_application_command_ui
status: review
type: human-reviewed-needed
---

# Application Command And UI

Use when creating, changing, moving, or reviewing desktop/native app windows,
panels, menu bar/tray items, shortcuts, commands, local state, background tasks,
trust boundary bridges, or UI tests on any desktop stack (Swift/macOS,
Electron, Tauri, Compose Multiplatform desktop on the JVM, or another native
toolkit). Stack cards such as
`platforms/application/skills/application-react-desktop/SKILL.md` and the KMP
cards refine these rules.

For shell, file, clipboard, notification, power, update, and OS integration
details, also read
`platforms/application/skills/application-system-integration/SKILL.md`. For
privileged APIs, IPC, signing, notarization, and update trust, also read
`platforms/application/skills/application-security/SKILL.md`.

## Application Layers

Use this shape unless the repo has a stricter local pattern:

```text
Window/Panel/View -> Presentation State -> Command/Use Case
-> App Service -> System Adapter
```

- Window/panel/view owns rendering, focus, layout, user intent, and presentation
  lifecycle.
- Presentation state owns visible loading, error, permission, progress, and
  selection state.
- Command/use case owns product action semantics and can be invoked from menu,
  shortcut, toolbar, tray/menu bar, or UI.
- App service owns orchestration, persistence, and background work.
- System adapter owns filesystem, shell, clipboard, notification, accessibility,
  power assertions, login items, updater, OS handles, and bridge/IPC transport.

## File And Command Split

Apply `common/skills/code-structure-ownership/SKILL.md` before growing
desktop/native runtime files. Default to one primary window/panel, presentation state owner,
command/use case, app service, system adapter, bridge contract, fixture, or
assertion owner per file.

Split files before adding behavior when command enablement, validation,
permission, progress, cancellation, bridge mapping, system API access, window
state, product state, and rendering can be named or tested independently.

Review must fail when a desktop/application runtime file keeps multiple
independently importable owners in one file: windows, panels, presentation
state, commands, services, system adapters, bridge contracts, bridge mappers,
fixtures, or assertion helpers.

Do not:

- Put a window, view state, command, service, filesystem/shell adapter, bridge
  payload mapper, and view code in one file.
- Implement menu, shortcut, toolbar, tray, panel, and bridge actions in
  separate files that each repeat the same product logic instead of sharing a
  command boundary.
- Hide privileged shell, filesystem, clipboard, updater, permission, or
  credential access behind a broad `AppService`, `SystemService`, `Helpers`, or
  `Utils` file.
- Split into packages or targets when purpose-named files inside the current
  boundary would make ownership and verification clear.

## Command Rule

Every user action that can be triggered from more than one entry point should
route through one command path:

```text
menu item -> Command
shortcut -> Command
toolbar button -> Command
tray/menu bar item -> Command
panel button -> Command
```

The command should define:

- enabled/disabled state
- required permission, entitlement, file access, or OS capability
- input validation
- cancellation behavior
- progress reporting
- user-visible error
- cleanup on failure, timeout, cancellation, and app quit

Do not duplicate action logic in menu handlers, button handlers, bridge or IPC
handlers, and shortcut callbacks.

## Window And State Rule

Keep four kinds of state owned separately:

- Shell state: window visibility, size, position, focus, drag regions, panel
  placement, and menu bar/tray state.
- UI state: interaction-local state such as an open menu, selected row, draft
  text, hover, focus, and transient dialogs. It stays near its interaction
  owner.
- Product state: workspace, session, and domain state owned by a feature
  store, use case, or app service with explicit persistence and restore rules.
- Filesystem (and server) state: the source of truth on disk or remote. Do not
  copy it into product state without a sync, conflict, and refresh rule.

- Window visibility, position, focus, and restoration state are not product
  state.
- Product state should survive close/reopen only when the product requires it.
- Panels, popovers, menu bar extras, and secondary windows need one owner.
- App launch, first run, restore, sign out, permission revoke, update, and quit
  should define state cleanup.
- UI should render loading, empty, error, permission denied, offline/unavailable,
  progress, disabled, and success states when reachable.

## Trust Boundary Bridges

Any path from an untrusted surface (renderer, webview, embedded browser
content, plugin, URL or deep link, dropped or opened file, external app
message) into the trusted process is a bridge:

- Expose narrow typed commands, not broad filesystem, shell, environment, or
  credential APIs.
- Validate every input that crosses the bridge, including drag/drop, URL, file,
  plugin, and external-app input.
- Keep privileged work in the trusted process or native layer.
- Treat bridge payloads as untrusted input even when the app's own UI created
  them.
- Return stable, user-safe errors and log private detail only in safe logs.

Stack-specific bridge mechanics (Electron preload and main process, Tauri
commands, WebView message handlers) live in the stack card, for example
`platforms/application/skills/application-react-desktop/SKILL.md`.

## Background Work And OS Resources

- Long-running work needs cancellation, progress, timeout, retry, and
  user-visible failure state.
- Timers, event monitors, file watchers, power assertions, background tasks,
  sockets, and OS handles need explicit owners.
- Release resources on stop, failure, timeout, cancellation, logout, app quit,
  and window deallocation where applicable.
- Do not leave menu bar/tray indicators, monitors, or assertions active after
  the command has stopped.

## File Layout

A desktop feature can use:

```text
features/capture/
  CaptureWindow       window, panel, or root view
  CaptureState        presentation state owner
  CaptureCommand      command/use case shared by every entry point
  CaptureService      orchestration and background work
  system/
    ClipboardAdapter
    FileBookmarkStore
  tests/
```

File extensions follow the stack, for example `.swift`, `.tsx`, or `.kt`.
Adapt names to the repo's local structure while preserving command and adapter
ownership.

## Tests

Choose the closest checks configured in the repo:

- Command tests for enabled state, validation, permission failure,
  cancellation, progress, and user-visible errors.
- Adapter tests for filesystem, clipboard, shell, notification, update, or
  permission behavior where the repo supports fakes.
- UI tests for window open/restore/close, menu/shortcut/tray consistency, forms,
  and permission prompts.
- Packaging smoke for signing, notarization, first launch, update, and
  quarantine behavior when release surfaces change.

Review the final diff for duplicated menu/button logic, privileged APIs
reachable from untrusted surfaces, product state stored as window state, missing cleanup, hidden background
work, and private file/token/clipboard data in logs.
