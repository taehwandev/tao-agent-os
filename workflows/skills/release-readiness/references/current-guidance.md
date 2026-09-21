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
review. A follow-up request or commit alone does not invalidate verification.
Reuse an unchanged retained package when its verified source, build flags,
version, toolchain and relevant environment still match. Revision changes require
rechecks only where embedded metadata, signing or provenance depend on them;
source equality alone cannot prove those inputs match. Rebuild for changed or
unverified inputs, missing/changed artifacts, or an explicit rebuild request. Conflicts,
changed dependencies/configuration, new findings or uncertain evidence require
affected checks again. Failed or pending checks never count as passing.

Keep pending source review scoped to its commit unit. Pre-existing structural
debt requires a split only when this diff grows responsibility or public owners,
or the release cannot be verified without it. Follow the commit workflow for
same-run commits and exact fast-forward review reuse; do not start another
implementation cycle solely for a publication substep.

Keep one ledger linking original and reused results. Use validated references
to prior successful document and local verification records where supported,
instead of rewriting their evidence. Reuse requires matching covered inputs;
failed, pending, changed or unverifiable records remain unsatisfied. A new run
does not inherit all gates: current authorization, mutable remote checks and
the required review still apply. If documentation is unchanged, retain the
checked source and reason, not a bare unchanged assertion or a new wording
crafted only to pass validation.

For a new ledger, `gate-batch --gate-record` accepts a compact reference:
`{"gate":"tests","reuse_from":"<source run id>","reuse_reason":"<why scope, artifacts, toolchain and external inputs still match>"}`.
Supported gates are `source docs`, `documentation impact`, `documentation`,
`tests`, `package` and `smoke`; only local verification is eligible, never a
previous deployment's live result. The hook copies the latest successful
record verbatim and records its provenance after checking the registered
same-project/session source and its captured project/rules state. The agent
still verifies ignored artifacts, toolchain and external inputs; the source
snapshot does not measure them. Changed HEAD/worktree/rules or a legacy record
without a snapshot needs normal evidence, not an invented reuse claim. Reuse
unaffected observed results in that evidence where their own contracts allow
it; rejection is not an instruction to rerun every check. For an unchanged
document decision, `inspected` and `coverage` fields preserve the exact source
read and why it still applies without requiring particular narrative wording.

Refresh mutable remote refs, release/assets and target permissions before
publication. Check existing production authority against the next action using
the release deployment approval and recovery rules; a changed SHA alone does
not require renewed confirmation. Preparation gates establish readiness only:
planned smoke, handoff text or a successful tag push cannot establish deployment
success.
After execution, collect this attempt's CI/deployment result, artifact provenance
and required live smoke before claiming release completion. Report pending or
failed publication explicitly; never copy a prior attempt's success forward.
Local passes do not replace signing, notarization or publication checks for the
artifact newly produced by CI. A pass on a different local toolchain does not
verify a CI compiler workaround; describe it as a candidate until the affected
CI build passes. Once the exact deployment is identified, monitor
one authoritative status source at bounded intervals. Pending is not failure;
do not restart source review while waiting. Inspect bounded relevant logs on
failure, stalled progress or explicit request, rather than dumping full build logs.

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
