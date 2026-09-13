# graphify reference: optional commit hook and native AGENTS.md integration

Load this only when the user explicitly asked to install the post-commit hook or
wire Graphify into a project's AGENTS.md. Tao defaults to explicit, on-demand
refresh because automatic checkout/commit rebuilding adds cost to unrelated
small work.

## For git commit hook

This is an opt-in tradeoff. Install a post-commit hook only when the user values
an always-fresh graph more than the extra work after every commit. No background
process is needed; it triggers once per commit and works with any editor.

```bash
GRAPHIFY_OUT=.agents/local/graphify-out graphify hook install    # install
GRAPHIFY_OUT=.agents/local/graphify-out graphify hook uninstall  # remove
GRAPHIFY_OUT=.agents/local/graphify-out graphify hook status     # check
```

After every `git commit`, the hook detects which code files changed (via `git diff HEAD~1`), re-runs AST extraction on those files, and rebuilds `graph.json` and `GRAPH_REPORT.md`. Doc/image changes are ignored by the hook - run `/graphify --update` manually for those.

If a post-commit hook already exists, graphify appends to it rather than replacing it.

To return a Tao-managed project to on-demand refresh while preserving unrelated
hook content, preview and then apply the narrow removal helper:

```bash
<TAO_ROOT>/scripts/setup-project-graphify.py --project <TARGET_REPO> --disable-rebuild-hooks --check
<TAO_ROOT>/scripts/setup-project-graphify.py --project <TARGET_REPO> --disable-rebuild-hooks
```

---

## For native AGENTS.md integration

Run once per project to make graphify always-on in your agent sessions:

```bash
GRAPHIFY_OUT=.agents/local/graphify-out graphify agents install
```

This writes a `## graphify` section to the local `AGENTS.md` that instructs your agent to check the graph before answering codebase questions and rebuild it after code changes. No manual `/graphify` needed in future sessions.

```bash
GRAPHIFY_OUT=.agents/local/graphify-out graphify agents uninstall  # remove the section
```
