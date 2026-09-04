from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_search import search_docs_outcome
from workflow_wikimap import (
    WIKIMAP_COMMIT,
    WIKIMAP_SCRIPT,
    WIKIMAP_SHA256,
    WIKIMAP_VERSION,
    _ensure_index,
    clear_wikimap_cache,
    search_wikimap,
)


class WorkflowWikimapTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_wikimap_cache()

    def test_vendor_source_is_pinned_with_license(self) -> None:
        digest = hashlib.sha256(WIKIMAP_SCRIPT.read_bytes()).hexdigest()
        license_text = (WIKIMAP_SCRIPT.parent / "LICENSE").read_text(encoding="utf-8")

        self.assertEqual("1.0.0", WIKIMAP_VERSION)
        self.assertEqual("9c26d7b66322741532ede0b474f0e5106643f275", WIKIMAP_COMMIT)
        self.assertEqual(WIKIMAP_SHA256, digest)
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 Donghyun Ha", license_text)

    def test_adapter_invokes_only_update_and_search_commands(self) -> None:
        payload = {
            "results": [
                {
                    "path": "guide.md",
                    "line": 3,
                    "heading": "Guide",
                    "score": 1.0,
                    "matched": ["retrieval rule"],
                    "sources": "1/1",
                }
            ]
        }
        completed_update = subprocess.CompletedProcess([], 0, stdout="updated", stderr="")
        completed_search = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "guide.md").write_text("# Guide\n\nretrieval rule\n", encoding="utf-8")
            with patch(
                "workflow_wikimap._run",
                side_effect=[(completed_update, ""), (completed_search, "")],
            ) as run:
                outcome = search_wikimap(root, ["retrieval rule"], max_results=4)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(outcome.available)
        self.assertEqual(["update", "search"], [command[4] for command in commands])
        flattened = " ".join(part for command in commands for part in command)
        for forbidden in ("install", "migrate", "--hook", "import-graphify", "note"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, flattened)

    def test_checksum_failure_uses_legacy_recovery_scorer(self) -> None:
        with patch(
            "workflow_search.search_wikimap",
            return_value=type(
                "Unavailable",
                (),
                {
                    "available": False,
                    "error": "pinned wikimap source checksum does not match",
                },
            )(),
        ):
            outcome = search_docs_outcome(ROOT, "documentation update", max_results=4)

        self.assertEqual("legacy", outcome.backend)
        self.assertIn("checksum", outcome.fallback_reason)
        self.assertTrue(outcome.results)
        self.assertTrue(all(item["search_backend"] == "legacy" for item in outcome.results))


class IndexRefreshIsSkippedOnlyWhenNothingChangedTests(unittest.TestCase):
    """Every hook is its own process, so the in-process cache saved the next
    one nothing: each `start` spent about 90 ms deciding that an incremental
    index had nothing to do.

    Skipping that is only safe while a skipped refresh is indistinguishable
    from a run one, so each test here is a way the corpus can change.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / ".tao").mkdir()
        (self.root / ".wikimap").mkdir()
        (self.root / ".wikimap" / "index.db").write_bytes(b"index")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "one.md").write_text("# one\n", encoding="utf-8")
        clear_wikimap_cache()

    def tearDown(self) -> None:
        clear_wikimap_cache()

    def _refresh(self) -> bool:
        """Run the refresh and report whether it reached the subprocess."""

        clear_wikimap_cache()
        with patch("workflow_wikimap._run", return_value=(None, "")) as ran:
            error = _ensure_index(str(self.root))
        self.assertEqual("", error)
        return bool(ran.call_count)

    def test_the_first_refresh_runs(self) -> None:
        self.assertTrue(self._refresh())

    def test_a_second_hook_skips_it(self) -> None:
        self._refresh()

        self.assertFalse(self._refresh())

    def test_a_changed_document_refreshes(self) -> None:
        self._refresh()
        (self.root / "docs" / "one.md").write_text("# one, edited\n", encoding="utf-8")

        self.assertTrue(self._refresh())

    def test_a_new_document_refreshes(self) -> None:
        self._refresh()
        (self.root / "docs" / "two.md").write_text("# two\n", encoding="utf-8")

        self.assertTrue(self._refresh())

    def test_a_removed_document_refreshes(self) -> None:
        (self.root / "docs" / "two.md").write_text("# two\n", encoding="utf-8")
        self._refresh()
        (self.root / "docs" / "two.md").unlink()

        self.assertTrue(self._refresh())

    def test_deleting_the_index_refreshes(self) -> None:
        """Removing it is how a person asks for a rebuild."""

        self._refresh()
        (self.root / ".wikimap" / "index.db").unlink()

        self.assertTrue(self._refresh())

    def test_the_receipt_does_not_invalidate_itself(self) -> None:
        """The refresh writes the index, so the signature must not describe it.

        Digesting the index file's own size and time made every receipt stale
        the moment it was written, and the skip never once happened.
        """

        self._refresh()
        (self.root / ".wikimap" / "index.db").write_bytes(b"index, rewritten by the update")

        self.assertFalse(self._refresh())

    def test_a_project_with_no_run_state_always_refreshes(self) -> None:
        """No `.tao` means nowhere to write a receipt, so nothing is skipped."""

        with tempfile.TemporaryDirectory() as bare:
            root = Path(bare)
            (root / ".wikimap").mkdir()
            (root / ".wikimap" / "index.db").write_bytes(b"index")
            for _ in range(2):
                clear_wikimap_cache()
                with patch("workflow_wikimap._run", return_value=(None, "")) as ran:
                    _ensure_index(str(root))
                self.assertTrue(ran.call_count)

    def test_a_failed_refresh_records_nothing(self) -> None:
        """A receipt for a refresh that failed would skip the retry."""

        clear_wikimap_cache()
        with patch("workflow_wikimap._run", return_value=(None, "wikimap exited with status 1")):
            self.assertNotEqual("", _ensure_index(str(self.root)))

        self.assertTrue(self._refresh())


if __name__ == "__main__":
    unittest.main()
