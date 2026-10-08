---
keyflow_id: sys_platforms_kmp_kmp_architecture_md_skill
status: review
type: ai-generated
---

# KMP Architecture

Use when a Kotlin Multiplatform or Compose Multiplatform change creates or
moves a layer, feature slice, composition root, platform service, window, or
long-running process, including Compose desktop apps on the JVM and shared
mobile/desktop logic.

Do not use when the project is an Android-only app (use the Android cards) or
a SwiftUI/UIKit-only app (use the iOS or Swift cards). For pure Gradle module
or package placement, start with `platforms/kmp/skills/kmp-module-structure/SKILL.md`.

## Read

- `references/current-guidance.md` for boundaries, rules, the production KMP
  baseline, refactor signals, and verification.
- `references/layering.md` before creating a module or feature slice, adding a
  Gradle project dependency, wiring the composition root, or placing a platform
  service, window, or long-running process.
- For desktop targets, also read
  `platforms/application/skills/application-architecture/SKILL.md`.

## Verification

- Run the narrowest compile/test task for every affected target (for example
  `./gradlew :shared:allTests :desktopApp:desktopTest`) or state which target
  could not be checked.
