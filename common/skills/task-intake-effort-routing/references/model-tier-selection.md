---
keyflow_id: sys_task_intake_model_tier_selection
status: stable
type: human-reviewed-needed
---

# Model Tier Selection

Read when a runtime chooses a model, reasoning level, or worker tier from the
effort profile in `current-guidance.md`.

Model tier is a runtime-neutral routing result. Do not make Codex model names the
shared workflow policy; they are one runtime mapping for the abstract tier.

| Effort | Model Tier | Codex Mapping | Typical Work |
| --- | --- | --- | --- |
| `quick` | `fast` | `gpt-5.6-luna` | exact search, small status checks, narrow docs lookup, read-only test reruns, low-risk summaries |
| `standard` | `balanced` | `gpt-5.6-terra` | scoped code edits, documentation updates, normal review, focused debugging |
| `deep` | `frontier` | `gpt-5.6-sol` | architecture, security/data/release risk, cross-module changes, repeated failure recovery, broad planning |
| `specialist` | `specialist` | `gpt-5.6-sol` unless a runtime specialist is configured | platform/security/release/billing/auth/database/AI-tooling expert work |

Runtime rules:

- Codex may map `fast` / `balanced` / `frontier` to the configured Luna / Terra /
  Sol model ids above when those models are available.
- Luna is not a code-authoring tier. A Codex dispatch may use it only for a
  read-only, non-authoring mechanical task; code edits, code generation, test
  creation, and test fixes require Terra / medium or higher.
- Claude and other runtimes must map the same tiers to their own configured
  model choices. Do not pass Codex model ids to non-Codex runtimes.
- If a runtime cannot switch models for the current session, keep the current
  model and apply the effort profile through smaller context, deeper planning,
  or stronger verification.
- Switch only at a task, subagent, or session boundary unless the runtime has a
  safe mid-task handoff mechanism. Preserve the route, docs read, gate ledger,
  and unresolved blockers across the handoff.
- Do not route secret, credential, destructive, deployment, or external-state
  work to a cheaper tier only for cost. Risk controls win over cost controls.

Do not default to the strongest model, longest reasoning, or full-document
loading when the request is clear and low risk. Escalate when evidence shows the
task is broader or riskier than first classified.
