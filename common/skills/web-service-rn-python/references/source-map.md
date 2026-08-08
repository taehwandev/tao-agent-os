---
keyflow_id: sys_common_web_service_rn_python_source_map
status: review
type: human-reviewed-needed
---

# Web Service RN Python Source Map

Use this reference when a branch needs current framework behavior or external
skill provenance. It is a map, not vendored source text.

Last verified: 2026-08-08.

## Source Policy

- Open the narrowest source that matches the touched runtime and behavior.
- Keep source-specific repository names, package paths, versions, and link lists
  in this map.
- Distill only reusable decision rules, stop signals, and verification questions
  into local Tao Agent OS cards.
- Do not copy vendor prose, sample code, repository layout, release notes, or
  provider setup into shared guidance.

## React Web

Open these when the task changes React component, hook, data-fetching, or
performance behavior:

- React official docs via Context7 library `/reactjs/react.dev` for current
  component, hooks, rendering, state, effect, and memoization guidance.
- Vercel Labs `vercel-labs/agent-skills`,
  [`skills/react-best-practices/SKILL.md`](https://github.com/vercel-labs/agent-skills/blob/805687f34e8c10b420e3d11335a0ca2c3c90d992/skills/react-best-practices/SKILL.md),
  for React and Next.js performance rule coverage.
- Local durable owners: `platforms/web/skills/web-react-ui/SKILL.md`,
  `platforms/web/skills/web-state-data/SKILL.md`, and
  `platforms/web/skills/web-security/SKILL.md`.

## React Native

Open these when the task changes React Native screens, lists, animations,
native modules, Expo configuration, startup, memory, or bundle behavior:

- React Native official docs via Context7 library `/react/react-native-website`
  for current architecture, components, APIs, networking, lists, testing, and
  platform behavior.
- Callstack Incubator `callstackincubator/agent-skills`,
  [`skills/react-native-best-practices/SKILL.md`](https://github.com/callstackincubator/agent-skills/blob/fa0bad00ce4029ca3b4e63b2d950e8fe1b9299a2/skills/react-native-best-practices/SKILL.md),
  for React Native performance, memory, bridge, list, animation, and bundle
  guidance.
- Vercel Labs `vercel-labs/agent-skills`,
  [`skills/react-native-skills/SKILL.md`](https://github.com/vercel-labs/agent-skills/blob/757ccb42a20478be6b7284088978070358b52d5e/skills/react-native-skills/SKILL.md),
  for React Native and Expo branch routing.
- Local durable owner: `platforms/react-native/skills/react-native-app/SKILL.md`.

## Python Web Service

Open these when the task changes Python web framework behavior, Pydantic models,
dependency injection, async routes, middleware, security, database integration,
or endpoint tests:

- FastAPI official docs via Context7 library `/websites/fastapi_tiangolo` for
  current FastAPI, Starlette, Pydantic, dependency, OpenAPI, async route, and
  testing behavior.
- `nealepetrillo/claude-skills-fastapi`,
  [`.claude/skills/fastapi/SKILL.md`](https://github.com/nealepetrillo/claude-skills-fastapi/blob/68f5bdee6309da5f3531b73f63e55f3ae94278ff/.claude/skills/fastapi/SKILL.md),
  for a FastAPI skill map sourced from the official docs.
- Local durable owners: `platforms/python/skills/python-web-service/SKILL.md`,
  `platforms/server/skills/server-api-implementation/SKILL.md`, and
  `platforms/server/skills/server-security/SKILL.md`.

## Distillation Rule

Use external sources for coverage and version-sensitive checks. Add local rules
only when the lesson is reusable across projects and can be stated without
copying vendor-specific prose, sample code, repository layout, or release-note
wording.
