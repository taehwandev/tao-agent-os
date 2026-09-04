# graphify reference: query, path, explain

Load this when the user asks a question against an existing graph, or runs `/graphify path` or `/graphify explain`. The core's query stub points here for the full traversal flow. These flows use the `graphify query` CLI when it is available and fall back to an inline NetworkX traversal otherwise.

Two traversal modes - choose based on the question:

| Mode | Flag | Best for |
|------|------|----------|
| BFS (default) | _(none)_ | "What is X connected to?" - broad context, nearest neighbors first |
| DFS | `--dfs` | "How does X reach Y?" - trace a specific chain or dependency path |

### Resolve and validate the read graph

Do not guess the output directory from which paths happen to exist. Run Tao's
read-only readiness inspection first:

```bash
python3 <TAO_ROOT>/scripts/setup-project-graphify.py --project . --check --format json
```

Read `projects[0].readiness` from that output. Continue only when all three are
true: `graph_exists`, `graph_fresh`, and `graph_integrity_ready`. These are the
query safety fields; the broader `ready` field also checks global skill install
freshness and project knowledge coverage, which must be reported but does not
choose the query file. If the graph is missing, stale, or malformed, stop and
tell the user which field failed. Offer `/graphify <path> --update`; do not start
that potentially expensive write automatically.

Set the read directory to the parent of the exact reported `graph_path`, and
keep the write directory canonical:

```bash
GRAPHIFY_READ_OUT="<parent directory of readiness.graph_path>"
GRAPHIFY_WRITE_OUT="$(pwd -P)/.agents/local/graphify-out"
GRAPHIFY_GRAPH="$GRAPHIFY_READ_OUT/graph.json"
export GRAPHIFY_READ_OUT GRAPHIFY_WRITE_OUT GRAPHIFY_GRAPH
echo "Graph source: $GRAPHIFY_GRAPH"
```

The fallback `graphify-out/` location is read-only compatibility. Query, path,
and explain may read it. Vocabulary, reflection, saved-result, rebuild, and
export writes must continue to use `GRAPHIFY_WRITE_OUT`.

### Step 0 — Constrained query expansion (REQUIRED before traversal)

graphify's `query` CLI matches nodes via case-folded substring + IDF — there is **no stemming, no synonyms, no cross-language match** inside the binary, and the inline fallback below matches the same way. If the user's question uses different language or different domain vocabulary than the graph's labels (user says "обработчик" / graph says "handler"; user says "authentication" / graph says "Guardian"), the literal matcher returns 0 hits and the answer collapses to noise.

Fix this **without inventing tokens** by expanding the query against the actual graph vocabulary first:

1. Extract the token vocabulary from the selected graph's node labels. The
   reusable vocabulary cache is still written only to the canonical boundary:
```bash
GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" GRAPHIFY_WRITE_OUT="$GRAPHIFY_WRITE_OUT" $(cat "$GRAPHIFY_WRITE_OUT/.graphify_python") -c "
import json, os, re
from pathlib import Path
graph = Path(os.environ['GRAPHIFY_OUT']) / 'graph.json'
write_out = Path(os.environ['GRAPHIFY_WRITE_OUT'])
data = json.loads(graph.read_text(encoding='utf-8'))
vocab = set()
for n in data['nodes']:
    for c in re.findall(r'[^\W\d_]+', n.get('label','') or '', re.UNICODE):
        parts = re.findall(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+', c) or [c]
        for p in parts:
            t = p.lower()
            if 3 <= len(t) <= 30:
                vocab.add(t)
write_out.mkdir(parents=True, exist_ok=True)
(write_out / '.vocab.txt').write_text('\n'.join(sorted(vocab)), encoding='utf-8')
print(f'vocab: {len(vocab)} tokens')
"
```

2. Read `$GRAPHIFY_WRITE_OUT/.vocab.txt`. Then for the user's question, select
   **up to 12 tokens from this exact list** that semantically match the query
   intent. Hard constraints:
   - You MUST pick only tokens present in the vocabulary file. Do NOT invent tokens.
   - If a query concept has no plausible token in the vocab, skip it — do not substitute a near-synonym from training memory.
   - If **no** vocab tokens match the query at all, output an empty list and tell the user the corpus has no relevant vocabulary for this question. Do not fabricate a search.
   - Translate cross-language: Russian "аутентификация" → look for `auth`, `credential`, `token`, `security` IFF present in vocab.
   - Morphology: "handlers" maps to `handler` IFF present; "todos" maps to `todo` IFF present.

3. Print the selection explicitly to the user before running the query, so the expansion is auditable:
```
Query expanded to (from graph vocab, N tokens): [token1, token2, ...]
```
If the list is empty, say so plainly and stop — do not proceed to traversal.

### Step 1 — Traversal

Build the **expanded query string** by joining the selected tokens with spaces. Use this string as `QUESTION` below — NOT the original user question. (The original question is preserved only for `save-result` at the end.)

Prefer the CLI when it is installed:
```bash
GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" graphify query "QUESTION"
# or:
GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" graphify query "QUESTION" --dfs --budget 3000
```

If the CLI is unavailable, load `$GRAPHIFY_GRAPH` and run the traversal inline:

1. Find the 1-3 nodes whose label best matches the expanded tokens.
2. Run the appropriate traversal from each starting node.
3. Read the subgraph - node labels, edge relations, confidence tags, source locations.
4. Answer using **only** what the graph contains. Quote `source_location` when citing a specific fact.
5. If the graph lacks enough information, say so - do not hallucinate edges.

```bash
GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" $(cat "$GRAPHIFY_WRITE_OUT/.graphify_python") -c "
import sys, json, os
from networkx.readwrite import json_graph
import networkx as nx
from pathlib import Path

data = json.loads((Path(os.environ['GRAPHIFY_OUT']) / 'graph.json').read_text(encoding='utf-8'))
G = json_graph.node_link_graph(data, edges='links')

question = 'QUESTION'
mode = 'MODE'  # 'bfs' or 'dfs'
terms = [t.lower() for t in question.split() if len(t) >= 3]  # match the vocab threshold; keeps api/jwt/ios (#1392)

# Find best-matching start nodes
scored = []
for nid, ndata in G.nodes(data=True):
    label = ndata.get('label', '').lower()
    score = sum(1 for t in terms if t in label)
    if score > 0:
        scored.append((score, nid))
scored.sort(reverse=True)
start_nodes = [nid for _, nid in scored[:3]]

if not start_nodes:
    print('No matching nodes found for query terms:', terms)
    sys.exit(0)

subgraph_nodes = set()
subgraph_edges = []

if mode == 'dfs':
    # DFS: follow one path as deep as possible before backtracking.
    # Depth-limited to 6 to avoid traversing the whole graph.
    visited = set()
    stack = [(n, 0) for n in reversed(start_nodes)]
    while stack:
        node, depth = stack.pop()
        if node in visited or depth > 6:
            continue
        visited.add(node)
        subgraph_nodes.add(node)
        for neighbor in G.neighbors(node):
            if neighbor not in visited:
                stack.append((neighbor, depth + 1))
                subgraph_edges.append((node, neighbor))
else:
    # BFS: explore all neighbors layer by layer up to depth 3.
    frontier = set(start_nodes)
    subgraph_nodes = set(start_nodes)
    for _ in range(3):
        next_frontier = set()
        for n in frontier:
            for neighbor in G.neighbors(n):
                if neighbor not in subgraph_nodes:
                    next_frontier.add(neighbor)
                    subgraph_edges.append((n, neighbor))
        subgraph_nodes.update(next_frontier)
        frontier = next_frontier

# Token-budget aware output: rank by relevance, cut at budget (~4 chars/token)
token_budget = BUDGET  # default 2000
char_budget = token_budget * 4

# Score each node by term overlap for ranked output
def relevance(nid):
    label = G.nodes[nid].get('label', '').lower()
    return sum(1 for t in terms if t in label)

ranked_nodes = sorted(subgraph_nodes, key=relevance, reverse=True)

lines = [f'Traversal: {mode.upper()} | Start: {[G.nodes[n].get(\"label\",n) for n in start_nodes]} | {len(subgraph_nodes)} nodes']
for nid in ranked_nodes:
    d = G.nodes[nid]
    lines.append(f'  NODE {d.get(\"label\", nid)} [src={d.get(\"source_file\",\"\")} loc={d.get(\"source_location\",\"\")}]')
for u, v in subgraph_edges:
    if u in subgraph_nodes and v in subgraph_nodes:
        _raw = G[u][v]; d = next(iter(_raw.values()), {}) if isinstance(G, nx.MultiGraph) else _raw
        lines.append(f'  EDGE {G.nodes[u].get(\"label\",u)} --{d.get(\"relation\",\"\")} [{d.get(\"confidence\",\"\")}]--> {G.nodes[v].get(\"label\",v)}')

output = '\n'.join(lines)
if len(output) > char_budget:
    output = output[:char_budget] + f'\n... (truncated at ~{token_budget} token budget - use --budget N for more)'
print(output)
"
```

Replace `QUESTION` with the **expanded** query string, `MODE` with `bfs` or `dfs`, and `BUDGET` with the token budget (default `2000`, or whatever `--budget N` specifies). Then answer based on the subgraph output above, using only what the graph contains.

After writing the answer, save it back only when the selected graph already
lives on the canonical write boundary. Include the expanded tokens inside the
`--answer` text (e.g. `"Expanded from original query via vocab: [tokens]. Then
traversed..."`) so the next `--update` extracts the expansion history as a graph
node:

```bash
if [ "$GRAPHIFY_READ_OUT" = "$GRAPHIFY_WRITE_OUT" ]; then
    GRAPHIFY_OUT="$GRAPHIFY_WRITE_OUT" $(cat "$GRAPHIFY_WRITE_OUT/.graphify_python") -m graphify save-result --question "ORIGINAL_QUESTION" --answer "ANSWER" --type query --nodes NODE1 NODE2
else
    echo "Skipped Graphify memory write: the selected graph is the read-only fallback."
fi
```

Replace `ORIGINAL_QUESTION` with the user's verbatim question, `ANSWER` with your full answer text (containing the expanded-token trace), `NODE1 NODE2` with the list of node labels you cited. This closes the feedback loop: the next `--update` will extract this Q&A as a node in the graph.

**Work memory (self-improving loop).** Add an `--outcome` so future sessions learn from this one — append `--outcome useful|dead_end|corrected` to the `save-result` command (and `--correction "the right answer"` when correcting):

- `useful` — the cited nodes answered the question well (they become *preferred sources*).
- `dead_end` — the question/path led nowhere; don't re-derive it next time.
- `corrected` — the saved answer was wrong; `--correction` records what was right.

At the **start** of graph work, refresh and read lessons only when the selected
graph is canonical:

```bash
if [ "$GRAPHIFY_READ_OUT" = "$GRAPHIFY_WRITE_OUT" ]; then
    GRAPHIFY_OUT="$GRAPHIFY_WRITE_OUT" graphify reflect --if-stale
fi
```

Then read `$GRAPHIFY_WRITE_OUT/reflections/LESSONS.md` when it exists. The
command is cheap and deterministic; `--if-stale` makes it a no-op when the
lessons are already newer than every canonical input. A fallback query never
writes reflections or saved results beside the fallback graph.

---

## For /graphify path

Find the shortest path between two named concepts in the graph. Prefer the CLI when installed:

```bash
GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" graphify path "NODE_A" "NODE_B"
```

If the CLI is unavailable, run it inline:

```bash
GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" $(cat "$GRAPHIFY_WRITE_OUT/.graphify_python") -c "
import json, os, sys
import networkx as nx
from networkx.readwrite import json_graph
from pathlib import Path

data = json.loads((Path(os.environ['GRAPHIFY_OUT']) / 'graph.json').read_text(encoding='utf-8'))
G = json_graph.node_link_graph(data, edges='links')

a_term = 'NODE_A'
b_term = 'NODE_B'

def find_node(term):
    term = term.lower()
    scored = sorted(
        [(sum(1 for w in term.split() if w in G.nodes[n].get('label','').lower()), n)
         for n in G.nodes()],
        reverse=True
    )
    return scored[0][1] if scored and scored[0][0] > 0 else None

src = find_node(a_term)
tgt = find_node(b_term)

if not src or not tgt:
    print(f'Could not find nodes matching: {a_term!r} or {b_term!r}')
    sys.exit(0)

try:
    path = nx.shortest_path(G, src, tgt)
    print(f'Shortest path ({len(path)-1} hops):')
    for i, nid in enumerate(path):
        label = G.nodes[nid].get('label', nid)
        if i < len(path) - 1:
            _raw = G[nid][path[i+1]]; edge = next(iter(_raw.values()), {}) if isinstance(G, nx.MultiGraph) else _raw
            rel = edge.get('relation', '')
            conf = edge.get('confidence', '')
            print(f'  {label} --{rel}--> [{conf}]')
        else:
            print(f'  {label}')
except nx.NetworkXNoPath:
    print(f'No path found between {a_term!r} and {b_term!r}')
except nx.NodeNotFound as e:
    print(f'Node not found: {e}')
"
```

Replace `NODE_A` and `NODE_B` with the actual concept names from the user. Then explain the path in plain language - what each hop means, why it's significant.

After writing the explanation, save it back:

```bash
if [ "$GRAPHIFY_READ_OUT" = "$GRAPHIFY_WRITE_OUT" ]; then
    GRAPHIFY_OUT="$GRAPHIFY_WRITE_OUT" $(cat "$GRAPHIFY_WRITE_OUT/.graphify_python") -m graphify save-result --question "Path from NODE_A to NODE_B" --answer "ANSWER" --type path_query --nodes NODE_A NODE_B
fi
```

---

## For /graphify explain

Give a plain-language explanation of a single node - everything connected to it. Prefer the CLI when installed:

```bash
GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" graphify explain "NODE_NAME"
```

If the CLI is unavailable, run it inline:

```bash
GRAPHIFY_OUT="$GRAPHIFY_READ_OUT" $(cat "$GRAPHIFY_WRITE_OUT/.graphify_python") -c "
import json, os, sys
import networkx as nx
from networkx.readwrite import json_graph
from pathlib import Path

data = json.loads((Path(os.environ['GRAPHIFY_OUT']) / 'graph.json').read_text(encoding='utf-8'))
G = json_graph.node_link_graph(data, edges='links')

term = 'NODE_NAME'
term_lower = term.lower()

# Find best matching node
scored = sorted(
    [(sum(1 for w in term_lower.split() if w in G.nodes[n].get('label','').lower()), n)
     for n in G.nodes()],
    reverse=True
)
if not scored or scored[0][0] == 0:
    print(f'No node matching {term!r}')
    sys.exit(0)

nid = scored[0][1]
data_n = G.nodes[nid]
print(f'NODE: {data_n.get(\"label\", nid)}')
print(f'  source: {data_n.get(\"source_file\",\"unknown\")}')
print(f'  type: {data_n.get(\"file_type\",\"unknown\")}')
print(f'  degree: {G.degree(nid)}')
print()
print('CONNECTIONS:')
for neighbor in G.neighbors(nid):
    _raw = G[nid][neighbor]; edge = next(iter(_raw.values()), {}) if isinstance(G, nx.MultiGraph) else _raw
    nlabel = G.nodes[neighbor].get('label', neighbor)
    rel = edge.get('relation', '')
    conf = edge.get('confidence', '')
    src_file = G.nodes[neighbor].get('source_file', '')
    print(f'  --{rel}--> {nlabel} [{conf}] ({src_file})')
"
```

Replace `NODE_NAME` with the concept the user asked about. Then write a 3-5 sentence explanation of what this node is, what it connects to, and why those connections are significant. Use the source locations as citations.

After writing the explanation, save it back:

```bash
if [ "$GRAPHIFY_READ_OUT" = "$GRAPHIFY_WRITE_OUT" ]; then
    GRAPHIFY_OUT="$GRAPHIFY_WRITE_OUT" $(cat "$GRAPHIFY_WRITE_OUT/.graphify_python") -m graphify save-result --question "Explain NODE_NAME" --answer "ANSWER" --type explain --nodes NODE_NAME
fi
```
