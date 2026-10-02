---
keyflow_id: sys_platforms_android_android_external_skill_source_coverage_md_skill
status: review
type: ai-generated
required_contract: core
---

# Android External Skill Source Coverage

Use when Android work cites or imports lessons from the external skill
repositories `android/skills`, `skydoves/compose-performance-skills` or
`chrisbanes/skills`; this is a source coverage manifest, not a vendored copy.

## Read

The core below is the required contract. Open
`references/current-guidance.md` only for an unresolved in-scope question:

- `## Source Trigger Map` to pick the narrowest upstream source file and the
  owning Tao local card for a touched surface.
- `## Source Snapshots` for repository commits and local snapshot paths.
- `## Google Android Skills Coverage`, `## Compose Performance Skills
  Coverage` or `## Chris Banes Skills Coverage` for the exact upstream
  `SKILL.md` and `references/` files of one surface.
- `## Workflow Routing Contract` when changing or checking Android routing.
- `## Tao Agent OS Mapping` to find which local card consumes a source.

For the reusable distilled rules, use `../source-coverage/SKILL.md`.

## Must

- Do not vendor or copy full external skill text into Tao Agent OS. Distill
  only reusable decision rules, stop signals and verification requirements into
  the local Android card that owns the recurring lesson, and only when they
  remain correct across products and repositories.
- Start with the narrowest external source file that matches the touched
  surface.
- Keep provider-specific setup, sample code, release notes and surface details
  as source references unless a reusable rule is needed.
- Keep Tao Agent OS's local Android architecture as the primary rule source;
  use external skills to prevent omission and confirm version-sensitive source
  behavior.
- No-Omission Gate, for Android documentation, architecture, module, Compose,
  lifecycle, coroutine scope, background work, performance, testing or
  platform-SDK work:
  1. Identify the touched source surface.
  2. Read the matching upstream `SKILL.md`.
  3. Read its listed `references/` docs when the task changes implementation,
     dependencies, public contracts, security behavior, testing or
     verification for that surface.
  4. Update the concise Tao rule card only when the lesson is reusable.
  5. Report the source surface and residual source docs not loaded as out of
     scope.
- Apply the gate especially for package/module boundaries, Navigation 3, deep
  links, Compose performance, Flow lifecycle collection and effect keys,
  coroutine scope ownership, edge-to-edge, testing, credentials, billing,
  profiling, Wear, XR, CameraX and AppFunctions.
- Routine device verification with established repo commands follows the
  bounded operation rule in `../source-coverage/SKILL.md`; running an existing
  install or inspection command does not reopen this manifest. Changed tool
  setup, test strategy, SDK behavior and security decisions still require
  their matching sources.
- When the selected platform is `android`, routes for
  `architecture`/`module`/`structure`, `compose`/`ui`/`state`/`performance`, `testing`/`test`, `skills`/`skill`,
  `security`, and `devtools`/`dependency`/`release`/`migration`/`platform`
  concerns must include this manifest.
- Do not claim all external guidance was applied unless the task checked this
  manifest and either loaded the matching source docs or documented why they
  were not relevant.
- In final reports or PR descriptions, cite the source repository and source
  surface, not only the Tao Agent OS summary.
- When a source doc is missing from the Tao mappings, update this manifest
  first, then the concise rule card that owns the lesson.

## Stop If

- An Android route for a covered concern does not include this manifest: treat
  the route as incomplete before editing.
- About to claim external guidance was applied while the matching upstream
  source doc for a touched surface was neither loaded nor documented as not
  relevant.

## Verification

- On a source repository change, refresh `## Source Snapshots` commits and
  re-check whether Android cards need rule updates.
- Confirm Android routes for the covered concerns include this manifest.
- Report the source repository, source surface, loaded docs and residual docs
  left out of scope.
