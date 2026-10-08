---
keyflow_id: sys_kmp_node_desktop_packaging
status: review
type: ai-generated
use_when: Changing Compose desktop native distributions, jpackage settings, bundled JRE or native helpers, code signing, notarization, entitlements, JVM launch options, or the app updater.
skip_when: The change does not touch packaging, signing, release configuration, launch options or update delivery.
refines:
  - platforms/application/skills/application-security/references/current-guidance.md
verified_by:
  - platforms/kmp/nodes/desktop-review.md
---

# KMP Desktop Packaging And Signing

The parent card owns signing, notarization and update trust as release risks.
This node adds the Compose desktop and JVM packaging mechanics.

## Rules

- `compose.desktop.application.nativeDistributions` in the app target is the
  only packaging source: target formats, package name, version, bundle id,
  icons, `modules(...)` for the jlinked runtime, and JVM args. Keep the
  version derived from one release version source.
- List required JDK modules explicitly (`suggestRuntimeModules` helps) so the
  jlinked runtime does not miss `java.sql`, `jdk.unsupported`,
  `java.management` or similar at runtime only.
- Set JVM launch options deliberately: a bounded `-Xmx` for the app and any
  helper JVM, and renderer or HiDPI flags chosen once and visually verified.
- macOS signing covers every executable byte: the app bundle, the bundled
  runtime, and native libraries or helper binaries shipped inside jars
  (PTY spawn helpers, JNA, SQLite drivers). Jar-embedded binaries are not
  signed by jpackage; extract, sign with the hardened runtime and a timestamp,
  and repack them before packaging.
- Hardened runtime entitlements are the minimum the JVM needs (typically JIT
  and unsigned executable memory, plus any device or network entitlement the
  app really uses). Each entitlement has a written reason.
- Notarize with `notarytool` using credentials from the CI keychain or
  environment, staple the ticket, and keep the notary log on failure.
- The updater verifies a signature or checksum from a trusted channel before
  replacing the app, never runs a downloaded script, and keeps the previous
  version until the new one launches.
- Release channel config (update URL, service origins) comes from build or
  signed channel config, not from user-editable settings.

## Do Not

- Do not commit signing identities, notary passwords, API keys or
  provisioning material; reference them from CI secrets.
- Do not ship a debug build, a developer-signed build or an unstapled build
  as a release.
- Do not add an entitlement or disable library validation to make a crash go
  away without identifying the binary that needed it.

## Verification

- Build the distributable (for example `packageDmg` / `packageMsi`) on a clean
  checkout and launch it from Finder or the installer, not from Gradle.
- `codesign --verify --deep --strict`, `spctl -a -vv` and
  `xcrun stapler validate` pass on the produced app; list any native binary
  that `codesign -dv` shows unsigned.
- Exercise one native helper path (open a terminal session, open the
  database) in the packaged app to prove its binaries load under the hardened
  runtime.
- For updater changes, test a real update from the previous released version
  and a tampered or unsigned payload being rejected.
