"""Performance mentions must not override the requested change's scope."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_doc_surfaces import infer_surface_docs
from workflow_request import infer_concerns_from_request
from workflow_route import resolve_docs


class PerformanceDocSelectionTests(unittest.TestCase):
    PLATFORMS = ("android", "ios", "web")
    PERFORMANCE = "common/skills/performance-verification/references/current-guidance.md"

    def route(self, platform, request, explicit=False):
        inferred = infer_concerns_from_request(request)
        return resolve_docs(
            "feature", platform, inferred, request_classified=True,
            inferred_concerns=[] if explicit else inferred, request_text=request,
        )

    def test_excluded_performance_does_not_add_required_reading(self):
        for platform in self.PLATFORMS:
            for excluded, plain in (
                ("Do not change scroll performance; adjust button spacing.",
                 "adjust button spacing."),
                ("성능은 수정하지 말고 버튼 위치만 수정해줘",
                 "버튼 위치만 수정해줘"),
                ("Adjust button spacing without touching scroll performance",
                 "Adjust button spacing"),
            ):
                with self.subTest(platform=platform, request=excluded):
                    route = self.route(platform, excluded)
                    self.assertEqual(self.route(platform, plain)["required_docs"],
                                     route["required_docs"])
                    self.assertNotIn(self.PERFORMANCE, route["required_docs"])
                    _, matches = infer_surface_docs(
                        command="feature", platform=platform, request_text=excluded,
                    )
                    self.assertNotIn(f"{platform}_ui_performance",
                                     [match["name"] for match in matches])

    def test_affirmative_performance_work_survives_other_exclusions(self):
        for platform in self.PLATFORMS:
            for request in (
                "Improve scroll performance without changing the button layout",
                "버튼 위치는 수정하지 말고 스크롤 성능을 개선해줘",
                "Do not change startup performance; improve scroll performance",
                "Improve scroll performance and adjust button spacing",
            ):
                with self.subTest(platform=platform, request=request):
                    self.assertIn(self.PERFORMANCE,
                                  self.route(platform, request)["required_docs"])

    def test_explicit_concern_remains_required(self):
        for platform in self.PLATFORMS:
            with self.subTest(platform=platform):
                route = self.route(
                    platform, "Do not change performance; adjust button spacing",
                    explicit=True,
                )
                self.assertIn(self.PERFORMANCE, route["required_docs"])


if __name__ == "__main__":
    unittest.main()
