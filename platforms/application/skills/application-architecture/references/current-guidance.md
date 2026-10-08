---
keyflow_id: sys_7a1b89bb9a49
status: review
type: ai-generated
---

# Application Architecture

Use for desktop/native app shells on any stack (Swift/macOS, Electron, Tauri,
Compose Multiplatform desktop on the JVM, or another native toolkit): windows,
menu bar/tray, commands, local files, background work, and system integration.
Stack cards refine this parent; they do not replace it.

Also use:

- `platforms/application/skills/application-command-ui/SKILL.md` for command
  routing, window/panel state, trust boundary bridges, and background resource
  ownership.
- `platforms/application/skills/application-system-integration/SKILL.md` for
  files, shell, clipboard, notifications, background work, updates, power
  assertions, menu bar/tray controls, or privileged APIs.
- `platforms/application/skills/application-security/SKILL.md` for signing,
  notarization, IPC, URL schemes, untrusted-surface bridges, shell/file access,
  or credential exposure risk.

Stack refinements:

- Swift macOS: `platforms/swift/skills/swift-architecture/SKILL.md`,
  `platforms/swift/skills/swift-code-structure/SKILL.md`, and
  `platforms/swift/skills/swift-design-system/SKILL.md`.
- React renderer in Electron, Tauri, or a WebView shell:
  `platforms/application/skills/application-react-desktop/SKILL.md`.
- Compose Multiplatform desktop (JVM):
  `platforms/kmp/skills/kmp-architecture/SKILL.md` and
  `platforms/kmp/skills/kmp-platform-integration/SKILL.md`.

## Trust Model

Every desktop stack has a trusted process (native app code, main process, Rust
core, JVM app process) and untrusted surfaces (renderer, webview, embedded
browser content, plugin, URL, dropped or opened file input, external app
message). Privileged work stays in the trusted process; untrusted surfaces
reach it only through narrow, typed, validated commands.

## Boundaries

```text
Window/Scene/View -> Presentation State -> Command/Use Case -> App Service -> System Adapter
```

## Rules

- Separate window lifecycle from screen state.
- Route menu, shortcut, toolbar actions through commands.
- Wrap file, shell, notification, clipboard, permission APIs.
- Keep contracts between the trusted process and untrusted surfaces typed and
  explicit (IPC, bridge, plugin, URL, or message APIs).
- Long-running work needs cancellation, progress, and error reporting.
- Distinguish user-facing errors from logs.
- Keep menu bar/tray, panel, shortcut, and toolbar entry points on the same command path.
- Keep OS resource ownership explicit: status items, windows, monitors, timers, assertions, and background workers.

## Do Not

- Do not expose broad shell, filesystem, clipboard, environment, updater,
  credential, or permission APIs directly to an untrusted surface (renderer,
  webview, embedded browser content, plugin, URL, or file input).
- Do not let windows or panels own product rules, persistence, SDK calls,
  command validation, and rendering in one unit.
- Do not implement the same user action separately for menu, shortcut, toolbar,
  tray, and panel entry points.
- Do not start background work, watchers, monitors, timers, or power assertions
  without a cancellation and cleanup owner.
- Do not log local paths, file contents, clipboard values, private prompts,
  credentials, tokens, or privileged command output.

## Refactor Signals

- Window code owns file I/O, network, and product rules.
- Menu actions repeat permission/state checks.
- An untrusted surface can reach privileged APIs too broadly.
- Background task ownership is unclear.
- App quit, timeout, or failure does not clean up active OS resources.

## Verification

- command/use-case test for each changed menu, shortcut, toolbar, tray, panel,
  or untrusted-surface entry point
- bridge/IPC contract test or typed contract inspection when a trust boundary
  changed
- lifecycle smoke for window open/close, app quit, cancellation, timeout, and
  failed background work when OS resources are touched
- signing, update, entitlement, permission, first-launch, or packaging smoke
  check when release-sensitive app configuration changed
