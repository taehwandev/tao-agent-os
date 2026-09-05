"""Static homepage integration and protected setup-content contracts."""

import hashlib
import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SiteMarkup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.assets, self.keys = [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'script' and 'src' in attrs:
            self.assets.append(attrs['src'])
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.assets.append(attrs['href'])
        if 'data-i18n' in attrs:
            self.keys.append(attrs['data-i18n'])
        if 'data-i18n-attr' in attrs:
            self.keys.extend(mapping.strip().split(':', 1)[1] for mapping in attrs['data-i18n-attr'].split(','))


class SiteWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / 'docs/index.html').read_text()
        cls.markup = SiteMarkup(cls.html)

    def test_workflow_is_connected_before_installation_and_has_no_script_fallback(self):
        self.assertEqual(1, self.markup.ids.count('workflow-map'))
        self.assertEqual(len(self.markup.ids), len(set(self.markup.ids)))
        self.assertLess(self.html.index('id="routing"'), self.html.index('id="apply"'))
        self.assertIn('./workflow/map.js', self.markup.assets)
        self.assertIn('./styles/workflow.css', self.markup.assets)
        self.assertIn('<noscript>', self.html)
        self.assertIn('tao:language', self.html)
        for asset in self.markup.assets:
            if asset.startswith('./'):
                self.assertTrue((ROOT / 'docs' / asset).is_file(), asset)

    def test_both_dictionaries_cover_every_static_label(self):
        for key in set(self.markup.keys):
            self.assertEqual(2, len(re.findall(r'"' + re.escape(key) + r'"\s*:', self.html)), key)

    def test_original_setup_prompts_remain_byte_identical(self):
        # Reviewed before copy editing; these carry runtime, permissions and
        # metering responsibilities and are not marketing prose.
        expected = [
            'dc805b26e52ea82899b42d7d712c1142b70201b3eec41d969ccf42ddefaa55a9',
            'fb107cc429549a469b5495db59f32d1f1097a200878ccf9bbc95691a25c658da',
            '54b81edb083882da3baacbbc48996d5b4b70e9327b33fef5a3f9baa88f93853d',
            'c3e58d607da7ef8faee2b91f17c539c7ed78461c430003302296ac1c7004b0cf',
        ]
        values = re.findall(r'"quick\.prompt\.step[12]":\s*("(?:\\.|[^"\\])*")', self.html)
        self.assertEqual(expected, [hashlib.sha256(json.loads(value).encode()).hexdigest() for value in values])

    def test_copy_does_not_promise_perfect_results(self):
        for phrase in ('한 치의 오차도 없이', '실수 없이', '고품격', '최적의 길'):
            self.assertNotIn(phrase, self.html)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for homepage interaction checks')
    def test_route_and_language_interactions(self):
        result = subprocess.run(['node', '--test', 'tests/site-workflow.test.cjs'], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
