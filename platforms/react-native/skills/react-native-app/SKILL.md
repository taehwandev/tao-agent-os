---
keyflow_id: sys_platforms_react_native_app_md_skill
status: review
type: human-reviewed-needed
---

# React Native App

Use when creating, changing, moving, or reviewing React Native or Expo screens,
components, navigation, lists, animations, native integrations, networking, or
mobile performance work.

## Read

- `references/current-guidance.md` for React Native branch rules.
- `../../../../common/skills/web-service-rn-python/references/source-map.md` when
  current React Native, Expo, Callstack, or Vercel source behavior matters.
- `platforms/web/skills/web-react-ui/SKILL.md` for shared React component and
  hook rules.
- `platforms/web/skills/web-state-data/SKILL.md` for server state, API client,
  cache, form, or storage boundaries.
- The focused Android architecture, module, security, and review cards surfaced
  by the mixed-native route when the requested React Native work explicitly
  changes Kotlin, Gradle, JNI, Android SDK or manifest behavior, or an Android
  native module or bridge. Keeping those paths in the conditional route avoids
  leaking Android guidance into pure React Native requests through doc-graph
  expansion.

## Process

1. Identify the mobile branch: screen, state, list, animation, network, native
   integration, startup, memory, or bundle.
2. Name the owner for state, effects, data, native capability, and verification.
3. Apply only the matching reference rules.
4. Verify on the smallest device/simulator, Expo, or unit path that exercises
   the changed behavior.

## Do Not

- Do not treat browser-only DOM, CSS, URL, or storage guidance as React Native
  behavior without a mobile equivalent.
- Do not call a performance change fixed without device, profiler, or release-like
  measurement evidence.
- Do not add native dependencies without naming the app package, config, and
  permission/runtime contract they require.

## Verification

- Route smoke with `--platform react-native` should include this card.
- Pure React Native request intent should route this card without Android
  platform cards.
- Explicit React Native Android native-module, bridge, Kotlin, Gradle, JNI,
  Android SDK, or manifest work should combine this card with focused Android
  platform guidance.
- Run `python3 scripts/workflow.py validate` after route wiring changes.
