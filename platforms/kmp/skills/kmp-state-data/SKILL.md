---
keyflow_id: sys_platforms_kmp_kmp_state_data_md_skill
status: review
type: ai-generated
---

# KMP State And Data

Use for shared Kotlin state holders, coroutines, `Flow`, repositories,
persistence, sync, settings or session state, including desktop JVM targets.
Not for Android-only ViewModels or pure rendering changes.

## Read

- `references/current-guidance.md`.

## Verification

- Run state-owner and repository tests with injected dispatchers for the
  changed transitions and typed failures.
