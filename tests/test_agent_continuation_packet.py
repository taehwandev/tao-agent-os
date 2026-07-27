from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_continuation_packet import (
    CONTINUATION_SCHEMA_VERSION,
    canonical_packet_bytes,
    validate_continuation_packet,
)

HASH = "a" * 64
STATE = {"head": "abc123", "worktree_fingerprint": HASH, "worktree_signature": HASH}


def packet(**overrides) -> dict:
    base = {
        "schema_version": CONTINUATION_SCHEMA_VERSION,
        "storage_class": "project_local_never_sync",
        "run_id": "0" * 32,
        "generation": 0,
        "phase": "scoped",
        "binding": {
            "kind": "preflight_snapshot",
            "filename": "preflight.json",
            "file_sha256": HASH,
            "binding_sha256": HASH,
        },
        "drift": {"project": STATE, "rules": STATE, "required_docs_sha256": HASH},
        "work": work(),
        "checkpoint": {
            "last_completed": None,
            "first_unfinished": "source docs",
            "mutation_pending": None,
        },
        "updated_at": "2026-07-27T09:00:00+00:00",
    }
    base.update(overrides)
    return base


def work(**overrides) -> dict:
    base = {
        "objective": "implement the shared continuation protocol",
        "non_goals": ["runtime adapters"],
        "decisions": [{"id": "single-lock-claim", "status": "accepted", "text": "one transaction"}],
        "changed_scope": [{"path": "scripts/agent_continuation_store.py", "role": "created"}],
        "inspected_scope": [{"path": "scripts/agent_run_registry.py", "role": "inspected"}],
        "verification": [
            {
                "id": "unittest",
                "kind": "unit",
                "result": "success",
                "evidence_sha256": None,
                "completed_at": None,
            }
        ],
        "remaining_work": [{"checkpoint": "review", "action": "record the review gate"}],
        "blockers": [],
    }
    base.update(overrides)
    return base


def rules(failures: list[dict[str, str]]) -> set[str]:
    return {item["rule"] for item in failures}


class ValidPacketTests(unittest.TestCase):
    def test_a_complete_packet_validates(self) -> None:
        self.assertEqual([], validate_continuation_packet(packet()))

    def test_serialization_is_canonical_and_stable(self) -> None:
        first = canonical_packet_bytes(packet())
        reordered = dict(reversed(list(packet().items())))
        self.assertEqual(first, canonical_packet_bytes(reordered))


class ClosedSchemaTests(unittest.TestCase):
    """Unknown fields are the mechanism by which a bounded record becomes a dump."""

    def test_unknown_root_field_is_rejected(self) -> None:
        failures = validate_continuation_packet(packet(notes="a transcript"))
        self.assertIn("unknown_field", rules(failures))
        self.assertIn("/notes", [item["pointer"] for item in failures])

    def test_unknown_nested_field_is_rejected(self) -> None:
        decisions = [{"id": "d", "status": "accepted", "text": "t", "command": "git push"}]
        failures = validate_continuation_packet(packet(work=work(decisions=decisions)))
        self.assertIn("unknown_field", rules(failures))

    def test_a_newer_schema_version_is_a_hard_stop(self) -> None:
        failures = validate_continuation_packet(packet(schema_version=2))
        self.assertEqual([{"rule": "schema_version_unsupported", "pointer": "/schema_version"}], failures)

    def test_missing_field_is_named_by_pointer(self) -> None:
        payload = packet()
        del payload["drift"]
        failures = validate_continuation_packet(payload)
        self.assertIn("missing_field", rules(failures))


class ProseBoundaryTests(unittest.TestCase):
    def test_an_over_length_free_text_field_is_rejected_not_truncated(self) -> None:
        for pointer, payload in (
            ("/work/objective", packet(work=work(objective="x" * 281))),
            ("/work/blockers/0", packet(work=work(blockers=["x" * 281]))),
            ("/work/non_goals/0", packet(work=work(non_goals=["x" * 161]))),
            (
                "/work/decisions/0/text",
                packet(work=work(decisions=[{"id": "d", "status": "accepted", "text": "x" * 281}])),
            ),
            (
                "/work/remaining_work/0/action",
                packet(work=work(remaining_work=[{"checkpoint": "review", "action": "x" * 281}])),
            ),
        ):
            with self.subTest(pointer=pointer):
                failures = validate_continuation_packet(payload)
                self.assertIn(
                    {"rule": "prose_too_long", "pointer": pointer},
                    failures,
                )

    def test_negative_control_the_exact_cap_is_accepted(self) -> None:
        """The control: the cap must reject over-length text, not all text.

        A rule that refused the boundary value too would make the cap look
        enforced while actually being off by one in the safe direction.
        """

        self.assertEqual([], validate_continuation_packet(packet(work=work(objective="x" * 280))))

    def test_prose_is_never_silently_truncated(self) -> None:
        payload = packet(work=work(objective="x" * 281))
        validate_continuation_packet(payload)
        self.assertEqual(281, len(payload["work"]["objective"]))

    def test_line_breaks_and_controls_are_rejected(self) -> None:
        for value in ("first\nsecond", "tabbed\tvalue", "null\x00byte", "bidi‮override"):
            with self.subTest(value=repr(value)):
                failures = validate_continuation_packet(packet(work=work(objective=value)))
                self.assertIn("prose_not_single_line", rules(failures))

    def test_secret_shaped_values_are_rejected(self) -> None:
        fixtures = (
            "key " + "".join(("s", "k-test-", "a" * 24)),
            "token " + "".join(("g", "hp_", "a" * 36)),
            "".join(("-----BEGIN ", "PRIVATE", " KEY-----")),
            "use " + "https://" + "user" + ":" + "password" + "@example.test",
            "jwt " + ".".join(("e" + "yJ" + "e" * 20, "e" * 20, "e" * 20)),
        )
        for value in fixtures:
            with self.subTest(value=value):
                failures = validate_continuation_packet(packet(work=work(objective=value)))
                self.assertIn("prose_secret_shaped", rules(failures))

    def test_aggregate_prose_payload_is_capped(self) -> None:
        decisions = [
            {"id": f"decision-{index}", "status": "accepted", "text": "x" * 280}
            for index in range(12)
        ]
        remaining = [{"checkpoint": "review", "action": "x" * 280} for _ in range(12)]
        failures = validate_continuation_packet(
            packet(work=work(decisions=decisions, remaining_work=remaining))
        )
        self.assertIn("prose_budget_exceeded", rules(failures))


class BoundedCollectionTests(unittest.TestCase):
    def test_a_thirteenth_decision_is_rejected(self) -> None:
        decisions = [
            {"id": f"decision-{index}", "status": "accepted", "text": "kept short"}
            for index in range(13)
        ]
        failures = validate_continuation_packet(packet(work=work(decisions=decisions)))
        self.assertIn("too_many_items", rules(failures))

    def test_twelve_decisions_are_accepted(self) -> None:
        decisions = [
            {"id": f"decision-{index}", "status": "accepted", "text": "kept short"}
            for index in range(12)
        ]
        self.assertEqual([], validate_continuation_packet(packet(work=work(decisions=decisions))))

    def test_an_oversized_packet_is_rejected(self) -> None:
        scope = [{"path": f"src/{'d' * 200}/{index}.py", "role": "modified"} for index in range(64)]
        inspected = [{"path": f"lib/{'e' * 200}/{index}.py", "role": "inspected"} for index in range(64)]
        failures = validate_continuation_packet(packet(work=work(changed_scope=scope, inspected_scope=inspected)))
        self.assertIn("packet_too_large", rules(failures))


class PathAndIdentifierTests(unittest.TestCase):
    def test_absolute_traversal_and_state_paths_are_rejected(self) -> None:
        for value in ("/etc/passwd", "../outside.py", "./here.py", ".git/config", ".tao/preflight.json"):
            with self.subTest(value=value):
                failures = validate_continuation_packet(
                    packet(work=work(changed_scope=[{"path": value, "role": "modified"}]))
                )
                self.assertIn("invalid_path", rules(failures))

    def test_a_rename_record_uses_from_and_to(self) -> None:
        renamed = [{"from": "old/name.py", "to": "new/name.py", "role": "renamed"}]
        self.assertEqual([], validate_continuation_packet(packet(work=work(changed_scope=renamed))))

    def test_run_id_must_be_the_opaque_registry_id(self) -> None:
        failures = validate_continuation_packet(packet(run_id="not-a-run-id"))
        self.assertIn("invalid_run_id", rules(failures))

    def test_verification_records_carry_no_command_or_output(self) -> None:
        record = {
            "id": "unittest",
            "kind": "unit",
            "result": "success",
            "evidence_sha256": HASH,
            "completed_at": "2026-07-27T09:00:00+00:00",
            "command": "python3 -m unittest",
        }
        failures = validate_continuation_packet(packet(work=work(verification=[record])))
        self.assertIn("unknown_field", rules(failures))

    def test_pending_mutation_is_a_closed_record(self) -> None:
        pending = {
            "kind": "update",
            "paths": ["scripts/agent_continuation_store.py"],
            "project": STATE,
            "rules": STATE,
            "started_at": "2026-07-27T09:00:00+00:00",
        }
        checkpoint = {"last_completed": None, "first_unfinished": "act", "mutation_pending": pending}
        self.assertEqual([], validate_continuation_packet(packet(checkpoint=checkpoint)))
        pending["tool_arguments"] = "rm -rf"
        self.assertIn("unknown_field", rules(validate_continuation_packet(packet(checkpoint=checkpoint))))


if __name__ == "__main__":
    unittest.main()
