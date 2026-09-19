"""Module placement must not silently become an external-source audit."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workflow_doc_resolution import resolve_guidance_docs
from workflow_platform_concerns import ANDROID_EXTERNAL_SKILL_DOCS
from workflow_route import resolve_docs


class AndroidModuleReadingTests(unittest.TestCase):
    def route(self, concerns):
        return resolve_docs(
            "refactor", "android", concerns, request_classified=True,
            request_text="앱의 DI 조립과 서비스 구현의 모듈 경계를 분리해줘",
        )

    def test_module_and_di_keep_contracts_without_external_source_bundle(self):
        route = self.route(["architecture", "module", "dependency"])
        required = set(route["required_docs"])
        for doc in resolve_guidance_docs(ROOT, [
            "platforms/android/skills/android-module-structure/SKILL.md",
            "platforms/android/skills/android-module-structure/references/module-boundaries.md",
            "platforms/android/skills/android-module-structure/references/di-build-logic.md",
        ]):
            self.assertIn(doc, required)
        for doc in resolve_guidance_docs(ROOT, list(ANDROID_EXTERNAL_SKILL_DOCS)):
            self.assertNotIn(doc, required)

    def test_explicit_source_audit_still_requires_coverage(self):
        required = self.route(["module", "skills"])["required_docs"]
        for doc in resolve_guidance_docs(ROOT, list(ANDROID_EXTERNAL_SKILL_DOCS)):
            self.assertIn(doc, required)


if __name__ == "__main__":
    unittest.main()
