# graphify reference: GitHub clone and cross-repo merge

Load this when the user passed one or more `https://github.com/...` URLs, or named several local subfolders to merge into one graph.

### Step 0 - Clone GitHub repo(s) (only if a GitHub URL was given)

**Single repo:**
```bash
LOCAL_PATH=$(GRAPHIFY_OUT=.agents/local/graphify-out graphify clone <github-url> [--branch <branch>])
# Use LOCAL_PATH as the target for all subsequent steps
```

**Multiple repos (cross-repo graph):**
```bash
# Clone each repo, run the full pipeline on each, then merge
GRAPHIFY_OUT=.agents/local/graphify-out graphify clone <url1>   # → ~/.graphify/repos/<owner1>/<repo1>
GRAPHIFY_OUT=.agents/local/graphify-out graphify clone <url2>   # → ~/.graphify/repos/<owner2>/<repo2>
# Run /graphify on each local path to produce their graph.json files
# Then merge:
GRAPHIFY_OUT=.agents/local/graphify-out graphify merge-graphs \
  ~/.graphify/repos/<owner1>/<repo1>/.agents/local/graphify-out/graph.json \
  ~/.graphify/repos/<owner2>/<repo2>/.agents/local/graphify-out/graph.json \
  --out .agents/local/graphify-out/cross-repo-graph.json
```

Graphify clones into `~/.graphify/repos/<owner>/<repo>` and reuses existing clones on repeat runs. Each node in the merged graph carries a `repo` attribute so you can filter by origin.

**Multiple local subfolders (monorepo or multi-service layout):**

The skill pipeline writes all intermediate and final outputs to `.agents/local/graphify-out/` in the current working directory. Running the skill on each subfolder separately will clobber the same output dir. Instead, use the CLI directly for each subfolder — it places `.agents/local/graphify-out/` *inside* the scanned path:

```bash
GRAPHIFY_OUT=.agents/local/graphify-out graphify extract ./core/     # → ./core/.agents/local/graphify-out/graph.json
GRAPHIFY_OUT=.agents/local/graphify-out graphify extract ./service/  # → ./service/.agents/local/graphify-out/graph.json
GRAPHIFY_OUT=.agents/local/graphify-out graphify extract ./platform/ # → ./platform/.agents/local/graphify-out/graph.json
# Add --backend gemini|kimi|openai|deepseek|claude-cli depending on which API key you have set

# Then merge at the project root:
GRAPHIFY_OUT=.agents/local/graphify-out graphify merge-graphs \
  ./core/.agents/local/graphify-out/graph.json \
  ./service/.agents/local/graphify-out/graph.json \
  ./platform/.agents/local/graphify-out/graph.json \
  --out .agents/local/graphify-out/graph.json
```

Once `.agents/local/graphify-out/graph.json` exists, the fast path above takes
over: any codebase question follows `references/query.md`, validates the graph,
and queries the readiness-selected `GRAPHIFY_READ_OUT` — no re-extraction or
size gate.
