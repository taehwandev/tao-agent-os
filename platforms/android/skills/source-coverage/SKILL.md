---
keyflow_id: sys_android_skill_source_coverage_skill
status: review
type: human-reviewed-needed
---

# Android Skill Source Coverage

Use when Android work cites, imports, compares, or refreshes guidance from the
external Android and Compose skill repositories.

## Read

Select one matching source family below; this list is not a required reading
sequence. Reuse unchanged source guidance already read for the current surface.
Running an established APK install, launch, screenshot or UI inspection command
does not itself change the toolchain or verification strategy. Use the repo's
known command and explicit device/artifact state for that operation. Open the
CLI source only for an unresolved tool behavior, setup change, failure, or a new
interaction/test strategy. Security, SDK and version changes retain their
matching source requirements.

- `../android-external-skill-source-coverage/SKILL.md` for the current source
  snapshot entrypoint.
- `../android-external-skill-source-coverage/references/current-guidance.md`
  for commit IDs and the complete upstream source file manifest.
- `references/external-source-distillation.md` for the source-family router.
- `references/official-android-source-map.md` for official Android skill and
  reference coverage by build, SDK, security, Play, profiling, testing, Wear,
  and XR surface.
- `references/compose-performance-source-map.md` only for Compose performance source
  skills, measurement rules, and specialized reference files.
- `references/chrisbanes-source-map.md` only for Chris Banes Compose/Kotlin source
  skills and their routing rules.
- The matching upstream `SKILL.md` and listed `references/` files before making
  code, dependency, security, performance, or verification changes for that
  source surface.

## Decision Rule

Use the external source as coverage and version-sensitive evidence. Use local
Tao Agent OS cards as the durable rule source. Update Tao Agent OS only when
the source lesson is reusable across Android projects and can be stated without
copying vendor-specific prose, sample code, or release-note detail.

## Process

1. Identify the touched Android surface: Compose, performance, build,
   navigation, testing, security, identity, Play, Wear, XR, CameraX,
   AppFunctions, CLI/devtools, or profiling.
2. Open the matching local source-map reference from this bundle.
3. Open the narrow upstream `SKILL.md` named there.
4. Open the upstream `references/` files named for that surface whenever the
   task changes implementation, dependency versions, public contracts, security
   posture, test strategy, profiler queries, release behavior, or verification.
5. Apply the distilled local rule to the owning Android bundle, not only this
   source manifest.
6. Report source repository, source skill path, upstream reference group,
   local Android bundle updated, and any source docs intentionally left out of
   scope.

## Do Not

- Do not vendor full external skill text into Tao Agent OS.
- Do not treat a matching file count as sufficient source coverage. Coverage
  requires the local source maps to name the extra decisions and reference
  groups inside each upstream skill.
- Do not treat the manifest as sufficient when the implementation surface has a
  matching upstream `SKILL.md` and `references/` files.
- Do not make a version-sensitive Android claim without confirming the repo
  version or opening the source reference for that version.
- Do not collapse security, build, performance, testing, and UI guidance into
  one large Android card when a focused reference can carry the detail.

## Stop If

- The source repository changed and this manifest was not refreshed.
- The task touches security, billing, credentials, release, migration, or
  platform SDK behavior and the exact upstream source file is unavailable.
- A proposed local rule would only be true for one external sample, one product
  vertical, or one dependency version.

## Verification

- Re-run the source manifest comparison against the local snapshots when
  refreshing source coverage.
- Run `python3 scripts/check_android_external_skill_manifest.py` from the
  Tao Agent OS root when the local source snapshots are available.
- Confirm the split source-map references still cover all 63 upstream
  `SKILL.md` entrypoints and the reference groups that affect implementation or
  verification.
- Run `python3 scripts/workflow.py route ... --platform android --concern skills`
  or the specific Android concern and confirm this skill bundle appears when it
  should.
- Run `python3 scripts/workflow.py validate` after route or index updates.
- Run `vibeguard audit . --rules .` before finishing.

## Report

Report the refreshed source commits, missing/stale source paths found, local
Android cards or references updated, validation commands, and remaining
source-surface gaps.
