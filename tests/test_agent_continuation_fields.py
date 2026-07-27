from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_continuation_fields import (
    checkpoint_name,
    closed_object,
    count,
    depth,
    filename,
    prose,
    relative_path,
    run_id,
    sha256_value,
    slug,
    timestamp,
)

HASH = "a" * 64


def collect(check, value, *arguments, **keywords) -> list[str]:
    failures: list[dict[str, str]] = []
    check(value, "/field", failures, *arguments, **keywords)
    return [item["rule"] for item in failures]


class ClosedObjectTests(unittest.TestCase):
    def test_extra_and_missing_keys_are_both_named(self) -> None:
        failures: list[dict[str, str]] = []
        closed_object({"kept": 1, "extra": 2}, ("kept", "wanted"), "/object", failures)
        self.assertEqual(
            [
                {"rule": "unknown_field", "pointer": "/object/extra"},
                {"rule": "missing_field", "pointer": "/object/wanted"},
            ],
            failures,
        )


class ScalarTests(unittest.TestCase):
    def test_count_rejects_booleans_and_negatives(self) -> None:
        self.assertEqual([], collect(count, 0))
        self.assertEqual(["invalid_count"], collect(count, True))
        self.assertEqual(["invalid_count"], collect(count, -1))

    def test_sha256_is_lowercase_hex_and_may_be_optional(self) -> None:
        self.assertEqual([], collect(sha256_value, HASH))
        self.assertEqual(["invalid_sha256"], collect(sha256_value, HASH.upper()))
        self.assertEqual(["invalid_sha256"], collect(sha256_value, None))
        self.assertEqual([], collect(sha256_value, None, optional=True))

    def test_timestamp_must_be_rfc3339_utc(self) -> None:
        self.assertEqual([], collect(timestamp, "2026-07-27T09:00:00+00:00"))
        self.assertEqual([], collect(timestamp, "2026-07-27T09:00:00Z"))
        self.assertEqual(["invalid_timestamp"], collect(timestamp, "2026-07-27T09:00:00+09:00"))
        self.assertEqual(["invalid_timestamp"], collect(timestamp, "2026-07-27 09:00"))

    def test_run_id_and_filename_shapes(self) -> None:
        self.assertEqual([], collect(run_id, "0" * 32))
        self.assertEqual(["invalid_run_id"], collect(run_id, "0" * 31))
        self.assertEqual([], collect(filename, "preflight.json"))
        self.assertEqual(["invalid_filename"], collect(filename, "../preflight.json"))
        self.assertEqual(["invalid_filename"], collect(filename, "x" * 81))


class ProseTests(unittest.TestCase):
    def test_empty_prose_is_refused_rather_than_stored(self) -> None:
        self.assertEqual(["prose_empty"], collect(prose, "", 280))

    def test_decomposed_text_is_rejected_before_it_is_stored(self) -> None:
        """NFC is checked, not applied: normalizing here would edit the record."""

        self.assertEqual(["prose_not_normalized"], collect(prose, "e\u0301clair", 280))
        self.assertEqual([], collect(prose, "\u00e9clair", 280))

    def test_non_string_prose_is_a_type_failure(self) -> None:
        self.assertEqual(["invalid_type"], collect(prose, 12, 280))


class IdentifierTests(unittest.TestCase):
    def test_slug_shape_and_cap(self) -> None:
        self.assertEqual([], collect(slug, "single-lock-claim", 40))
        self.assertEqual(["invalid_slug"], collect(slug, "Single Lock", 40))
        self.assertEqual(["invalid_slug"], collect(slug, "a" * 41, 40))
        self.assertEqual([], collect(slug, None, 40, optional=True))

    def test_checkpoint_accepts_an_exact_gate_name_with_spaces(self) -> None:
        self.assertEqual([], collect(checkpoint_name, "source docs"))
        self.assertEqual([], collect(checkpoint_name, "retrospective check"))
        self.assertEqual(["invalid_checkpoint"], collect(checkpoint_name, "Source Docs"))
        self.assertEqual(["invalid_checkpoint"], collect(checkpoint_name, "x" * 65))


class RelativePathTests(unittest.TestCase):
    def test_normalized_repo_relative_paths_are_accepted(self) -> None:
        self.assertEqual([], collect(relative_path, "scripts/agent_continuation_store.py"))

    def test_windows_separators_and_drive_letters_are_rejected(self) -> None:
        self.assertEqual(["invalid_path"], collect(relative_path, "scripts\\store.py"))
        self.assertEqual(["invalid_path"], collect(relative_path, "C:/scripts/store.py"))

    def test_empty_segments_are_rejected(self) -> None:
        self.assertEqual(["invalid_path"], collect(relative_path, "scripts//store.py"))
        self.assertEqual(["invalid_path"], collect(relative_path, "scripts/"))


class DepthTests(unittest.TestCase):
    def test_depth_counts_nested_containers(self) -> None:
        self.assertEqual(1, depth({}))
        self.assertEqual(2, depth({"a": 1}))
        # Root, work, the decisions list, one decision, and its leaf value is
        # the deepest shape the schema allows, and it is exactly the cap.
        self.assertEqual(5, depth({"work": {"decisions": [{"id": "d"}]}}))


if __name__ == "__main__":
    unittest.main()
