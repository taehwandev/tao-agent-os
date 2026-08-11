---
keyflow_id: sys_common_react_rn_external_skill_source_coverage_guidance
status: review
type: human-reviewed-needed
---

# React And React Native External Skill Source Coverage

This reference owns complete coverage for the reviewed React and React Native
agent-skill snapshot. It is a provenance and no-omission artifact, not a
vendored replacement for the provider repositories.

## Reviewed Snapshot

- Snapshot label: user-provided React and React Native Agent Skills bundle.
- Snapshot date: 2026-08-07.
- Bundle README SHA-256:
  `ed96f4cf15522e175a71e950a66006229e2dadd74fc0691d3594e3de84ddd7ba`.
- License declared by the bundle and skill frontmatter: MIT.
- Installable top-level skills: 32.
- Nested Software Mansion subskills: 9.
- Recursive `SKILL.md` total: 41.

The committed manifest never stores the reviewed machine's absolute source
path. Pass a local snapshot root only to the checker at verification time.

## Source Families

| Family | Repository | Installable | Nested | Coverage focus |
| --- | --- | ---: | ---: | --- |
| Vercel React | `https://github.com/vercel-labs/agent-skills` | 3 | 0 | React/Next.js performance, composition APIs, and React View Transitions |
| Vercel React Native | `https://github.com/vercel-labs/agent-skills` | 1 | 0 | React Native/Expo UI, lists, state, animation, and monorepo rules |
| Expo | `https://github.com/expo/skills` | 20 | 0 | Expo framework, EAS services, routing, native UI/modules, upgrades, and migration |
| Callstack | `https://github.com/callstackincubator/agent-skills` | 7 | 0 | migration, libraries, performance, brownfield, TV, navigation, and upgrades |
| Software Mansion | `https://github.com/software-mansion-labs/skills` | 1 | 9 | New Architecture, animation, gestures, JSI, worklets, AI, audio, rich text, and SVG |

## Upstream Provenance

The snapshot date and bundle README hash record when the files were reviewed,
never which upstream commit they came from. Each `repositories` entry therefore
carries a `commit` and a `provenance` state:

| Provenance | Meaning | Set the commit to |
| --- | --- | --- |
| `content_verified` | every manifest `SKILL.md` for that provider was found byte-identical in a fresh clone at that commit | the proven 40-character sha |
| `unpinned` | upstream has already moved past the reviewed content, so the originating commit is not recoverable from a snapshot directory | `unknown` |

As of 2026-08-11, Vercel, Expo, and Software Mansion are `content_verified`
against their current HEADs. Callstack is `unpinned`: all seven reviewed
Callstack skills have changed upstream, so no reachable commit reproduces the
reviewed bytes. Never write today's HEAD into a provider whose content no longer
matches -- a guessed pin is worse than an explicit `unknown`, because it makes an
unprovable snapshot look proven.

A snapshot directory copied without its `.git` cannot answer this question at
all. Clone each provider when refreshing so the pin can be established.

## Dispositions

- `distilled`: a provider-neutral Tao owner already carries the reusable
  baseline. Read that owner first and use the source only for coverage and
  current behavior.
- `source_only`: keep the provider skill discoverable for a matching task, but
  do not promote its service workflow, setup commands, product assumptions, or
  specialized API details into Tao's shared baseline without a separate
  commonization decision.

Every manifest entry must use exactly one disposition. `source_only` is an
explicit inclusion decision, not an omission or a lower-confidence copy.

## Ownership Decision

```text
rule/question: Which external React/RN skill surfaces were reviewed, and where
               does a reusable rule belong?
canonical owner: common/skills/react-rn-external-skill-source-coverage/SKILL.md
reason this owner is most specific: the inventory spans React web and React
                                    Native but owns provenance only, while
                                    platform cards retain operational rules.
files to link or remove: link the existing combined source map plus React and
                         React Native entrypoints; do not copy provider files.
route/index updates: route explicit React/RN external-skill or source-coverage
                     requests to this bundle and add an index discovery entry.
verification: compare all 41 paths and hashes, validate owners, run route tests,
              workflow validation, the full test suite, and VibeGuard.
```

## No-Omission Process

1. Read the bundle README and confirm the advertised installable count.
2. Recursively enumerate `SKILL.md`; do not exclude nested provider subskills.
3. Compare the exact relative path set with `source-manifest.json`.
4. Compare each SHA-256 value. A hash change requires a refreshed review
   decision even when the path and frontmatter name stayed the same.
5. Validate provider, installable flag, disposition, surface, and local owner.
6. Re-establish each provider's `commit` and `provenance` from a fresh clone,
   and record `unpinned` for any provider whose reviewed bytes no longer exist
   upstream.
7. Treat the Callstack and Software Mansion `react-native-best-practices`
   entries as distinct provider-qualified paths.
8. Run focused route checks so explicit source-coverage requests load this
   owner without pulling Python or Android cards into unrelated React work.

## Trigger Map

| Task surface | Start with | Add when needed |
| --- | --- | --- |
| React performance, composition, or View Transitions | The matching Vercel React manifest entry and `platforms/web/skills/web-react-ui/SKILL.md` | Web state, performance, component API, accessibility, or browser verification cards |
| React Native screen, navigation, list, state, animation, or native integration | The matching Vercel, Expo, Callstack, or Software Mansion entry and `platforms/react-native/skills/react-native-app/SKILL.md` | Web React semantics cards and explicit Android/iOS/native cards for real platform implementation |
| EAS hosting, simulator, observe, workflows, update insights, or app-store operations | The matching Expo `source_only` entry | Repo-local release/deployment policy, cost approval, credentials, and current official Expo documentation |
| Migration, brownfield, library scaffolding, TV, or upgrade | The matching Callstack or Expo entry | Repo-local architecture, platform, release, dependency, and product-decision docs |
| JSI, worklets, on-device AI, audio, SVG, rich text, or advanced gestures | The matching nested Software Mansion entry | Native platform, performance, security/privacy, asset, accessibility, and measurement owners as applicable |

## Source Application Boundary

The manifest proves that a source exists and was reviewed at the recorded
snapshot. It does not make provider guidance authoritative over:

- repo-local instructions, installed dependency versions, or official docs
- security, privacy, credentials, cost, release, or deployment gates
- platform-specific build, signing, permission, and store policy
- Tao's provider-neutral ownership and verification rules

If a source-specific lesson becomes broadly reusable, update the most specific
existing Tao owner and keep this coverage document as provenance only.

## Refresh Verification

Run:

```text
python3 scripts/check_react_rn_external_skill_manifest.py \
  --source-root <reviewed-snapshot>
python3 scripts/check_react_rn_external_skill_manifest.py --remote-check
python3 -m unittest tests.test_react_rn_external_skill_manifest
python3 scripts/workflow.py validate
vibeguard audit . --rules .
```

`--remote-check` is opt-in and needs network access; the default run stays
offline. It reports `CURRENT` when a provider's remote HEAD still equals the
pinned commit and `MOVED` when upstream advanced past it. `MOVED` is not a
failure -- a snapshot is a point in time. It fails only when the question cannot
be answered at all: an `unpinned` provider or an unreachable remote.

Report added, removed, renamed, and hash-changed entries separately. A provider
rename is not evidence that the old surface disappeared; inspect the source
content and ownership decision before changing the manifest.
