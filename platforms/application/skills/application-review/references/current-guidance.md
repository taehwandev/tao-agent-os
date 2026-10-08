---
keyflow_id: sys_4c70aafdfcb1
status: review
type: ai-generated
---

# Application Review

Use for desktop/native app review on any stack (Swift/macOS, Electron, Tauri,
Compose Multiplatform desktop on the JVM, or another native toolkit): menu
bar, window, command, trust boundary, and system integration review. Load the
matching stack review card as well when one exists.

## Findings Priority

1. Privileged command exposure, unsafe shell/filesystem access, update/signing
   risk, data loss, or private data leak.
2. Window/menu/shortcut/tray action mismatch that triggers different behavior
   for the same user command.
3. IPC or trust boundary bridge, permission, background task, cancellation, or OS
   resource leak.
4. Missing packaging, signing, first-launch, command, or system-integration
   verification for affected surfaces.
5. Maintainability, command naming, ownership, or duplicated adapter risk.

## Review

- Check window/menu/shortcut actions route through commands or use cases.
- Check command, window/panel, IPC, background work, and OS resource ownership
  against `platforms/application/skills/application-command-ui/SKILL.md` when
  desktop UI/actions changed.
- Verify file, shell, clipboard, notification, permission, and update boundaries.
- Ensure untrusted surfaces (renderer, webview, embedded browser content,
  plugin, URL, file input) cannot reach privileged APIs broadly.
- Check background task cancellation, progress, retry, and error reporting.
- Confirm logs avoid secrets, tokens, file contents, and private user data.
- Check menu bar, shortcut, toolbar, and panel entry points share command behavior.
- Verify timers, monitors, power assertions, and OS resources are released on stop, failure, timeout, and quit.

## Do Not Approve When

- An untrusted surface (renderer, webview, embedded browser content, plugin,
  URL, or file input) can reach broad shell,
  filesystem, clipboard, environment, credential, updater, or permission APIs.
- Menu, shortcut, toolbar, tray, and panel entry points bypass the shared command
  path or enforce different validation.
- Local file paths, file contents, clipboard contents, private prompts, tokens,
  credentials, or diagnostics leak into logs, analytics, crash reports, or UI.
- Background work, watchers, monitors, power assertions, or native handles lack
  cancellation and cleanup paths.
- Signing, notarization, update, permission, or first-launch behavior changed
  without a release-oriented check or residual-risk note.

## Tools

Every stack:

- Command/use-case tests for each changed entry point.
- UI or smoke test for the changed window, panel, or flow.
- Packaging smoke: build the distributable, install it, and launch it fresh.
- Release: signing, permission, auto-update, and first-launch smoke checks.
- macOS release: signing, notarization/stapling, Gatekeeper, quarantine, and
  update smoke checks when configured.

Stack examples:

- Swift/macOS: XCTest/XCUITest, `xcodebuild test`, SwiftLint if configured.
- Tauri: frontend tests, Playwright, Rust `cargo test`, command tests.
- Electron: unit tests, Playwright, packaging smoke tests.
- Compose Multiplatform desktop (JVM): the Gradle desktop test task (for
  example `./gradlew :desktopApp:desktopTest`), Compose UI tests with
  `runComposeUiTest`, a packaging task smoke such as `./gradlew packageDmg`
  (or `packageMsi`/`packageDeb`), and `spctl -a -vv` plus
  `xcrun stapler validate` on the packaged app when notarization is in
  scope.

## UI Test Focus

- Window opens, restores, and closes without state loss.
- Menu, shortcut, tray/menu bar, and toolbar actions work.
- File picker, drag/drop, clipboard, notification, and permission flows behave safely.
- Background work can be cancelled and reports user-visible errors.
- Menu bar/tray controls reflect the same state as panel/window controls.
- Active OS assertions or monitors do not survive stop, expiry, or app termination.

## Output

Lead with concrete findings and name the command or privileged boundary:

```text
Findings:
- [High] platforms/application/... - issue, impact, affected command, required verification
```

If no findings remain, say so and list unchecked OS, signing, updater, or
packaging surfaces.
