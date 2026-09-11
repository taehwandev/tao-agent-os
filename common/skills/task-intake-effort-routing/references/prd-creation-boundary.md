---
keyflow_id: sys_task_intake_prd_creation_boundary
status: stable
type: human-reviewed-needed
---

# PRD Creation Boundary

Read when deciding whether requirements analysis or modification work needs a
new or updated PRD, or only the user-visible PRD-skip alignment checkpoint.
The always-applicable intake rules stay in `current-guidance.md`.

PRD creation is a deliverable and risk decision. It is separate from the
alignment brief and from Grill-Me.

- The alignment brief is mandatory before requirements analysis or modification
  work, but it does not imply a PRD.
- When a PRD is not created for requirements analysis or modification work, the
  agent must still give the user a compact PRD-skip alignment checkpoint before
  drafting or editing. This must be user-visible, not only an internal note.
  State shared understanding, possible differences, unsupported assumptions or
  unknowns, and either the minimal blocker question or the safe default the
  agent will use.
- Grill-Me is a clarification skill for blocker questions, but it does not imply
  a PRD by itself.
- For writing or documentation work, unclear genre, point of view, honorific
  level, audience, or voice target is still an alignment blocker when the choice
  would change the outline or rewrite strategy. Ask with concrete options before
  editing; do not infer the mode from a single style example.
- Create a new PRD when the requested deliverable is explicitly a PRD/product
  requirements note, or when work introduces a new product capability, flow,
  multi-screen behavior, data model, API contract, auth/permission/billing
  policy, release behavior, or durable acceptance criteria that do not already
  exist.
- Update an existing PRD or product source of truth when the change alters
  documented user behavior, acceptance criteria, product policy, or required
  states.
- Do not create a PRD for a clear bugfix, refactor, documentation edit, test
  update, hook/script/workflow-policy repair, or internal cleanup unless that
  work changes product behavior or a public contract. Use the user-visible
  PRD-skip alignment checkpoint and acceptance criteria instead.
