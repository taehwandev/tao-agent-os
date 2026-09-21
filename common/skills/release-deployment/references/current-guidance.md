---
keyflow_id: sys_release_deployment
status: stable
type: human-reviewed-needed
---

# Release Deployment

Use when packaging, deploying, publishing, migrating, signing, tagging, creating
release notes, changing environment config, or preparing rollback-sensitive work.

## Default

A release is not complete because the build succeeded. It needs a clear artifact,
environment, verification gate, and rollback or forward-fix path.

## Separate

- Build artifact
- Runtime configuration
- Secrets and credentials
- Database or storage migration
- Feature flag or rollout policy
- Deployment action
- Post-release smoke and monitoring
- Rollback or forward-fix plan

## Rules

- Keep local, development, staging, and production configuration separate.
- Do not hard-code environment behavior that should be injected by deployment,
  release config, or local config.
- Use `runtime-url-configuration.md` when API origins, callback URLs, redirect
  URIs, webhook endpoints, CORS origins, app link hosts, or asset/CDN hosts vary
  by release environment.
- Verify signing, credentials, package identity, bundle id, domain, callback URL,
  or app id before release when applicable.
- Make migrations backward compatible when old and new app versions can overlap.
- Run destructive migrations only with a rollback, restore, or forward-fix plan.
- Feature flags need an owner, default, rollout condition, monitoring signal, and
  cleanup plan.
- CI/CD automation should separate build, test, package, publish, deploy, and
  smoke stages enough that failures are diagnosable and rollback remains
  realistic. Use `common/skills/ci-cd-automation/SKILL.md` when automation changes.
- Deprecation, migration, or removal work needs compatibility mode, migrated
  callers, docs, and zero-usage or rollback evidence. Use
  `common/skills/deprecation-migration/SKILL.md` when release behavior removes or replaces a
  path.
- Release notes should mention user-visible changes, migrations, breaking
  changes, security impact, and required operator action.
- Never print or commit deployment secrets, signing material, or generated
  production config.
- Release tags should identify the exact source revision used to build and
  publish artifacts, not just the latest branch head.
- Version schemes should follow `common/skills/release-versioning/SKILL.md` and the
  repo-local release contract.

## Approval And Recovery

Carry explicit deployment approval through scoped repairs and retries for the
same target and version. State the next concrete action and continue when it is
covered; do not ask again solely because a repair produces a new source SHA.
Changed source invalidates affected verification, not automatically authority.
Reconcile current remote state before retrying an external write; an uncertain
outcome is not permission to repeat it.

Ask for a decision when the destination, version or action exceeds granted scope,
material risk changes, or authority is paused, limited or revoked. Existing
deployment approval does not grant data deletion, credential changes, increased
cost, or tag overwrite unless explicitly included. Apply the failed-tag rules
below even when a retry uses the same version. Preserve user restrictions and
required sandbox approval; never infer authorization from silence.

## Versioning

Before choosing or changing a release version, read
`common/skills/release-versioning/SKILL.md`.

Do not impose one calendar versioning scheme across unrelated projects. The
shared rule is to choose a documented scheme per artifact and keep it stable:

- SemVer for compatibility-sensitive libraries, APIs, SDKs, generated clients,
  plugins, or packages.
- Weekly CalVer `YY.WW.N` for date-based release tags and operational
  artifacts: two-digit year, ISO week, and release count starting at `1`.
- Monthly CalVer only when the repo-local release contract explicitly says the
  release unit is month-based.

Do not use four-digit years such as `2026.27.1` for CalVer release tags; use
`26.27.1` or `v26.27.1` according to the repo-local tag prefix policy.

## Tag And Artifact Ownership

When a release uses source-control tags:

- Treat tag creation, tag movement, and tag push as release-sensitive
  source-control operations. Read the release readiness, release deployment,
  release versioning, commit workflow, and worktree hygiene guidance before
  mutating a local or remote tag; version naming guidance alone is not enough.
- Create or move the tag only after the intended release revision has passed the
  required source and artifact verification.
- Keep the tag on the revision used to build the published artifacts.
- Do not move a prior release tag to a later commit for documentation, workflow,
  or unrelated follow-up reasons.
- If a post-release fix changes behavior or artifacts, publish a new version or
  release candidate instead of moving the old tag.
- If a post-release fix changes only process or documentation, commit it after
  the release tag and leave the tag where it is.
- Do not overwrite, force-push, or republish an existing public release without
  explicit approval and a clear correction note.
- For annotated tags, verify the peeled commit target, not only the tag object.
- For an explicitly authorized failed-tag replacement, inspect the failed run,
  existing Release/assets and remote tag object SHA. Absence of assets alone
  grants no overwrite authority. Push with an explicit expected old tag SHA
  (`--force-with-lease=refs/tags/<tag>:<old-tag-object-sha>`), never bare force.
  A changed remote tip requires reconciliation, not an automatic retry.

## Direct Push And Tags

Repo-local release policy decides whether a release uses PR merge, direct push,
release branch, or tag. Shared guidance must not choose that model.

When default-branch push deploys production, apply the production approval
boundary. Tag only when repo policy or durable release provenance requires it,
with a known version scheme and passed readiness; preview/staging push alone
does not require a tag.

If branch and tag updates share authorization and no CI dependency requires
separate pushes, prefer one `git push --atomic` with explicit refspecs and any
required tag lease. Atomic refs do not make deployment jobs atomic. If the
server rejects atomic updates, stop and assess partial-publication risk before
choosing a supported sequence. Reuse the enabled strict pre-push audit under
the commit workflow; never disable it or repeat an identical standalone audit.

## Release Gate

Use `workflows/skills/release-readiness/references/current-guidance.md` for
preparation, evidence reuse and completion criteria. Keep applicable checks on
source/version/provenance, target configuration and secret injection,
tests/builds/smoke, monitoring and rollback; reference valid existing results
instead of recording this checklist again.

## Post-Release Check

Verify the most important user or system path after release. If verification is
manual, record exactly what was checked and what was not checked.
