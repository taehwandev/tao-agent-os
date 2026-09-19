"""REST inspection must not create lifecycle state or authorize writes."""
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from claude_bash_readonly import gh_command_kind


class GhApiTests(unittest.TestCase):
    def test_rest_read_forms(self):
        for args in (
            'api repos/x/y/commits/abc/status',
            'api --method GET repos/x/y/commits/abc/status --jq .state',
            'api repos/x/y/deployments --method=GET --paginate --slurp',
            'api -X HEAD /repos/x/y --include',
            'api repos/{owner}/{repo}/checks --template "{{.state}}"',
            'api --hostname github.example repos/x/y --preview example',
        ):
            with self.subTest(args=args):
                self.assertEqual('read_only', gh_command_kind(shlex.split(args)))

    def test_writes_unknown_flags_and_payloads_stay_restricted(self):
        for args in (
            'api repos/x/y -X POST', 'api repos/x/y --method=DELETE',
            'api repos/x/y -X PATCH', 'api repos/x/y -XGET',
            'api repos/x/y -f state=success', 'api repos/x/y -F data=@file',
            'api repos/x/y --method GET --raw-field x=y',
            'api repos/x/y --input file', 'api repos/x/y --cache 1h',
            'api repos/x/y -H X-HTTP-Method-Override:DELETE',
            'api repos/x/y --output file', 'api repos/x/y --unknown',
            'api graphql', 'api /graphql --method GET',
            'api graphql?query=mutation', 'api https://example.invalid/graphql',
            'api repos/x/../../graphql', 'api', 'api repos/x/y --method',
            'api --jq repos/x/y', 'api repos/x/y second',
            'api repos/x/y -X GET -X POST', 'api repos/x/y --method=get',
        ):
            with self.subTest(args=args):
                self.assertEqual('mutating', gh_command_kind(shlex.split(args)))
