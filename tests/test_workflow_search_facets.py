"""Regression tests for natural-language workflow search facets."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workflow_search_facets import query_terms


COMBINED_FACET = "web_service_rn_python"
REACT_NATIVE_DOC = "platforms/react-native/skills/react-native-app/SKILL.md"
PYTHON_SERVICE_DOC = "platforms/python/skills/python-web-service/SKILL.md"
SERVER_API_DOC = "platforms/server/skills/server-api-implementation/SKILL.md"


class WorkflowSearchFacetTests(unittest.TestCase):
    def test_single_runtime_requests_do_not_match_combined_stack(self) -> None:
        cases = (
            ("Fix a FastAPI endpoint", (REACT_NATIVE_DOC,)),
            ("Add a React Native screen", (PYTHON_SERVICE_DOC, SERVER_API_DOC)),
            ("Create a Python export API schema", (REACT_NATIVE_DOC,)),
        )

        for request, unrelated_docs in cases:
            with self.subTest(request=request):
                _, _, facets, boosts = query_terms(request)
                self.assertNotIn(COMBINED_FACET, facets)
                for doc in unrelated_docs:
                    self.assertNotIn(doc, boosts)

    def test_combined_runtime_stack_intent_matches_combined_facet(self) -> None:
        for request in (
            "Add a React Native client for the Python web service",
            "Create an RN React Python skill pack",
        ):
            with self.subTest(request=request):
                _, _, facets, boosts = query_terms(request)
                self.assertIn(COMBINED_FACET, facets)
                self.assertIn(REACT_NATIVE_DOC, boosts)
                self.assertIn(PYTHON_SERVICE_DOC, boosts)


if __name__ == "__main__":
    unittest.main()
