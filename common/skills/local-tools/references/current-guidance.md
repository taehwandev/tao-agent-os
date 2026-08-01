---
keyflow_id: sys_local_tools
status: stable
type: human-reviewed-needed
---

# Local Tools Policy

Use installed local tools when they provide better evidence, faster inspection,
or safer execution than guessing.

## Principles

- Prefer local inspection over assumptions.
- Prefer repo-provided scripts and wrappers over global commands.
- Prefer read-only commands before commands that mutate files or external
  state.
- Use network only when current external information is required or local
  evidence is insufficient.
- Do not invent tool availability. Check it.

## Decision Rule

Use a local tool when it answers a concrete question better than reading prose or
guessing:

- stack discovery: manifests, lockfiles, wrappers, versions, and configured
  scripts
- verification: tests, build, typecheck, lint, formatter, smoke, audit, or
  evidence commands
- repository state: git status, diff, branch, remote, changed files, and
  untracked files
- platform state: simulator/device/runtime lists, package tools, signing,
  local server status, or app health checks
- usage/telemetry status: only through approved read-only local status helpers

Prefer read-only checks first. Use mutating, network, destructive, deployment,
publish, credential, or external-state tools only when the task requires them
and approval or repo-local policy allows them.

## Agent And AI CLIs

Tool aliases, preferred agent CLIs, model providers, and usage telemetry tools
are environment-specific. Record them in repo-local instructions or local
operator docs, not in this shared library.

For usage and quota visibility, use the configured local telemetry tool when
available. Example:

```text
<usage-tool> snapshot --json
```

For local model availability, prefer runtime health or listing commands when
configured. Example:

```text
<runtime-tool> list
```

## Runtime Usage Evidence

When a local telemetry or metering tool is involved, separate setup evidence from
usage evidence. A label/context command, permission prompt, hook configuration,
hook process start, command log, or mock payload injection proves only setup or
diagnostic behavior. It is not evidence that real token usage was recorded.

For each supported AI runtime, local docs should name:

- the primary exact usage source;
- any fallback diagnostic or hook path;
- why that source is reliable enough, or why another source is not;
- the accepted proof of a real usage record, such as a queued/imported local
  event or an exact-usage success marker;
- the privacy boundary for what must never be inspected or stored.

Prefer an active exact-usage importer over hooks when a runtime can skip hooks,
run hooks with empty input, terminate hooks early, or omit exact token counts.
Hooks are acceptable usage sources only when the runtime exposes exact post-turn
usage to that hook and the adapter can normalize it without reading private
content. If exact counts are unavailable, record no usage event and use
diagnostics only when they can be content-free.

Keep synchronous lifecycle-hook importers bounded. Persist an opaque per-source
byte offset and process only complete records appended since the last recorded
checkpoint. Run any required full-history bootstrap outside the hook timeout;
do not hide an unbounded rescan by only increasing the hook timeout.

When a product has one normalized local usage store, document runtime-specific
sources as inputs to that store. Do not describe separate runtime sources as
separate product databases unless the product actually reads separate databases.

Never inspect prompts, responses, commands, file paths, transcripts, logs,
diffs, source content, environment values, or secrets to reconstruct token
usage, labels, session names, or display names.

## Workflow Metering Changes

When changing a workflow router, route catalog, hook, prompt bridge, permission
installer, or local metering setup, treat usage-metering labels as a preserved
contract rather than incidental metadata.

Do:

- keep every workflow command mapped to a safe reusable task/stage label;
- keep action labels for classify, list, query, validate, and any new workflow
  action that can run before a route exists;
- add or update tests that fail when a command or action loses its label;
- document whether the change affects setup evidence, label handoff,
  diagnostics, or exact usage evidence.

Do not:

- rename or remove labels only because the route, hook, or command shape changed;
- use prompts, commands, file paths, diffs, logs, repo names, or branch names to
  derive labels or display names;
- treat permission prompts, hook configuration, label writes, setup output, or
  mock payloads as proof that real usage was recorded;
- route usage metering work through design-token guidance. Use the metering,
  usage, or telemetry workflow concern instead.

## Global Agent Lessons

Use a user-local global lesson store such as `~/.tao/` only for
content-free cross-agent learning metadata. This store helps future agents on
the same machine notice accepted or promoted lessons before repeating a workflow
mistake.

Allowed lesson fields are reusable slugs and counts such as failure type, missed
gate, root-cause category, next action, promotion target, promotion status, and
schema version. Do not store prompts, responses, commands, file paths, repo
names, branch names, diffs, logs, source content, environment values, secrets,
or project-specific display names.

Treat global lessons as local guidance, not proof that work was completed. A
lesson becomes durable only when it is promoted into shared docs, tests,
workflow validation, hooks, or repo-local instructions.

## Discovery Pattern

When local tooling matters:

1. Check whether the command exists.
2. Check the version or health command when safe.
3. Prefer the absolute path if PATH is unreliable.
4. Record failures plainly instead of silently falling back.

Example:

```text
command -v <tool>
<tool> --version
<tool> health
```

## Repo Commands

Exact build, test, lint, package, deploy, and smoke commands belong in each
repo's local instructions. Shared docs should not hard-code repo-specific
commands.

## Reporting

When local tools affect the result, report:

- tool name
- command run
- success or failure
- important limitation, such as missing auth, stale cache, or unavailable quota
  data

## Verification

Tool evidence is valid only when the command actually ran and its output proves
the claim being made. Do not claim a build, test, audit, usage import, or smoke
check passed from setup logs, config shape, permission prompts, stale cache, or
mock payloads.

If a tool cannot run, report the command, failure type, likely cause, and the
residual risk. Do not silently replace a failed high-risk check with a weaker
tool unless the weaker check is explicitly reported as partial evidence.
