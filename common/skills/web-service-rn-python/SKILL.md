---
keyflow_id: sys_common_web_service_rn_python_md_skill
status: review
type: human-reviewed-needed
---

# Web Service RN Python

Router only. Use this pack to choose the focused Tao Agent OS cards for a
non-Android React web, React Native, and Python web-service task, then load
those cards before detailed advice, editing, or review.

If a request already clearly matches one focused card, use that card directly.
If several runtimes affect one behavior, load each relevant branch before acting
on that area.

## Read

- `references/current-guidance.md` for branch selection, combining rules, and
  completion criteria.
- `references/source-map.md` when selecting, refreshing, or citing current React,
  React Native, Callstack, FastAPI, Pydantic, Starlette, or external skill
  source behavior.

## Common Routes

| Task signal | Start with |
| --- | --- |
| React route, page, component, hook, form, cache, browser state, or API client | `platforms/web/skills/web-react-ui/SKILL.md`, then add `platforms/web/skills/web-state-data/SKILL.md` when state, cache, form, or data ownership changes |
| Shared API, web-service boundary, DTO, auth, tenant, outbound call, upload, webhook, or secret handling | `platforms/server/skills/server-api-implementation/SKILL.md`, then add `platforms/server/skills/server-security/SKILL.md` for protected or untrusted paths |
| React Native or Expo screen, component, navigation, list, animation, native integration, network, startup, memory, or bundle work | `platforms/react-native/skills/react-native-app/SKILL.md` |
| Python HTTP API, FastAPI, Starlette, Pydantic model, dependency, middleware, settings, async route, database/session boundary, or endpoint test | `platforms/python/skills/python-web-service/SKILL.md` |
| One feature spanning React web, React Native, and Python service behavior | `references/current-guidance.md`, then every branch card named by the touched runtime and contract |

## Process

1. Pick every touched branch before opening detailed cards.
2. Load only the matching branch cards and their source maps when current
   framework behavior or provenance matters.
3. Combine branches when an API contract, state shape, auth rule, or verification
   path crosses runtimes.
4. Report selected branches, skipped branches, and the smallest verification
   command or scenario for each selected runtime.

## Do Not

- Do not vendor third-party skill text into this pack.
- Do not use this pack for native Android, Kotlin, Gradle, Jetpack Compose, or
  Android SDK work.
- Do not turn the pack into a catch-all web platform card.

## Verification

- Route smoke should show this skill for combined React Native, React, Python,
  FastAPI, API, or web-service requests.
- Route smoke should not load Android platform cards from this pack.
- Run `python3 scripts/workflow.py validate` after routing or index changes.
