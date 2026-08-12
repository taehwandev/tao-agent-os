---
keyflow_id: sys_figma_handoff_verification
status: review
type: ai-generated
---

# Verification Harness

Figma handoff verification has three layers: offline regression, generated
bundle validation, and optional live smoke testing. It does not require a
specific team's token or Figma file as a default fixture.

## 1. Offline Regression

The tests mock `request_json` and `download_file`; they do not use the network.

- `test_figma_handoff.py`: URL/node parsing, fetch batching, prototype flow,
  styles, variables, asset formats, and fallback behavior
- `test_figma_asset_dedup_parallel.py`: asset-signature deduplication, batching,
  and asset caps
- `test_figma_fidelity_harness.py`: synthetic golden coverage for rotation,
  opacity, strokes, masks, blend modes, gradients, variable aliases, and text runs
- `test_figma_standalone.py`: dry-run behavior from another working directory,
  Python isolated mode, default output, and safe error information
- `test_figma_secrets_boundary.py`: local-path, token-material, and runtime
  import boundaries

Run from the repository root:

```bash
python3 -m py_compile scripts/figma-handoff/figma-handoff.py \
  scripts/figma-handoff/figma_*.py scripts/figma-handoff/live_smoke.py
python3 -m unittest \
  tests.test_figma_handoff \
  tests.test_figma_standalone \
  tests.test_figma_asset_dedup_parallel \
  tests.test_figma_fidelity_harness \
  tests.test_figma_secrets_boundary
```

Every offline test must pass without a token or Figma network access. New fetch
behavior must go through the existing network mocks.

## 2. Bundle Validator

`figma_validate.py` reads any `design-summary.json` and checks schema invariants
and fidelity coverage.

```bash
python3 scripts/figma-handoff/figma_validate.py \
  <bundle>/summary/design-summary.json
```

- Exit `0`: no schema violations
- Exit `1`: schema invariant violation
- Exit `2`: argument or file-read failure

The CLI runs the same validator during bundle creation and reports problems in
`warnings` and stderr. When adding or changing summary fields, update the
validator, schema document, and synthetic fidelity fixture together.

## 3. Live Smoke

`live_smoke.py` calls the real Figma API to check frame downloads, asset format
selection, and image-fill recovery. It has no embedded default URL; provide a
small frame URL that the caller is authorized to use.

```bash
python3 scripts/figma-handoff/live_smoke.py \
  --url "$FIGMA_SMOKE_URL" --scale 3
```

Use `--quick` to skip asset export and check only the schema, frame PNG, and
layout coverage. Use `--token-env` to select a different environment variable.

- If the token environment variable is missing, the harness prints `SKIP` and exits `0`.
- If a token is present but the URL is missing, it reports a usage error.
- It writes real artifacts to a temporary directory and removes them on exit.
- It does not print tokens or signed render URLs.

Offline tests do not prove behavior that requires the real API. Conversely, a
token-less CI environment should not treat the intentional live-smoke skip as a
failure.

## 4. Documentation And Independence Checks

Before release, also verify that:

- Markdown links in the skill and tool point to files that exist in this checkout
- shared execution docs contain no external CLI checkout, personal absolute
  path, company identifier, or AI-runtime-specific fallback
- `.figma-handoff-work/`, legacy output directories, tokens, signed URLs, and
  Python caches are not tracked
- the token setup instructions use an environment variable or secret manager,
  never a command-line argument or checked-in file
