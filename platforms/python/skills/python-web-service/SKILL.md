---
keyflow_id: sys_platforms_python_web_service_md_skill
status: review
type: human-reviewed-needed
---

# Python Web Service

Use when creating, changing, moving, or reviewing Python HTTP APIs, FastAPI or
Starlette routes, Pydantic models, dependency injection, middleware, service
layers, async I/O, settings, or endpoint tests.

## Read

- `references/current-guidance.md` for Python web-service branch rules.
- `../../../../common/skills/web-service-rn-python/references/source-map.md` when
  current FastAPI, Pydantic, Starlette, or external skill source behavior matters.
- `platforms/server/skills/server-api-implementation/SKILL.md` for transport,
  validation, use case, repository/client, and response/error contracts.
- `platforms/server/skills/server-security/SKILL.md` when auth, tenant, input,
  outbound call, upload, webhook, or secret handling changes.

## Process

1. Identify the framework and installed versions before choosing syntax.
2. Name route, DTO/model, dependency, service/use-case, repository/client, and
   response/error owners.
3. Keep async and blocking I/O boundaries explicit.
4. Verify through the narrow endpoint, TestClient, unit, typecheck, or server
   start path that covers the change.

## Do Not

- Do not put route parsing, validation, auth, product rules, database access,
  external calls, and response shaping in one handler.
- Do not use a framework idiom without confirming the repo's installed version
  when syntax or behavior is version-sensitive.
- Do not expose secrets, stack traces, SQL, provider payloads, or database rows
  as public responses.

## Verification

- Route smoke with `--platform python` or `--concern python` should include this
  card.
- FastAPI/Python web-service request intent should route this card.
- Run `python3 scripts/workflow.py validate` after route wiring changes.
