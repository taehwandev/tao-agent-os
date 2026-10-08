---
keyflow_id: sys_platforms_kmp_kmp_security_md_skill
status: review
type: ai-generated
---

# KMP Security

Use when Kotlin Multiplatform work touches credentials, tokens, local files or
config, shell or process execution, network clients, secure storage, platform
permissions, native interop, logging, release builds, or signing, on mobile or
desktop (JVM) targets.

Do not use when the change has no data, privilege, or release surface (pure
layout or copy), or when the app is Android-only (use
`platforms/android/skills/android-security/SKILL.md`).

## Read

- `references/current-guidance.md` for rules, auth and network security, local
  storage and config files, review questions, and verification.
- `common/skills/secure-development-baseline/SKILL.md` for shared secret,
  logging, and repository safety rules.
- For desktop shell, IPC, signing, notarization, updates, or privileged APIs,
  also read `platforms/application/skills/application-security/SKILL.md`.

## Verification

- Run the relevant compile/test target plus a focused adapter or smoke check,
  and inspect the diff for secrets, broad shell/filesystem APIs, and unsafe
  logs.
