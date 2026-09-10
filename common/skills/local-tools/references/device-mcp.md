---
keyflow_id: sys_local_tools_device_mcp
status: stable
type: ai-generated
---

# Automatic Preparation For Device Verification

When the current task requires evidence from an Android device or emulator,
select the configured host-driven device MCP automatically. This includes
on-device UI tests, gesture/keyboard/focus checks, navigation and bug reproduction.
The `device-testing` concern selects this short contract. It does not create an
extra lifecycle gate, background process, or hook before every tool call.

Do not prepare devices for source-only lookups, ordinary commits, documentation,
or unit tests. An explicit request to omit device checks wins. For other target
platforms, use their supported device tools instead of assuming Android support.

## Prepare Once Per Required Verification

Use the active runtime's registered tool when it is available and healthy.
Otherwise run the installed Tao helper with the current runtime:

```text
python3 <TAO_ROOT>/scripts/device-mcp.py ensure --runtime <codex|claude>
```

This uses the operator-owned `~/.tao/device-mcp.json` registry across projects.
A ready installation is checked and reused: no clone, package sync or duplicate
registration. If setup is missing, the helper installs the pinned approved source,
syncs the locked Python environment and registers the same stdio entrypoint with
the selected host. It never resets an existing checkout, overwrites a conflicting
server, changes global permission profiles, or provisions a model/cloud account.
Concurrent installers stop with `setup_busy` rather than racing. A stale lock
requires confirming its previous process ended before removing it.

The task must permit local setup writes. Reuse existing user authority for the
same approved tool and request any required sandbox escalation through the tool.
Read-only routing does not authorize installation. If the source registry, host
CLI, Python or package manager is missing, resolve that specific prerequisite;
do not invent a repository URL, revision, credential or paid service. New hosts
outside the supported adapters need their own standard stdio MCP registration.

After new registration, reconnect the host MCP client if it cannot reload tools
in-session. A subprocess protocol check is valid connection evidence but does not
prove that the current chat loaded the new tools. Never start a nested model CLI
just to test registration. Do not retry an unchanged failed/pending setup command.

## Local Registry

Store tool identity and machine paths locally, never in shared Tao instructions.
The registry fields are `schema_version` (1), `name`, absolute `checkout`, relative
`entrypoint`, optional `python_version` (default 3.12), `health_imports` (default
`["mcp"]`), and non-secret `env`. Fresh installation additionally requires an
operator-approved HTTPS `repository` and full 40-character `revision` reachable
from that repository. A commit existing only locally cannot bootstrap a new
machine until the operator publishes it. The helper uses `uv sync --frozen
--no-dev`; it does not install the host CLI or provision credentials.

For a read-only installation report, use the same helper with `status` in place
of `ensure`. `ready` means local files, imports and host registration agree; it
is not a device or end-to-end test result.

## Operate And Verify

The current host owns reasoning. Use direct observation/action tools, without
starting a second model agent or paid OCR/model call to operate the device.
List devices, select the intended authorized serial, and include it in every
operation. Never silently choose the first of several devices. Inspect a fresh
screenshot or hierarchy before acting, then verify the observable outcome.
Keep device data out of commits and use content authorized for the host.

Report installation, protocol connection, device observation and end-to-end
behavior verification separately. No connected device means device acceptance
is unverified; continue independent source checks. A local device adapter does
not provide cloud devices or prove animation timing from a static screenshot.
