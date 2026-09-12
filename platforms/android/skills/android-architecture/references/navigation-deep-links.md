---
keyflow_id: sys_android_navigation_deep_links
status: review
type: ai-generated
---

# Android Navigation And Deep Links

Use when adding or changing navigation routes, back stack behaviour, or deep links.

Split out of `current-guidance.md`, which keeps the boundary
contract every Android change applies.

## Navigation 3 Advanced Deep Links

For Navigation 3-style Compose apps, treat deep links as an app-entry concern
that creates navigation state, not as a screen-local shortcut.

Use this flow:

```text
Activity intent data
  -> app deep-link request
  -> host/scheme/base-path validation
  -> feature route/deep-link contract
  -> synthetic back stack or route plan
  -> Compose entry mapping and/or ActivityRoute launch request
```

Rules:

- The Activity is the external deep-link entrypoint. It may read `ACTION_VIEW`
  intent data, but it should pass a normalized request into the route
  coordinator instead of parsing feature paths inline.
- The app route coordinator builds the synthetic back stack before Compose
  rendering. Feature implementation screens emit callbacks or route events;
  they do not reconstruct deep-link paths.
- Compose route keys belong to feature API or router API contracts. The app,
  feature implementation, or app-shell module owns the entry builder that maps
  those keys to Compose content.
- Activity-backed destinations are execution requests. An Activity may own its
  own local Navigation 3 back stack, but the top-level router should not mix
  that local stack into the app Compose stack.
- Treat current-task and new-task deep-link launches as separate behavior. Back
  and Up expectations must be explicit and covered by tests or smoke evidence
  whenever both entry paths are supported.
- Keep AndroidX Navigation types out of pure router API modules until the app
  intentionally adopts Navigation 3 as the execution engine. Put the bridge in
  the app, app-shell, or Android-specific router boundary.
- Keep the Activity/base layer responsible for receiving intents and forwarding
  normalized deep-link requests. Keep route planning and synthetic back-stack
  construction in the route coordinator or app-shell runtime. Keep product
  route eligibility and feature entry mapping in app or feature owners.
  Do not hide all three responsibilities in a `BaseActivity`.
