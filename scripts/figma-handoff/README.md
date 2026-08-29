---
keyflow_id: sys_figma_handoff_tool_readme
status: review
type: ai-generated
---

# Figma Handoff CLI

`scripts/figma-handoff/` owns a standalone tool that extracts screen structure,
frame renders, individual assets, and implementation measurements from the
Figma REST API. It depends on no external CLI repository, sibling clone,
installed skill, or specific AI runtime: Python standard library only, and one
Tao Agent OS checkout carries both the executable code and its verification
material.

The CLI does not generate code. `common/skills/figma-handoff/SKILL.md` owns the
procedure that selects the target repository and platform and applies the
handoff this tool produces to a real implementation.

## Requirements And Token Setup

- Python 3.9 or newer
- Network access to the Figma REST API for real extraction
- A Figma personal access token with read access to the target file

The CLI reads the token only from an environment variable. It sends read
requests only, but a Figma personal access token can expose the Figma data
available to its account, so treat it as a high-sensitivity secret. Figma's
current account-settings flow is documented in [Manage personal access tokens]
(https://help.figma.com/hc/en-us/articles/8085703771159-Manage-personal-access-tokens).

For a local interactive run, create the token in Figma and enter it only at a
hidden prompt. The value is not stored in this repository or in shell history:

```bash
read -r -s FIGMA_TOKEN
export FIGMA_TOKEN
```

Paste the token when prompted, then run the CLI. To use a different variable
name, repeat the same pattern and pass `--token-env`:

```bash
read -r -s FIGMA_READ_TOKEN
export FIGMA_READ_TOKEN
python3 scripts/figma-handoff/figma-handoff.py \
  --url "https://www.figma.com/design/<FILE_KEY>/<FILE_NAME>?node-id=123-456" \
  --name "feature-screen" \
  --token-env FIGMA_READ_TOKEN
```

Do not put a token value in arguments, documents, prompts, logs, outputs, or
commits. Check presence without printing the value and clear it after use:

```bash
test -n "${FIGMA_TOKEN:-}" && echo "FIGMA_TOKEN is set"
unset FIGMA_TOKEN
```

Use `--dry-run` when you only need to validate the URL and output plan; it does
not require a token or network access.

Figma Dev Mode is not required for the base handoff. Node structure, frame
renders, styles, components, and exportable assets use the ordinary REST API.
Variable metadata is an optional enrichment: when `/variables/local` is denied
by the account, plan, or file permission, the CLI records a warning and still
produces the rest of the bundle. A token alone cannot prove file access, so use
the live smoke only with a small file the token is actually allowed to read.

## Running

From the repository root:

```bash
python3 scripts/figma-handoff/figma-handoff.py \
  --url "https://www.figma.com/design/<FILE_KEY>/<FILE_NAME>?node-id=123-456" \
  --name "feature-screen" \
  --out "/path/to/work-output" \
  --export-assets
```

The entrypoint loads its sibling modules directly regardless of the current
working directory, including under Python isolated mode
(`python3 -I scripts/figma-handoff/figma-handoff.py ...`). When `--out` is
omitted, bundles are created under the hidden local workspace
`.figma-handoff-work/` in the current working directory. That path is
git-ignored and never promoted to a tracked repository asset.

To resolve inputs and output locations without a network or token:

```bash
python3 scripts/figma-handoff/figma-handoff.py \
  --url "https://www.figma.com/design/<FILE_KEY>/<FILE_NAME>?node-id=123-456" \
  --name "feature-screen" \
  --dry-run
```

Large SECTION nodes split into a full-structure pass and per-screen renders:

```bash
python3 scripts/figma-handoff/figma-handoff.py \
  --file-key <KEY> --node-id <SECTION_NODE> --name flow --no-images

python3 scripts/figma-handoff/figma-handoff.py \
  --file-key <KEY> --node-id <SCREEN_NODE> --name flow-screen \
  --max-flow-depth 0 --scale 1
```

## Option Contract

| Option | Default | Description |
|---|---|---|
| `--url` | none | Figma design/file/proto URL containing a `node-id` |
| `--file-key`, `--node-id` | none | Name the target directly instead of a URL |
| `--name` | node-id based | Bundle name, normalized to a path-safe slug |
| `--out` | `<cwd>/.figma-handoff-work` | Git-ignored local bundle workspace |
| `--format` | `png` | Frame render format: png, jpg, svg, pdf |
| `--scale` | `2.0` | png/jpg render scale; Figma allows 0.01-4 |
| `--max-flow-depth` | `4` | Depth of prototype transitions to follow |
| `--no-images` | off | Fetch JSON only, skip frame renders |
| `--include-image-fills` | off | Also collect the file-level image-fill URL map |
| `--export-assets` | off | Render vectors as SVG and image fills as PNG individually |
| `--max-assets` | unlimited | Cap on unique assets rendered after dedup |
| `--timeout` | `60` | Request timeout in seconds |
| `--token-env` | `FIGMA_TOKEN` | Environment variable holding the token |
| `--dry-run` | off | Resolve inputs and print the plan JSON only |

## Output Contract

```text
<out>/<name>/
├── frames/                   screen frame renders
├── assets/                   --export-assets results
├── raw/                      raw node/style payloads and render availability metadata
├── summary/
│   ├── design-handoff.md     human-readable, truncatable summary
│   └── design-summary.json   source of truth for full implementation measurements
└── manifest.json             schemaVersion, run options, item counts
```

`design-summary.json` fields and units are defined by the
[design-summary schema](docs/design-summary-schema.md). `design-handoff.md`
truncates long lists, so it is not the authoritative text for exact values.
Schema v4 makes effective visibility an explicit implementation allowlist,
keeps excluded nodes as negative evidence, and attaches rendered paint stacks
to their owning nodes.
API and tool reproduction limits follow the
[fidelity document](docs/fidelity-and-limits.md).

`imagePath` and `assetPath` are recorded relative to the bundle root, so the
whole bundle directory can move to another team, a CI workspace, or a
file-reading AI without path rewrites.

CLI exit status:

- `0`: dry-run or bundle creation completed; some asset/Variables failures may
  remain in `warnings`
- `1`: execution failure during Figma calls or required node processing
- `2`: missing input, invalid URL/node, or missing token environment variable
- `130`: user interrupt

## Package Layers And The Execution Boundary

| Layer | Path | Role | Required to run the CLI |
|---|---|---|---|
| Executable code | `figma-handoff.py`, `figma_*.py`, `figma_validate.py` | Figma calls, analysis, bundle creation, in-flight validation | yes |
| Usage procedure and contract | `../../common/skills/figma-handoff/`, `docs/` | Source text for AIs and humans selecting work and interpreting results | no |
| Development and verification | repository `tests/test_figma_*`, `live_smoke.py` | Offline regression and optional real-API smoke | no |
| Local workspace | `<cwd>/.figma-handoff-work/` | Raw payloads, frames, assets, and bundles created during runs | no |

Executable code never imports tests, `live_smoke.py`, or Markdown. Real Figma
extracts and intermediate outputs live only in the hidden local workspace and
are never committed.

### Executable Code Structure

| File | Responsibility |
|---|---|
| `figma-handoff.py` | stable executable entrypoint |
| `figma_cli.py`, `figma_cli_arguments.py` | orchestration and argument validation |
| `figma_api.py` | authenticated same-origin REST requests and credential-free public asset downloads |
| `figma_flow_fetch.py`, `figma_metadata_fetch.py`, `figma_render.py` | flow traversal, optional metadata, and frame/asset rendering |
| `figma_style_parse.py`, `figma_variable_parse.py` | named/referenced style and variable parsing |
| `figma_*_analysis.py` | color, interaction, layout, component, and asset analysis by concern |
| `figma_summary.py`, `figma_markdown.py`, `figma_manifest.py` | summary, Markdown, and manifest generation |
| `figma_coverage.py`, `figma_summary_validate.py`, `figma_validation_report.py` | validation and fidelity reporting by concern |
| `figma_util.py` | URL, node id, color, gradient, JSON helpers |
| `figma_validate.py` | stable validation CLI entrypoint |

Only API/fetch/render modules own the network. Parse, analysis, summary, and
validation stay deterministic and network-free. The small `figma_analyze.py`,
`figma_parse.py`, and `figma_report.py` files are import-compatibility facades;
they own no processing logic. When the output schema changes, update the schema
document, summary validator, synthetic fidelity fixture, and manifest
`schemaVersion` together.

## Verification

```bash
python3 -m py_compile scripts/figma-handoff/figma-handoff.py \
  scripts/figma-handoff/figma_*.py scripts/figma-handoff/live_smoke.py
python3 -m unittest discover -s tests -p 'test_figma*.py'

python3 scripts/figma-handoff/figma-handoff.py \
  --url "https://www.figma.com/design/FILE/Name?node-id=1-2" \
  --name standalone-check --dry-run
```

Validate a produced bundle with:

```bash
python3 scripts/figma-handoff/figma_validate.py \
  /path/to/bundle/summary/design-summary.json
```

Run the real-API smoke only with a token already loaded in the environment and
a test frame URL that the caller is authorized to use:

```bash
python3 scripts/figma-handoff/live_smoke.py \
  --url "$FIGMA_SMOKE_URL" --scale 3
```

Detailed gates live in the [verification harness](docs/verification.md).

## Safety Boundary

- Tokens are read only from environment variables and never written to
  outputs, manifests, or logs.
- Authenticated requests are restricted to `https://api.figma.com`; redirects
  cannot carry the token to another origin.
- Signed render downloads never receive the token. Each HTTPS target and
  redirect is checked against local/private addresses, streamed under a size
  cap, and validated against its expected PNG/JPEG/SVG/PDF signature before an
  atomic output replace.
- Produced bundles and `raw/` contain real design content; follow the target
  team's storage and sharing policy.
- The default `.figma-handoff-work/` and any explicit one-off output location
  are local work artifacts and are never added to Git.
- Signed render URLs are not stored in ordinary render metadata or error
  messages. With `--include-image-fills`, the requested image-fill URL map IS
  included under `raw/`; treat it as sensitive short-lived output.
- Offline unit tests mock the network functions and never call the real
  Figma API.
- A full-frame image is a visual comparison reference, not an implementation
  result.
