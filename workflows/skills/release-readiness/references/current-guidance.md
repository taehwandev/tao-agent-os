---
keyflow_id: sys_release_readiness_workflow
status: stable
type: human-reviewed-needed
---

# Release Readiness Workflow

Use before packaging, deploying, publishing, tagging, migration rollout,
signing, or handing off release-sensitive work.

## Read

- `common/skills/release-deployment/SKILL.md`
- `common/skills/release-versioning/SKILL.md`
- `common/skills/commit-workflow/SKILL.md` and `common/skills/worktree-hygiene/SKILL.md` when the release
  action creates, moves, pushes, or publishes a source-control tag or branch
- `common/skills/ci-cd-automation/SKILL.md` when workflow files, release automation,
  package publishing, deployment jobs, or CI gates are touched
- `common/skills/deprecation-migration/SKILL.md` when release work removes, renames,
  migrates, or changes compatibility
- `common/skills/verification-policy/SKILL.md`
- `common/skills/secure-development-baseline/SKILL.md`
- `common/skills/generated-files-policy/SKILL.md`
- `common/skills/runtime-url-configuration/SKILL.md` when runtime URLs, callback URLs,
  redirect URIs, webhook endpoints, CORS origins, or asset hosts vary by
  environment
- `common/skills/dependency-policy/SKILL.md` when packages or lockfiles changed
- matching platform security or review card from `index.md`

## Steps

1. Identify artifact, source revision, version scheme, target environment,
   release owner, and rollback or forward-fix path.
2. Inspect final diff for secrets, local config, generated files, migrations,
   dependency churn, and contract changes.
3. Reuse valid verification as below; run missing or invalidated build, package,
   migration, signing, or smoke checks.
4. Verify tag, version, source revision, and artifact provenance match when tags
   are part of the release process.
5. Verify environment config, secret injection, callback URLs, app ids, domains,
   and package identity when relevant.
6. Record user-visible changes, breaking changes, security impact, operator
   action, and known residual risk.
7. Confirm post-release smoke, logs, monitoring, or health checks can detect
   failure.
8. Confirm CI/CD gates, publish/deploy permissions, and rollback automation are
   scoped to the intended branch, tag, environment, or approval path.

## Release Orchestration Context

Carry one release context through commit, review, packaging, tagging and
publication: revision, version, artifact, target, verification and recovery path.
Reuse unchanged required-document readings and existing evidence; do not
reconstruct them or manually repeat hashes already checked by the hooks.

On retry, apply `common/skills/testing/references/final-check.md`: reuse observed
passes only for matching covered inputs and relevant environment. Review the
correction and its affected boundary; unchanged covered code retains its prior
review. A new revision invalidates checks that depend on revision metadata,
packaging, signing or provenance even when source bytes match. Conflicts,
changed dependencies/configuration, new findings or uncertain evidence require
affected checks again. Failed or pending checks never count as passing.

Keep pending source review scoped to its commit unit. Pre-existing structural
debt requires a split only when this diff grows responsibility or public owners,
or the release cannot be verified without it. Follow the commit workflow for
same-run commits and exact fast-forward review reuse; do not start another
implementation cycle solely for a publication substep.

Keep one ledger linking original and reused results. Refresh mutable remote
refs, release/assets, target permissions and applicable production approval
before publication. Preparation gates establish readiness only: planned smoke,
handoff text or a successful tag push cannot establish deployment success.
After execution, collect this attempt's CI/deployment result, artifact provenance
and required live smoke before claiming release completion. Report pending or
failed publication explicitly; never copy a prior attempt's success forward.

## Verification

Release evidence should cover the artifact that will actually ship:

- source revision, version, tag, build number, package id, artifact name, and
  release channel agree
- build/package/sign/notarize/publish dry run or release command completed for
  the intended target
- migration, backfill, seed, generated artifact, or config change has rollback
  or forward-fix evidence
- secrets, env injection, callback URLs, app ids, domains, permissions, and
  signing material are supplied through the intended deployment mechanism
- smoke, health check, logs, metrics, crash reporting, or rollback monitor can
  detect the primary failure modes

Do not treat a local typecheck or formatter as release evidence when packaging,
deployment, signing, migration, or external configuration changed.

## Stop If

- The release artifact or target environment is unclear.
- The version scheme, reset rule, or version/tag/artifact relationship is
  unclear.
- A tag will be created, moved, pushed, or published but repo-local tag policy,
  current branch/remote, or worktree state has not been checked.
- A migration, signing, secret, or deployment change lacks a recovery path.
- Required verification cannot run and no owner has accepted the release risk.
