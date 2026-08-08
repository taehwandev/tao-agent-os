---
keyflow_id: sys_common_web_service_rn_python
status: review
type: human-reviewed-needed
---

# Web Service RN Python

Use this as a tight branch router for a reduced skill set centered on React web,
React Native, and Python web services.

## Core Principle

Route first, then specialize. A cross-runtime feature is not one generic "web"
task: name the browser UI, mobile UI, service/API, contract, security, state,
and verification owners that actually change.

## Branches

Select every branch that changes behavior, public contracts, tests, or review
criteria. Completion requires each requested runtime to be selected or explicitly
marked out of scope.

| Branch | Load | Completion criterion |
| --- | --- | --- |
| React web UI | `platforms/web/skills/web-architecture/SKILL.md`, `platforms/web/skills/web-react-ui/SKILL.md`, `platforms/web/skills/web-state-data/SKILL.md` when state, cache, forms, or API clients are touched | Route/page, component, hook, service/client, state, and UI verification owner are named. |
| Shared API or web service | `platforms/server/skills/server-architecture/SKILL.md`, `platforms/server/skills/server-api-implementation/SKILL.md`, `platforms/server/skills/server-security/SKILL.md` when auth, tenancy, input, outbound calls, or secrets are touched | Transport, validation, use case, repository/client, response/error shape, and security boundary are named. |
| React Native app | `platforms/react-native/skills/react-native-app/SKILL.md`, plus React web state/UI cards when the same component, hook, or state rule applies | Screen/component, navigation, list, animation, native integration, data, and device-smoke owner are named when applicable. |
| Python web service | `platforms/python/skills/python-web-service/SKILL.md`, plus server API/security cards | Python runtime, framework, DTO/model, dependency, async I/O, settings, and TestClient or equivalent smoke are named. |

## Combining Branches

- Browser React rules transfer to React Native only through shared React
  semantics: component purity, hooks, state ownership, effects, props, and
  render cost. DOM, CSS, URL, cookie, storage, and browser security rules need a
  mobile equivalent before reuse.
- API contracts are product surfaces. If a request/response, DTO, status code,
  header, auth rule, cache key, or error shape changes, verify at least one
  caller branch and the service branch.
- State that crosses runtime boundaries needs an explicit serialized shape.
  Convert server DTOs before rendering in React or React Native.
- Performance claims need runtime-specific proof: browser route/profile evidence
  for web, device/simulator or release-like evidence for React Native, and
  endpoint/server-start/async evidence for Python services.

## Source Map

Use `references/source-map.md` only when a task depends on current library
behavior, external skill provenance, framework version changes, or a source
claim. Keep durable local rules in the branch cards; keep repository names,
versions, and link lists in the source map.

## Boundary

This pack has no native Android branch. When a request becomes native Android,
Kotlin, Gradle, Jetpack Compose, or Android SDK work, leave this pack and route
through the Android platform cards as a separate scoped task.

## Review

Check for a vague one-card route hiding multiple owners, API contract changes
without caller verification, React Native treated as browser DOM, FastAPI syntax
chosen without installed-version evidence, untrusted input reaching services
unchecked, or performance claims without runtime-specific proof.

## Verification

- React web: run the repo's component, route, browser, typecheck, or lint check
  that covers the changed UI/data path.
- React Native: run the smallest simulator/device, Expo, navigation, list,
  animation, or unit check that covers the changed mobile path.
- Python service: run the endpoint/use-case test, TestClient smoke, typecheck,
  or server-start check that covers the changed API path.
- Cross-branch API work: verify request/response compatibility from the caller
  branch and the server branch.
