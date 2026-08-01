---
keyflow_id: sys_secure_development_baseline
status: stable
type: human-reviewed-needed
---

# Secure Development Baseline

Use this for any work that touches secrets, auth, permissions, user data,
external integrations, local storage, logs, analytics, crash reporting, release
configuration, or open-source-safe setup.

This is a common baseline. Platform-specific documents may add details, but they
must not weaken these rules.

For environment-specific API origins, callback URLs, redirect URIs, webhook
endpoints, CORS origins, deep link hosts, or asset hosts, also use
`runtime-url-configuration.md`. Those values are configuration and portability
concerns unless they contain credentials or expose private infrastructure.

## Non-Negotiables

1. Do not commit secrets, tokens, private keys, signing material, service-role
   keys, session cookies, or private configuration values.
2. Do not place server-only secrets in client apps, web bundles, mobile apps,
   desktop apps, or generated artifacts.
3. UI gating is not authorization. The trusted boundary must enforce access.
4. Treat logs, analytics, crash reports, support exports, screenshots, and audit
   events as data surfaces.
5. Store only the data needed for the product purpose and clear it on logout,
   account switch, revoke, tenant switch, or downgrade when relevant.
6. Prefer explicit configuration injection over hard-coded environment behavior.
7. If a secret might have been exposed, stop using it, rotate it, and document the
   affected surface.

## Secret Handling

- Keep local developer secrets in ignored local files, OS credential stores, or
  approved secret managers.
- Keep CI and release secrets in the CI provider or deployment platform secret
  store.
- Document required secret names, scopes, and purpose without documenting secret
  values.
- Use least-privilege keys. Prefer separate keys per environment, app, platform,
  and integration.
- Restrict client-exposed API keys by package, bundle id, domain, SHA
  fingerprint, referrer, quota, or provider-specific controls when available.
- Never print, summarize, or paste secret values in agent output, logs, tickets,
  commits, screenshots, or docs.

## Client App Rule

Client apps can contain public identifiers and restricted client keys only when
the provider expects them to be public. They must not contain private credentials
that grant broad server-side access.

Examples of values that must stay out of client code:

- database service-role keys
- payment provider secret keys
- OAuth client secrets for confidential clients
- signing keys and keystores
- private API tokens
- admin, support, or impersonation credentials

Public provider identifiers such as publishable keys, Firebase public config,
public project ids, app ids, measurement ids, and public telemetry DSNs are not
secrets by default. Keep them in the correct environment's config, restrict them
through provider controls when available, and do not confuse them with private
server credentials.

## Runtime URL Configuration Boundary

- Treat password-bearing URLs, database connection strings, URLs containing
  private tokens, webhook secrets, signing material, or session values as
  credential risks.
- Treat API origins, frontend/backend domains, redirect URIs, callback URLs,
  OAuth callbacks, deep link hosts, webhook endpoints, CORS allowed origins, and
  environment-specific asset hosts as runtime configuration unless they contain
  credentials.
- Do not hard-code environment-specific runtime URLs in source. Use the
  platform's documented environment, deployment, flavor, scheme, build setting,
  or config mechanism.
- A URL with only a username, public id, public project id, app id, or public
  telemetry DSN is not a secret by default, but it may still be the wrong
  environment's config.

## Authorization And Tenant Boundaries

- Enforce auth, permission, entitlement, and tenant checks on the trusted server
  or platform boundary.
- Prefer action-level permissions over role-name checks in business logic.
- Recheck permission-sensitive state after login, logout, token refresh, role
  change, invite accept, organization switch, entitlement change, or account
  deletion.
- Do not trust client-provided user id, tenant id, role, price, quota, or feature
  entitlement without server verification.
- Errors should not reveal whether a private resource exists unless the product
  intentionally allows that disclosure.

## Data Storage And Retention

- Classify stored data as public, internal, personal, sensitive, credential, or
  regulated before choosing storage.
- Use secure platform storage for credentials and refresh tokens.
- Avoid plain local files, browser localStorage, plist/UserDefaults, shared
  preferences, or unencrypted exports for sensitive data unless the repo records
  an accepted risk.
- Define cache invalidation and deletion behavior for logout, account switch,
  tenant switch, permission revoke, billing downgrade, and remote deletion.
- Version durable local data and define migration, corruption, and rollback
  behavior.

## Logging, Analytics, And Diagnostics

- Logs should identify what failed without leaking secrets or unnecessary personal
  data.
- Redact tokens, cookies, auth headers, private URLs, one-time codes, invite
  tokens, reset links, and raw request or response bodies by default.
- Crash reports and analytics must not include sensitive field values unless the
  repo explicitly accepts that risk.
- Audit events should record actor, target, action, time, and result, not secret
  payloads.
- Support diagnostics should have retention, access control, and export rules.

## External Integrations

- Identify whether the integration key is public, restricted client, server-only,
  or signing material.
- Define environment separation for local, development, staging, and production.
- Verify callback URLs, redirect URIs, webhook signatures, package names, bundle
  ids, domains, and allowed origins where applicable.
- Use idempotency or duplicate handling for retries, webhooks, billing, and
  background jobs.
- Document provider quota and failure behavior when it affects product flow.

## Open Source Repository Rule

- Keep sample config files value-free, using placeholders only.
- Keep real local config files ignored.
- Document setup steps as variable names and locations, not values.
- Review generated files before committing; generated client config can still
  contain keys, app ids, endpoints, or environment-specific metadata.
- Treat ignored source-tool outputs as security surfaces too. Raw design-tool,
  API, browser, or handoff responses can contain signed asset URLs, auth
  headers, or provider identifiers even when Git ignores their directory.
- Before the final full-tree security audit, remove no-longer-needed raw tool
  responses from the target repository or move them to an OS temporary
  directory. Do not weaken scanner exclusions just to make the audit pass.
- When generated evidence must be retained, keep only redacted summaries and
  derived assets in the repository; keep raw provider responses outside it.
- Add secret scanning or a manual secret review before publishing, tagging, or
  creating a release when the repo is public.

## Review Checklist

- What is the trusted enforcement boundary?
- Which values are secrets, restricted client keys, public ids, or harmless config?
- Where are sensitive fields stored, cached, logged, synced, exported, or shown?
- What clears on logout, account switch, revoke, tenant switch, or downgrade?
- Can denied access, stale session, revoked permission, and cross-tenant access be
  tested?
- If a key is exposed, can it be restricted, rotated, and redeployed without code
  changes?
