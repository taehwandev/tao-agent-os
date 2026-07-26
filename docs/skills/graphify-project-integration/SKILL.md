---
keyflow_id: sys_docs_graphify_project_integration_skill
status: review
type: human-reviewed-needed
tao_card_contract: strict
requires_docs:
  - docs/skills/agent-bootstrap/SKILL.md
  - common/skills/llm-wiki-documentation/SKILL.md
  - common/skills/verification-policy/SKILL.md
---

# Graphify Project Integration

Use when Tao Agent OS must install or verify the shared Graphify skill, or
when a target repository needs its own current local graph.

## Use When

- Installing or repairing the user-level Graphify skill and runtime discovery links.
- A route mentions Graphify or a missing target-project graph.
- A project Graphify setup leaked `.tao/skills/graphify` or
  runtime-specific Graphify links into a checkout.
- An agent skipped Graphify because the CLI, shared skill, or project graph was absent.

## Read

- `references/current-guidance.md` for the install and readiness procedure.
- `~/.tao/skills/graphify/SKILL.md` before building, updating, or querying
  a target graph. This user-level copy comes from the active runtime's bundled
  `.tao/skills/graphify`.

## Decision Rule

Keep ownership split into two boundaries:

1. The active Tao Agent OS owns the bundled Graphify skill and installs one
   user-level copy with user-level Codex, Claude, AGY, and generic-agent links.
2. Each target checkout owns only its ignored generated graph at
   `.agents/local/graphify-out`.

Target repositories do not own Graphify skill copies, `.tao` canonical bundles,
runtime discovery links, rule adapters, or Git-tracked Graphify installation
assets. Their presence is a failed project-integration condition.

Readiness has seven conditions: CLI available; shared user-level `SKILL.md`
installed and read; user-level runtime links resolving to it; shared runtime
ownership verified; project integration free of copied runtime assets; a fresh,
input-complete local graph; and a scoped query smoke check.

## Process

1. Identify the active runtime root and target repository.
2. Install or check the runtime-bundled skill at user level.
3. Read the installed shared `SKILL.md`.
4. Confirm runtime discovery links resolve under `~/.tao`, outside the target repo.
5. Remove project-local Graphify skill copies and links created by an obsolete setup.
6. Build or update the target graph with
   `GRAPHIFY_OUT=.agents/local/graphify-out`.
7. Run a scoped query/path/explain smoke check and record all seven readiness fields.

## Common Rationalizations

| Rationalization | Required response |
| --- | --- |
| "Every worktree needs its own skill copy." | Use the user-level runtime link; worktrees own only generated local graph state. |
| "The project bundle makes setup portable." | Common runtime behavior belongs to the active runtime, not a product repo. |
| "Git must own the Graphify skill." | Verify runtime ownership and local graph isolation; do not stage runtime assets in the target repo. |
| "There is no graph, so I will use grep." | Build or repair the target-local graph, or report the readiness failure. |
| "Setup can generate the graph automatically." | Keep model/provider and cost decisions in the shared skill flow. |

## Red Flags

- `.tao/skills/graphify` appears in a target checkout.
- `.agents/skills/graphify`, `.claude/skills/graphify`, or
  `.codex/skills/graphify` resolves inside the target checkout.
- A generated graph is written to tracked project paths.
- A setup command claims readiness from skill presence without a target graph or query.
- The global copy differs from the active runtime bundle after setup completes.

## Do Not

- Do not copy the Graphify skill into a project or worktree.
- Do not create project-local Graphify runtime links or adapter files.
- Do not require `git add`, a commit, or repository ignore allowlists for the shared skill.
- Do not copy graphs between repositories.
- Do not run package installation or model-backed extraction without required approval.
- Do not mark readiness from file presence alone.

## Stop If

- The target project or active runtime is ambiguous.
- The Graphify CLI is missing and installation requires new package/network authority.
- The shared skill requires an unapproved provider, model, or paid action.
- The graph input scope crosses repositories without an explicit merge scope.

## Verification

- CLI: `graphify` resolves locally.
- Skill doc: `~/.tao/skills/graphify/SKILL.md` matches the active runtime bundle and was read.
- Runtime links: user-level runtime skill links resolve to `~/.tao/skills/graphify`.
- Runtime ownership: no target-project Graphify skill or adapter asset exists.
- Project integration: graph output is `.agents/local/graphify-out`.
- Graph: `graph.json` is valid, current, input-complete, and has valid endpoints.
- Query smoke: a scoped `graphify query`, `path`, or `explain` call succeeds.

## Report

Report the seven readiness fields explicitly. Name the active runtime bundle,
installed user-level skill, resolved user-level links, absence of target-project
runtime assets, local graph path and integrity/freshness state, and query smoke
result. State separately whether the shared skill was installed and whether the
target graph was actually built.
