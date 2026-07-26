---
keyflow_id: sys_graphify_project_integration_guidance
status: review
type: human-reviewed-needed
---

# Graphify Project Integration Guidance

Graphify has one common runtime skill and one generated graph per target
checkout. Do not turn the shared skill into a project asset.

## Ownership

The active Tao Agent OS source is:

```text
<TAO_ROOT>/.tao/skills/graphify/
  SKILL.md
  references/
  runtime/
  .graphify_version
```

User-level setup copies that bundle atomically and creates discovery links:

```text
~/.tao/skills/graphify/          # installed shared copy
~/.agents/skills/graphify             # link
~/.gemini/config/skills/graphify      # AGY link
~/.claude/skills/graphify             # link
~/.codex/skills/graphify              # link
```

The target checkout owns only:

```text
<TARGET_REPO>/.agents/local/graphify-out/
```

This directory is local generated state and is not a portable repository
artifact. Setup never writes the target repository's `.gitignore`, so keeping
this path out of version control is the target repository's own responsibility;
add it to that repository's ignore rules before building a graph. Worktrees may
have separate graph caches; they still use the same user-level skill.

The following target-project paths belong to the removed project-bundle design:

```text
.tao/skills/graphify
.agents/skills/graphify
.agents/rules/graphify.md
.agents/workflows/graphify.md
.claude/skills/graphify
.codex/skills/graphify
```

Setup and readiness must report these paths when present. Do not stage or commit
them as a repair.

The Tao Agent OS checkout itself is the one exception, because it is the runtime
source rather than a target: `.tao/skills/graphify` is the canonical bundle
defined above, and that repository self-hosts its own discovery links into that
same bundle. Readiness excuses those paths only there, and only when the path is
the bundle or a link resolving inside it. A copied bundle, or a link pointing
outside it, stays a reported leak even in the runtime source root.

## Global Setup

Install or inspect the common skill:

```bash
python3 <TAO_ROOT>/scripts/setup-project-graphify.py --global
python3 <TAO_ROOT>/scripts/setup-project-graphify.py --global --check
```

Global installation copies from the active runtime bundle; it does not invoke a
project Graphify installer and does not download a new skill. The Graphify CLI
remains a separate executable dependency.

`setup-agent-hooks.py` also refreshes this global copy and its user-level links
when Graphify is available. Runtime selection limits which user-level links are
checked; it never changes a target repository.

## Target Inspection

Inspect target graph readiness without repository mutation:

```bash
python3 <TAO_ROOT>/scripts/setup-project-graphify.py \
  --project <TARGET_REPO> \
  --check
```

An explicit target in `setup-agent-hooks.py` performs the same readiness check.
It does not install project skills, links, rules, workflows, hooks, or Git
policies. `--repair-input-policy` is a separate explicit operation and may
change only `.graphifyignore`.

Initial graph generation stays separate because extraction can involve source
scope, model/provider selection, time, and cost decisions.

## Graph Location

Run Graphify from the target root with the local output boundary:

```bash
GRAPHIFY_OUT=.agents/local/graphify-out graphify update .
GRAPHIFY_OUT=.agents/local/graphify-out graphify query "<scoped question>"
GRAPHIFY_OUT=.agents/local/graphify-out graphify path "<source>" "<target>"
GRAPHIFY_OUT=.agents/local/graphify-out graphify explain "<concept>"
```

The installed shared skill remains the operational source. Its build, query,
path, explain, update, and export instructions all use the explicit
`.agents/local/graphify-out` path and set `GRAPHIFY_OUT` on CLI invocations.
Do not fall back to the legacy root-level cache.

The managed `.graphifyignore` input block is narrow:

```text
# tao-graphify-inputs:start
.tao/
.agents/local/
graphify-out/
# tao-graphify-inputs:end
```

Do not rewrite `.gitignore`, unignore `.tao`, or narrow a repository's
`.claude`/`.codex` ignores to expose runtime links. Project-local knowledge under
`.agents/shared` remains graph input; `.agents/local` is intentionally excluded.

## Migration From Project Bundles

Setup has no removal mode. Deleting files from a target checkout is a
destructive action on someone else's repository, so `--check` reports the
leaked project-bundle paths listed above and stops there. Removal is a manual,
user-approved step:

1. Run `--check` to inventory target-project skill copies, links, adapters, Git
   policies, and graphs.
2. Confirm the active runtime bundle and user-level links are ready.
3. Preserve a usable generated graph by moving it to
   `.agents/local/graphify-out` when safe.
4. Ask the user before deleting, then remove only the reported setup-created
   project skill copies and adapter links.
5. Restore unrelated project instructions and ignore policy.
6. Verify `git status` contains no Graphify installation assets.
7. Re-run target readiness and a scoped query.

Do not remove product-owned documents merely because their names contain
`graphify`. Do not overwrite unrelated runtime settings. A project-local graph
cache is replaceable generated state; user changes and source documents are not.

## Freshness And Integrity

Readiness verifies the manifest against the current target inputs. The manifest
and graph are read from `.agents/local/graphify-out`. `built_at_commit` remains
diagnostic: a graph rebuilt from a dirty worktree can still be current when
manifest content hashes match.

The graph must be non-empty, parseable, and free of malformed nodes, dangling
edges, duplicate node ids, and self-loop edges. Project knowledge input checks
must preserve `.agents/shared` and other non-local agent documentation.
Document-to-code relationships improve query quality but are not mandatory for
an AST-only graph.

If an older Graphify CLI produced dangling or self-loop edges, repair only the
replaceable project-local graph:

```bash
python3 <TAO_ROOT>/scripts/setup-project-graphify.py \
  --project <TARGET_REPO> \
  --repair-graph-integrity
```

The repair preserves nodes, valid edges, metadata, and project sources. It does
not invoke an LLM or create project-local runtime assets.

Explicit source-path repair uses the same local graph:

```bash
python3 <TAO_ROOT>/scripts/setup-project-graphify.py \
  --project <TARGET_REPO> \
  --repair-document-links
```

The repair adds deterministic references only for real cited source paths. It
does not invoke an LLM or invent conceptual relationships.

## Workflow Gate Evidence

Graphify routes include a `graphify readiness` gate with these fields:

- `cli`: local Graphify executable verified.
- `skill_doc`: installed shared `~/.tao/skills/graphify/SKILL.md` read.
- `runtime_links`: enabled user-level links resolve to the shared copy.
- `runtime_ownership`: active runtime bundle is the source and target-project
  runtime assets are absent.
- `project_integration`: `.agents/local/graphify-out` is the output boundary.
- `graph`: target-local graph freshness, integrity, and input coverage.
- `query_smoke`: scoped query/path/explain result.

Every structural field must be exactly `success`. Put paths, versions, graph
counts, and query output in descriptive evidence rather than the status fields.

Presence of a shared skill does not prove the target graph exists. Presence of a
graph does not prove the shared skill was read or the query succeeded.

## Report

Report the active runtime bundle, installed global path, resolved user-level
links, target-project asset absence, local graph path, freshness/integrity/input
coverage, query result, and any remaining CLI or provider blocker.
