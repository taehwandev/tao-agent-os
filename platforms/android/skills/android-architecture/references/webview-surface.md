---
keyflow_id: sys_android_webview_surface
status: review
type: ai-generated
---

# Android WebView Surface

Use when embedding, configuring, or hardening a WebView surface.

Split out of `current-guidance.md`, which keeps the boundary
contract every Android change applies.

## Reusable WebView Surface

For WebView-backed destinations, make the reusable surface Compose content first
and let execution shells wrap it.

Use this shape when the same web destination may appear from an Activity route,
a Compose navigation entry, a modal/sheet, or a future app-shell wrapper:

```text
WebViewRouteData
  -> reusable Compose WebView content/controller
  -> Activity wrapper for external task, result, or manifest ownership
  -> Compose route wrapper when the app navigation stack owns the destination
```

Rules:

- Keep URL validation, allowlists, JavaScript policy, file access policy, and
  external-browser fallback in the WebView runtime or feature owner before a
  page is loaded.
- Keep the WebView body reusable as a Composable or controller-backed surface.
  An Activity should install that content; it should not fork a second WebView
  implementation.
- Use an Activity-backed route when the destination needs manifest metadata,
  task/back-stack isolation, Activity result integration, external app entry, or
  a WebView lifecycle boundary that should outlive the app Compose stack.
- Use a Compose route when the destination is part of the in-app navigation
  stack and does not need a separate Activity contract.
- Keep `Intent`, `Activity`, `WebView`, `WebSettings`, JavaScript bridges, and
  AndroidX Activity Result types out of pure route contracts. Put them in the
  runtime adapter, Activity wrapper, or Android-specific feature implementation.
- Do not put product copy, network error mapping, auth policy, or feature route
  registration into a generic WebView base.

If a WebView design cannot show the route data, reusable Compose content,
Activity or Compose wrapper, security policy, and verification path, keep the
WebView local until that example exists.
