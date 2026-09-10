---
keyflow_id: sys_local_tools_device_mcp
status: stable
type: ai-generated
---

# Optional Host-Driven Device Verification

Use an already configured device MCP server when the task needs evidence from a
real device or emulator: UI behavior, gestures, keyboard/focus, navigation, or a
visual comparison. Do not start device tooling for source-only lookups, routine
commits, documentation, or changes whose nearest useful check is a unit test.
This is an optional reference, not an additional route gate or required document.

The current host agent owns reasoning. Prefer direct observation/action tools
when available; do not start a second model agent or paid OCR/model call merely
to operate a device. Installation and provider-specific entrypoints belong in
the tool repository; absolute paths and host registrations belong in local config.

List devices, select the intended authorized serial, and include that serial in
every operation. Do not silently choose the first of several devices. Inspect a
fresh screenshot or hierarchy before acting, then verify the observable outcome.
Keep device data out of commits and use only content authorized for the host.

Distinguish installed configuration, successful MCP handshake, device observation,
and end-to-end behavior verification. Each claim needs its own observed evidence.
An unavailable device does not make source-only checks fail; report the missing
device verification when it is an acceptance requirement. A local device adapter
does not imply cloud device provisioning or cloud-only test support.
