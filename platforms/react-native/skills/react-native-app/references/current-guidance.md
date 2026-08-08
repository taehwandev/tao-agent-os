---
keyflow_id: sys_platforms_react_native_app
status: review
type: human-reviewed-needed
---

# React Native App

Use for React Native and Expo app work: screens, components, navigation, lists,
animations, networking, native modules, app startup, memory, and bundle size.

## Core Principle

Separate mobile rendering from app, network, navigation, and native-capability
ownership. A screen should render explicit UI states and callbacks; hooks,
containers, services, or native adapters own data loading, permissions, effects,
and platform behavior.

## When To Use

Use this when a React Native or Expo change touches:

- screen/container splits, navigation params, route effects, or callbacks
- loading, content, empty, error, offline, denied, optimistic, or submitted state
- `FlatList`, `SectionList`, virtualized rows, pagination, or scroll behavior
- networking, DTO conversion, stale requests, or API-client placement
- Reanimated, gesture state, frame-sensitive animation, or JS-thread work
- native modules, permissions, config plugins, startup, memory, bundle, or assets

## Branches

| Branch | Rules | Verification |
| --- | --- | --- |
| Screen and state | Keep screens render-focused. Put data loading, permissions, navigation effects, and mutations in a named container, hook, store, or service boundary. Model loading, content, empty, error, offline, denied, and submitted states explicitly when reachable. | Component test, navigation smoke, or device/simulator path that reaches the changed state. |
| Lists and scroll | Use `FlatList` or `SectionList` for large or changing data. Provide stable keys, keep row work cheap, and tune pagination thresholds only against observed behavior. Memoize after a measured re-render or allocation issue, not by default. | Scroll smoke or profiler evidence for changed large-list behavior. |
| Networking and API | Keep raw HTTP/SDK details behind a client, service, or hook. Convert DTOs before rendering. Abort or ignore stale requests when the screen can unmount or change params. | Request/response test, mocked client test, or screen smoke for loading/error/success. |
| Animations and gestures | Prefer native-thread or Reanimated paths for frame-sensitive motion. Animate transform/opacity before layout-heavy properties when the design allows it. Keep gesture state separate from server state. | Device/simulator interaction smoke; profiler evidence for performance claims. |
| Native integration | Name the native capability, permission, config plugin or native package owner, and fallback when unavailable. Keep native dependencies in the app package when the monorepo has multiple packages. When implementation crosses into Kotlin, Gradle, JNI, Android SDK or manifest behavior, or an Android native module or bridge, add the focused Android architecture, module, security, and review cards. | Platform build/config check or device smoke for the capability; include the focused Android check when native Android implementation changed. |
| Startup, memory, bundle | Measure before optimizing. Prefer lazy work, smaller imports, asset discipline, Hermes-aware checks, static analysis, and type checking before broad rewrites. | Startup, memory, bundle analyzer, lint/typecheck, or release-like measurement tied to the changed path. |

## Boundary

React rules transfer only through React semantics: components, hooks, render
state, effects, and props. Browser DOM, CSS, URL, cookie, and storage behavior
needs a React Native equivalent before reuse.

Pure JavaScript or TypeScript React Native work should not load Android platform
guidance merely because the app runs on Android. Explicit native Android
implementation is different: Kotlin, Gradle, JNI, Android SDK or manifest work,
and Android native modules or bridges must combine this card with focused
Android architecture, module, security, and review guidance. Do not suppress
those cards just because the request is framed as React Native work.

## Common Mistakes

| Mistake | Why it hurts | Fix |
| --- | --- | --- |
| Raw API call in a component body or leaf row | Fetch lifecycle and DTO shape become hidden in rendering | Move API work to a client, service, or hook and pass UI state down |
| Unbounded list with unstable keys | Row identity and memory behavior become unpredictable | Use virtualized lists with stable keys and cheap row contracts |
| Browser-only storage or URL assumption | React Native runtime does not provide the same platform surface | Name the mobile storage, deep-link, or navigation equivalent first |
| Native package added without capability owner | Permissions, config, and app-package placement become implicit | Name the native capability, permission/config path, fallback, and smoke check |
| Performance fix without measurement | The change may move work rather than reduce it | Record device/simulator, profiler, bundle, or release-like evidence |

## Review

Check for raw API calls in components, DTOs leaking into JSX, unbounded lists,
unstable keys, unnecessary re-renders, JS-thread animation work, missing cleanup,
permission assumptions, native dependency placement, and unverified performance
claims.
