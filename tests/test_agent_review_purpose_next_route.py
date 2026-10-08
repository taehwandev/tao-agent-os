from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from agent_review_purpose import top_level_declaration_failures, top_level_type_declarations


class NextRouteOwnerTests(unittest.TestCase):
    def failures(self, source: str, path: str = 'src/app/api/publication/route.ts'):
        target = Path(path)
        return top_level_declaration_failures(target, top_level_type_declarations(target, source.splitlines()))

    def test_multiple_http_methods_and_configuration_form_one_adapter(self):
        source = "export const runtime = 'nodejs';\nexport const dynamic = 'force-dynamic';\nexport const GET = (request: Request) => owner.read(request);\nexport const POST = (request: Request) => owner.save(request);\nexport const DELETE = (request: Request) => owner.remove(request);"
        for path in ('src/app/api/publication/route.ts', 'app/api/publication/route.ts'):
            with self.subTest(path=path):
                self.assertEqual([], self.failures(source, path))

    def test_task_entrypoint_configuration_and_method_form_one_adapter(self):
        source = "export const runtime = 'nodejs';\nexport const dynamic = 'force-dynamic';\nexport const maxDuration = 300;\nexport function POST(request: Request) { return owner.execute(request); }"
        self.assertEqual([], self.failures(source))

    def test_an_extra_public_helper_still_fails(self):
        source = "export const runtime = 'nodejs';\nexport function POST() { return owner.execute(); }\nexport function other() { return 1; }"
        self.assertTrue(self.failures(source))

    def test_reserved_names_in_normal_modules_still_fail(self):
        source = "export const runtime = 'nodejs';\nexport function POST() { return owner.execute(); }"
        for path in ('src/features/publication/route.ts', 'src/app/api/publication/helpers.ts'):
            with self.subTest(path=path):
                self.assertTrue(self.failures(source, path))

    def test_reserved_class_is_not_a_framework_export(self):
        self.assertTrue(self.failures("export const runtime = 'nodejs';\nexport function POST() { return 1; }\nexport class GET {}"))

    def test_configuration_without_http_method_is_not_an_adapter(self):
        self.assertTrue(self.failures("export const runtime = 'nodejs';\nexport const dynamic = 'force-dynamic';"))
