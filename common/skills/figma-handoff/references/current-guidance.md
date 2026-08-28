---
keyflow_id: sys_common_figma_handoff_guidance
status: review
type: ai-generated
---

# Figma Handoff

Use when creating screen images, individual assets, component structure, and
implementation measurements from a Figma URL, or when implementing or auditing
UI from an already-produced handoff bundle. This procedure assumes no specific
AI product, external CLI checkout, or team-private path.

## Source Map

| Current work | Source to read |
|---|---|
| Bundle creation, CLI options, exit status | [tool contract](../../../../scripts/figma-handoff/README.md) |
| Interpreting `design-summary.json` measurements | [schema](../../../../scripts/figma-handoff/docs/design-summary-schema.md) |
| Implementing real UI from a handoff | [implementation playbook](implementation-guide.md) |
| Mapping values to Android, iOS, Web, or another UI stack | [platform mapping](platform-mapping.md) |
| Android implementation with Compose, Views, or a mixed UI | [Figma to Android](../../../../platforms/android/skills/figma-to-android/SKILL.md) |
| iOS implementation with SwiftUI, UIKit, or a mixed UI | [Figma to iOS](../../../../platforms/ios/skills/figma-to-ios/SKILL.md) |
| Web implementation and responsive/accessibility behavior | [Figma to Web](../../../../platforms/web/skills/figma-to-web/SKILL.md) |
| AIs without execution rights or with upload-only access | [AI execution modes](ai-execution-modes.md) |
| Adopting this canonical source in another team | [team adoption](team-adoption.md) |
| Judging pixel-fidelity claims and API limits | [fidelity and limits](../../../../scripts/figma-handoff/docs/fidelity-and-limits.md) |
| Tool changes, verification, live smoke | [verification harness](../../../../scripts/figma-handoff/docs/verification.md) |

Read only the rows you need. Creating a new bundle requires the tool contract.
An implementation request additionally requires the implementation playbook,
the general platform mapping, and the matching platform card when one is listed
above. Platform cards choose toolkit- or framework-specific guidance only after
inspecting the target repository; a platform name alone never implies Compose,
Views, SwiftUI, UIKit, or React. For Web, load the framework-neutral Figma-to-Web
card first and add React guidance only when the target actually uses React. For
an unlisted stack, use the general platform mapping and the target repository's
nearest instructions. Never route local run outputs as knowledge sources or
regression material.

## 1. Classify The Request And Execution Capability

Settle the current deliverable first:

- `handoff`: extract Figma information into a bundle and explain it.
- `implementation`: produce or receive a bundle and change real product UI.
- `audit`: compare an existing implementation against Figma evidence and
  report differences.
- `validation`: verify only the schema and coverage of an existing bundle.

Then confirm whether the current AI can use a shell, Python, the network, and
local files. Without execution capability, do not pretend a link alone
produced an extraction — follow the bundle-consumption path in
[AI execution modes](ai-execution-modes.md).

## 2. Resolve Only The In-Repo Tool

Find the skill and CLI inside this repository. Do not look for external
checkouts, sibling repositories, global installs, or environment-variable
fallback paths.

```bash
SKILL_DIR="<directory containing this reference>"
REPO_ROOT=$(git -C "$SKILL_DIR" rev-parse --show-toplevel)
HANDOFF_CLI="$REPO_ROOT/scripts/figma-handoff/figma-handoff.py"
```

If `HANDOFF_CLI` does not exist, report the incomplete checkout instead of
attempting an install.

## 3. Confirm The Target And Platform

For implementation or audit work, read the target repository's instructions
first and identify its existing UI technology, navigation, design tokens,
assets, accessibility, and test/preview rules. Signals such as Gradle,
Xcode/Swift Package, or `package.json` are candidates only; the user-named
platform and the nearest instructions win.

With no signal, or with several coexisting UI stacks, never default to Web
silently. Either produce only the handoff or confirm the implementation
target before changing anything.

## 4. Validate Inputs With A Dry Run

Prefer a URL containing a `node-id`. Before any real call, validate parsing
and output locations without a token:

```bash
python3 "$HANDOFF_CLI" \
  --url "<FIGMA_URL>" \
  --name "<bundle-name>" \
  --out "<workspace-controlled-output>" \
  --dry-run
```

A real call requires a token in an environment variable. Never accept a token
value in chat or command arguments; if absent, guide the user to the [CLI token
setup](../../../../scripts/figma-handoff/README.md#requirements-and-token-setup)
instructions. Enter the token through a hidden prompt or trusted secret
manager, verify only that the variable is set, and unset it after the run. A
token value must never appear in a repository, prompt, command argument, log,
output, or commit.

Dev Mode is not a prerequisite for the base bundle. Treat Variables metadata as
optional enrichment: an account-, plan-, or file-permission denial from
`/variables/local` becomes a warning, while node structure, renders, components,
styles, and authorized asset exports continue. Do not claim the live boundary
works merely because an environment variable exists; a live smoke also needs a
small node URL the token is authorized to read.

## 5. Produce The Bundle For The Purpose

Implementation requests default to collecting individual assets:

```bash
python3 "$HANDOFF_CLI" \
  --url "<FIGMA_URL>" \
  --name "<bundle-name>" \
  --out "<workspace-controlled-output>" \
  --export-assets
```

Large SECTION splits, JSON-only runs, asset caps, and scale choices follow the
tool contract. Without `--out`, bundles land in `.figma-handoff-work/`, a
hidden workspace never added to Git. Create deliverable handoffs only in a
user-designated output location.

## 6. Interpret By Evidence Priority And Implement

Use `summary/design-summary.json` for exact measurements,
`design-handoff.md` for the human-readable overview, `raw/nodes.json` for
precise conversions and gap recovery, and `frames/` for visual comparison, in
that order. Never estimate measurements from `design-handoff.md` or the
full-frame PNG alone. This applies to a value already stated as correct by a
teammate, a prior session, or an existing comment in the target code, not only
to a value the implementing AI would otherwise guess: re-check it against the
node's actual field in `design-summary.json` before relying on it.

For an implementation request, do not stop at bundle creation. Build reusable
units from `components` and `componentBlueprints`, and land the individual
assets from `assetInventory` and `assetCandidates[].assetPath` into the target
repository by relative path. Never embed the full-frame image as the screen
implementation.

States absent from Figma — loading, empty, error, validation, dark mode,
responsive, accessibility — follow the target product's sources and existing
patterns, and are reported separately as `Missing State`.

### 6-1. Hard Gates — Violations Fail The Handoff

These are gates, not advice. Do not report an implementation that breaks one.

1. **A node with `visible: false` or `opacity: 0` does not exist.** Check the
   node's `visible` field (absent means visible) before implementing it, and
   cross-check against the rendered frame image in `frames/` — a node's
   presence in `layoutNodes` is not on its own proof it should be implemented.
2. **An INSTANCE box size is not the glyph size.** Draw an icon at its inner
   VECTOR size, not the component box. `Icon/Plus2` at 20x20 wrapping a 16x16
   vector is a 16dp icon.
3. **Confirm the vertical extent of every background band by scanning a column
   of the rendered frame.** A `fill` on a `Header` node does not prove the band
   covers that header. Establish where the panel starts and ends from pixels.
4. **Compute overhang from `absoluteBoundingBox` differences.** When a child
   crosses its parent's right or bottom edge, carry that delta as an offset.
   Alignment alone produces a flush edge that does not match the design.
5. **Keep design copy verbatim, but repair an obvious typo or truncation and
   report it as a mismatch.**

### 6-2. Scope Gate — Never Fold A New Design Into Existing Components

**Implement a new design with new components. Visual similarity to an existing
screen is not a reason to reuse or modify that screen's shared component.**

- Another screen's design is a separate specification. Two designs that look
  alike today change independently tomorrow.
- Touching a shared component changes screens nobody asked about. That is a
  scope violation, not a refactor.
- Extract, share, or parameterise only when the user explicitly asks.
  "It is duplicated" and "reuse is cleaner" are not authorisation.
- Before implementing, write down the files this design will own and the files
  it will not touch. An existing file appearing in the diff is the signal to
  stop and ask.
- Once a question is raised about touching shared code, do not act until the
  answer arrives.

## 7. Verify And Report

For a newly produced bundle, check the CLI-recorded warnings and run the
validator:

```bash
python3 "$REPO_ROOT/scripts/figma-handoff/figma_validate.py" \
  "<bundle>/summary/design-summary.json"
```

When real UI changed, add the target repository's approved build, test,
preview, or screenshot-comparison procedure. Never claim pixel equality
without comparing the Figma reference against an implementation screenshot.

Include in the completion report:

- Processing mode and target platform/UI stack
- Bundle or input handoff location
- What was actually implemented and verified
- Warnings, missing assets, API limits, and Missing States
- Verifications run and verifications not run

## Completion Conditions

- Executable code, validator, schema, and procedure all use in-repo sources.
- No token appears in documents, outputs, or logs, and signed render URLs are
  not repeated into logs. An `--include-image-fills` URL map is sensitive
  short-lived `raw/` output.
- The measurement source of truth and the visual reference keep separate
  roles.
- An implementation request ends with real structure, style, and individual
  assets landed plus target-repository verification.
- An AI without execution capability can still interpret an existing bundle
  without overstating what it did.
