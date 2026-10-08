---
keyflow_id: sys_application_security
status: review
type: ai-generated
---

# Application Security

Use for desktop/native app security on any stack (Swift/macOS, Electron,
Tauri, Compose Multiplatform desktop on the JVM, or another native toolkit):
menu bar tools, local files, shell access, update flows, IPC, and privileged OS
APIs.

The trust model is the same everywhere: a trusted process (native app code,
main process, Rust core, JVM app process) and untrusted surfaces (renderer,
webview, embedded browser content, plugin, URL or deep link, dropped or opened
file, external app message). Stack-specific bridge hardening lives in the stack
card, for example
`platforms/application/skills/application-react-desktop/SKILL.md`.

Also use `common/skills/secure-development-baseline/SKILL.md` for shared secret handling,
authorization, logging, diagnostics, and open-source repository safety rules.
Use `common/skills/runtime-url-configuration/SKILL.md` for environment-specific service
origins, callback URLs, URL scheme hosts, update channels, asset hosts, and
release-channel config.

## Rules

- Keep file, shell, clipboard, notification, accessibility, power, and update APIs behind narrow adapters.
- Route menu bar, shortcut, toolbar, and panel actions through the same command or use case.
- Treat IPC, URL schemes, app links, file input, and every bridge from an
  untrusted surface as a trust boundary.
- Never expose broad shell, filesystem, environment, or credential APIs
  directly to an untrusted surface.
- Keep environment-specific service origins, callback URLs, update channels, and
  asset hosts in app config, installer/release config, or signed channel config;
  do not let an untrusted surface choose trusted origins.
- Keep local file paths, tokens, private prompt text, clipboard content, and user file contents out of logs.
- Signing, notarization, auto-update, first launch, quarantine, and permission prompts require explicit smoke coverage.
- Release assertions, timers, event monitors, background tasks, and OS resources on stop, expiry, app quit, and failure rollback.

## macOS Notes

Apply to any stack that ships on macOS, including JVM and Electron apps.

- `NSStatusItem`, menu bar extras, popovers, panels, windows, and global monitors need a single clear owner.
- Panel/window lifecycle state should not be the source of product state.
- System behaviors such as Accessibility, power assertions, file bookmarks, notifications, and login items are best-effort and must fail visibly.
- Public APIs and distribution constraints matter; private APIs create maintenance, trust, and notarization risk.

## Check

- Can the same action run consistently from menu, shortcut, toolbar, tray, and panel?
- Which OS permission, entitlement, or signing state is required?
- What resource must be cleaned up on app quit, cancellation, failure, or timeout?
- Could an untrusted surface (renderer, webview, URL, file, plugin, or
  external app) trigger this action?
- Does the release channel use the intended service origin, callback URL, update
  channel, and asset host?
- Does the release artifact prove signing, notarization/update, and first-launch behavior?
