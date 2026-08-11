---
keyflow_id: sys_common_react_rn_external_skill_source_coverage
status: review
type: human-reviewed-needed
---

# React And React Native External Skill Source Coverage

## Use When

Use when React web or React Native work depends on external agent-skill
coverage, when refreshing the reviewed React/RN source snapshot, or when an
agent must prove that a provider skill was not omitted.

Do not load the full manifest for ordinary UI work that does not depend on
external-source provenance or a version-sensitive provider surface.

## Read

- `references/current-guidance.md` for the source families, dispositions,
  ownership decision, and no-omission process.
- `references/source-manifest.json` for the exact snapshot paths and SHA-256
  values.
- `common/skills/web-service-rn-python/references/source-map.md` for the broader
  React, React Native, Python, and official-document source map.
- The local durable owner named by the selected manifest entry before applying
  a reusable Tao Agent OS rule.

## Decision Rule

1. Match the task to the narrowest manifest entry.
2. If its disposition is `distilled`, load the named Tao owner and use the
   external skill only to check coverage or current source behavior.
3. If its disposition is `source_only`, read the provider source for that task
   without turning provider setup, commands, product policy, or prose into a
   shared Tao rule.
4. For a snapshot refresh, compare every recursive `SKILL.md` path and hash;
   account separately for installable skills and nested subskills.
5. Update a durable owner only when the rule remains correct after removing the
   provider, repository, product, command, and version-specific context.

## Common Rationalizations

| Rationalization | Required response |
| --- | --- |
| "The README says 32, so nested skills do not count." | Keep the 32 installable count and also validate every nested `SKILL.md`. |
| "The main best-practices card covers the provider." | Check each manifest entry; broad cards do not prove leaf coverage. |
| "Copying the source is the safest way to keep it." | Preserve provenance and hashes, then distill only reusable rules. |
| "A provider workflow should become the Tao default." | Keep provider/service operations `source_only` unless a provider-neutral owner exists. |

## Red Flags

- A source refresh changes a hash without a review decision.
- A provider commit is pinned to a HEAD that does not reproduce the reviewed
  bytes, which makes an unprovable snapshot look proven.
- One provider path is absent, duplicated, or assigned to a nonexistent owner.
- The two `react-native-best-practices` names are treated as one source.
- A local machine path appears in committed documentation or tests.
- EAS service commands, provider setup, or paid-service assumptions become
  shared baseline guidance.

## Do Not

- Do not vendor the external skill prose, examples, images, scripts, or
  provider repository layout.
- Do not infer snapshot freshness from a date alone when hashes are available.
- Do not collapse Callstack and Software Mansion sources because their skill
  names collide.
- Do not claim complete coverage from the 32 installable entries while ignoring
  the nine nested Software Mansion subskills.

## Stop If

- The checker reports a missing, unexpected, or hash-mismatched `SKILL.md`.
- The source license or provenance is unknown.
- No canonical Tao owner or explicit `source_only` decision can be named.
- Applying the source would conflict with repo-local instructions or current
  official framework behavior.

## Verification

- `python3 scripts/check_react_rn_external_skill_manifest.py`
- Add `--source-root <reviewed-snapshot>` to verify exact paths and hashes.
- Add `--remote-check` to compare each pinned commit with the provider's current
  remote HEAD; it needs network access and fails on an unpinned or unreachable
  provider, not on an upstream that merely moved.
- `python3 -m unittest tests.test_react_rn_external_skill_manifest`
- Run the React/RN source-coverage route smoke and
  `python3 scripts/workflow.py validate` after routing changes.

## Report

Report the snapshot label, matched provider and skill path, disposition, local
owner, checks run, and any source entries intentionally left `source_only`.
