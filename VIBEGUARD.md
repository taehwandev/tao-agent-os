---
keyflow_id: sys_vibeguard_policy
status: review
type: human-reviewed-needed
---

# [VIBEGUARD.md](http://VIBEGUARD.md)

This repository requires VibeGuard as the preflight safety gate for maintaining Tao Agent OS itself.

## Scope

This file applies to edits in the Tao Agent OS repository. It should not be treated as downstream policy for every repository that links to Tao Agent OS.

Tao Agent OS remains a reusable guidance library. VibeGuard remains the required setup, update, audit, prompt, evidence, and safe-fix CLI.

## Execution Policy

VibeGuard is required. For normal Tao Agent OS maintenance, prefer an
installed `vibeguard` binary when the environment provides one:

```bash
vibeguard <command> [project]
```

Use the published package command only when no trusted installed binary is
available, when bootstrapping a machine, or when a task explicitly needs the
latest published package:

```bash
npx --yes @taehwandev/vibeguard <command> [project]
```

Do not use `npx` as the first choice in routine agent hooks or repeated local
maintenance, because it may contact the npm registry and wait through network
retry timeouts even when the audit itself is fast. A local checkout command is
allowed only when validating VibeGuard itself or when the package command cannot
run and the checkout is trusted. If VibeGuard cannot run from any approved
source, stop and report the blocker instead of continuing without the safety
gate.

## Audit Commands

Run an installed binary during normal Tao Agent OS maintenance:

```bash
vibeguard audit . --rules .
```

Use the package command only as the fallback or explicit latest-package path:

```bash
npx --yes @taehwandev/vibeguard audit . --rules .
```

Use `vibeguard` as the canonical command name. Do not document deprecated hyphenated command spellings for new setup.

Use a local checkout only when validating local VibeGuard changes:

```bash
node <VIBEGUARD_ROOT>/src/cli.js audit . --rules .
```

## Auxiliary Commands

Use the prompt command only when a user or runtime wants a generated safety prompt for a concrete request:

```bash
vibeguard prompt . --request "<request>" --rules .
```

Use evidence only when the target runtime has an execution evidence adapter or session evidence available:

```bash
vibeguard evidence .
vibeguard evidence install-claude-hook .
```

## Setup And Fix Policy

- Before running `setup` or `update` in a target repo, inspect existing repo-local instructions, `.vibeguard.json`, `VIBEGUARD.md`, and managed VibeGuard blocks.

- If the target already has instructions or guardrails, ask an application drill before changing files: add pointer vs merge vs pin; audit-only vs refresh with update vs first-time setup; apply now vs prepare instructions only.

- Existing custom guardrails should default to audit-only unless the user chooses to refresh the managed block.

- Initial Tao Agent OS application in a repo with no guardrails should use the current VibeGuard command policy with the selected Tao Agent OS root as `--rules`. Prefer `vibeguard` when installed, otherwise use the package command:

  ```bash
  vibeguard setup . --rules <TAO_ROOT>
  vibeguard audit . --fix --rules <TAO_ROOT>
  vibeguard audit . --rules <TAO_ROOT>
  ```

- Existing managed VibeGuard guardrails should be refreshed with `vibeguard update . --rules <TAO_ROOT>` only when that mode is selected, then checked with `vibeguard audit . --rules <TAO_ROOT>`. Use the package command only if no trusted binary is installed or the user explicitly requests the latest published package.

- If an audit-only run reports `Needs review` solely because the managed
  guardrails exceeded their refresh interval, do not turn that advisory into
  an unauthorized `update`. A review or finish hook may accept that exact
  advisory with `--allow-vibeguard-review` and a concrete reason stating that
  refresh was not selected. This accepts the already executed audit; it does
  not skip it. Any additional security, cost, data, structure, repository, or
  environment finding remains blocking and requires its own resolution.

- Normal Tao Agent OS maintenance should run audit-only before editing and before finishing.

- Use `--fix` only after audit output shows low-risk safety fixes such as env ignore rules, value-free `.env.example` updates, or simple secret quarantine.

- Do not use `--fix` for code rewrites, dependency changes, data changes, credential rotation, deletion, deployment, or release work without explicit approval.

## Rules

- Do not print detected secret values.
- Keep real secrets only in ignored local env files or deployment secret stores.
- Keep `.env.example` value-free.
- Ask before deleting data, running migrations, deploying, changing credentials, or increasing paid API/model usage.
- For target repos that apply Tao Agent OS, apply VibeGuard with the selected Tao Agent OS root as `--rules`.
- For normal Tao Agent OS repository maintenance, run `audit . --rules .` before editing and before finishing.
- When an execution evidence adapter is configured, run `vibeguard evidence .` before final reporting and do not claim checks that are not supported by command output or evidence.

## Verification

Before finishing Tao Agent OS changes, run:

```bash
<TAO_LAUNCHER> workflow validate
vibeguard audit . --rules .
```
