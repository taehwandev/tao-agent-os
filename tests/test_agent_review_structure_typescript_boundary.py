"""Guard the TypeScript owner boundary for a legacy oversized UI function."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_review_structure import large_block_findings


class TypeScriptStructureBoundaryTests(unittest.TestCase):
    def test_growth_inside_legacy_component_fails(self) -> None:
        previous_lines = ["export function LegacyPicker() {"]
        previous_lines.extend(f"  const value{index} = {index};" for index in range(120))
        previous_lines.append("}")
        current_lines = previous_lines[:-1] + ["  const imported = true;", "}"]

        failures, warnings = self._findings(current_lines, previous_lines)

        self.assertTrue(any("LegacyPicker" in failure for failure in failures))
        self.assertEqual([], warnings)

    def test_change_outside_legacy_component_only_warns(self) -> None:
        previous_lines = ["export function LegacyPicker() {"]
        previous_lines.extend(f"  const value{index} = {index};" for index in range(120))
        previous_lines.append("}")
        current_lines = previous_lines + ["export const pickerLabel = 'Gist';"]

        failures, warnings = self._findings(current_lines, previous_lines)

        self.assertEqual([], failures)
        self.assertTrue(any("pre-existing oversized unit" in warning for warning in warnings))

    @staticmethod
    def _findings(current_lines: list[str], previous_lines: list[str]):
        return large_block_findings(
            Path("."),
            Path("src/components/LegacyPicker.tsx"),
            current_lines,
            120,
            {"status": "M"},
            lambda _command, _cwd: {
                "returncode": 0,
                "stdout": "\n".join(previous_lines),
                "stderr": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
