---
keyflow_id: sys_common_ui_visual_verification_md_skill
status: stable
type: ai-generated
required_contract: core
---

# UI Visual Verification

Use when changing UI layout, interaction, visible text, controls, navigation, responsive behavior, accessibility labels, or state presentation.

## Read

The core below is the required contract. Open `references/current-guidance.md` only for an unresolved in-scope question:

- `## Check` for the full state, text, numeric, viewport and input checklist.
- `## Tools By Platform` for evidence tooling per platform and companion cards.
- `## Comparison Oracle And Evidence Budget` for before/after, regression or motion claims.
- `## Figma parity gate` for the parity measurement list when a design frame is the requirement.

## Must

- Treat build, typecheck and unit tests as proof of compilation only. Verify the user path, not only the component, when the change affects navigation, commands, permissions, persistence or cross-surface state.
- Check the success path plus empty, loading, disabled, error, unavailable, offline and permission-denied states; long/localized text, missing images/icons, slow data; numeric, unit and value+unit text; relevant viewports; light/dark, font size, reduced motion, high contrast when supported.
- Check keyboard focus, screen-reader labels, hit targets, visible focus; overlap or unexpected resize; same result from every entry point; state updating after actions, retries, refreshes, navigation.
- Hover-only reveal (`:hover`/`group-hover`/`focus-within`) is never the sole way to open an actionable menu or control: require a tap/click toggle with outside-tap/escape close, verified at a touch/mobile viewport.
- Use repo-local tooling first and the strongest practical evidence: interaction tests, semantic assertions, screenshot/geometry checks, manual smoke only when automation cannot observe it. Load `common/skills/accessibility-i18n/SKILL.md` for text, forms, numbers, units, localization, focus or screen readers.
- State what each check can and cannot prove: geometry is not contrast, a screenshot is not command execution, a visible button is not the trusted boundary reached.
- Define the comparison oracle before operating the UI: requirement or state invariant, approved design frame, known-good build, or pre-change behavior. Current state alone cannot prove an improvement or a fixed regression.
- Before/after: same bounded scenario, device, display, flavor, theme, data state and entry point; capture the baseline before replacing its build. Collect one baseline and one candidate observation; repeat only after a failure, instability or conflict, and say why. No recapturing for confidence.
- Motion claims need matched temporal evidence; a single frame, pixel delta or hierarchy cannot prove them.
- Figma parity is blocking: capture the full, uncropped surface from the running app on the requested device and flavor; compare side by side or by overlay; check each variant independently. Source-computed geometry does not satisfy it. Text containers grow from content and padding; never force a sample height with `height()`/`size()` to hide clipping.

## Stop If

- The Figma reference is cropped, the implementation route is uncertain, or a caller/variant cannot be identified: mark visual verification incomplete and stop the completion report.
- The only screenshot is cropped and hides the entry point, overflow, modal/sheet boundary or next section.
- Assets, icons, fonts or remote data failed to load in the checked environment; do not claim visual verification.
- The baseline cannot be reproduced: verify only the current-state invariant and report the comparative claim unverified.

## Verification

- Report scenario, environment, action, expected result, observed result, and remaining risk when verification is manual or partial.
- Name the oracle used and which claims stay unverified.
