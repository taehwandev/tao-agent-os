---
keyflow_id: sys_platforms_python_web_service
status: review
type: human-reviewed-needed
---

# Python Web Service

Use for Python HTTP services: FastAPI, Starlette, ASGI apps, Pydantic models,
dependency injection, middleware, settings, async routes, database/session
boundaries, and endpoint tests.

## Core Principle

Keep transport, validation, product rules, persistence, outbound calls, and
public response shape in named boundaries. Routes adapt HTTP to a use case; they
should not become the use case, repository, serializer, and error policy at
once.

## When To Use

Use this when a Python service change touches:

- FastAPI, Starlette, ASGI route handlers, dependencies, middleware, or startup
- Pydantic request/response models, serializers, validation, or OpenAPI shape
- auth, tenant, idempotency, transaction, or side-effect rules
- database/session boundaries, external clients, retries, timeouts, or mapping
- async routes, blocking I/O, cancellation, settings, or endpoint tests

## Branches

| Branch | Rules | Verification |
| --- | --- | --- |
| Route and DTO | Keep transport parsing, request/response models, status codes, headers, and OpenAPI-visible shape at the route boundary. Use explicit response models, return annotations, or serializers for public contracts. | Endpoint or contract test for status and response shape. |
| Validation and dependency | Use typed models, dependencies, and allowlists for query/body/path/header input. Keep server-owned fields out of client-controlled writes. | Validation test for accepted, rejected, default, and malformed inputs. |
| Service/use case | Move authz, tenant, idempotency, transaction, and side-effect rules behind a named service/use-case when more than transport mapping is involved. | Unit or endpoint test for permission, tenant, idempotency, and side effects. |
| Repository/client | Keep database sessions, transactions, external calls, timeouts, retries, and provider DTO mapping behind repository/client boundaries. | Repository/client test or mocked external-call test for success and failure. |
| Async and blocking I/O | Keep blocking work off the event loop or isolate it behind the framework-approved path. Propagate cancellation/timeouts where the repo pattern supports them. | Async test, server-start smoke, or timeout/cancellation check for the changed path. |
| Settings and middleware | Load environment-specific settings through the repo's config pattern. Keep CORS, auth, compression, proxy, and error middleware order explicit. | App startup or middleware test for configured behavior. |

## FastAPI Defaults

When the repo uses FastAPI, prefer the repo's installed FastAPI/Pydantic idioms.
Use dependency overrides for tests, `TestClient` or the repo's async client for
route checks, and Pydantic models for request/response contracts. Confirm the
installed version before applying syntax that changed across FastAPI, Starlette,
or Pydantic releases.

## Common Mistakes

| Mistake | Why it hurts | Fix |
| --- | --- | --- |
| Returning ORM/database entities directly | Public contracts inherit private persistence shape | Map through a response model or serializer |
| Trusting optional tenant/user filters | Missing filters silently widen access | Put authz and tenant checks behind dependencies or use cases and test denial |
| Letting client writes include server-owned fields | Mass assignment creates privilege or integrity bugs | Define input models that exclude server-owned fields |
| Blocking work in async routes | Event-loop latency leaks across requests | Use the repo-approved sync boundary, worker, or async client |
| Broad `except Exception` response shaping | Provider and programming errors become indistinguishable | Map typed errors at the boundary and let unknown bugs surface safely |

## Review

Check for mass assignment, optional tenant filters, raw request objects in use
cases, database entities in public responses, untyped provider errors, broad
`except Exception`, leaked diagnostics, blocking calls in async routes, missing
dependency overrides in tests, and endpoint behavior not covered by a narrow
smoke or contract test.
