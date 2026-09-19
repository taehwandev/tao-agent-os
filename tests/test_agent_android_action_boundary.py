"""Compose action ownership: user regression and executable review boundary."""

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_android_action_boundary import AndroidActionBoundary
from agent_review_hook import _run_review_checks


class AndroidActionBoundaryTests(unittest.TestCase):
    def check(self, body, prefix=""):
        return AndroidActionBoundary.failures(
            Path("feature/feed/FeedScreen.kt"),
            prefix + "\n@Composable\nfun FeedScreen() {\n" + body + "\n}",
        )

    def test_reported_feed_route_bypass_is_rejected(self):
        failures = self.check('''
            FeedLoadContent(onRetry = viewModel::retry,
                onClipSelected = { clipId ->
                    onRouteEvent(FeedRouteEvent.ClipRequested(clipId))
                })
        ''')
        self.assertTrue(any("effect construction" in item for item in failures))
        self.assertTrue(any("effect dispatch" in item for item in failures))

    def test_reported_chat_request_assembly_and_forwarding_are_rejected(self):
        for body in (
            'Button(onClick = { onStartThread(state.creator, "Chat", state.id, null) })',
            'ClipDetailContent(onStartThread = onStartThread)',
        ):
            with self.subTest(body=body):
                self.assertTrue(self.check(body))

    def test_direct_effects_and_data_access_are_rejected(self):
        for body in (
            'Button(onClick = { router.navigate(route) })',
            'Button(onClick = { Toast.makeText(context, "hello", 0).show() })',
            'Button(onClick = { notices.showNotice(alert) })',
            'LaunchedEffect(Unit) { repository.load() }',
            'val content = contentRepository.destinations()',
            'submitUseCase(input)',
            'val response = api.load()',
            'Column(Modifier.clickable { router.navigate(route) })',
            'Content(onClick = router::navigate)',
            'other.effects.collect { router.navigate(route) }',
        ):
            with self.subTest(body=body):
                self.assertTrue(self.check(body))

    def test_actions_and_rendering_are_allowed(self):
        self.assertEqual([], self.check('''
            val state by viewModel.state.collectAsStateWithLifecycle()
            val listState = rememberLazyListState()
            SideEffect { onBackdropColorChanged(backdropColor) }
            Content(onAction = viewModel::onAction,
                onClick = { viewModel.onAction(FeedAction.ClipClicked(id)) },
                onRetry = viewModel::retry)
            Button(onClick = { viewModel.navigate() })
            Toolbar(onBack = onBack, onOpenMenu = onOpenMenu)
            Content(onClick = viewModel::navigate)
        '''))

    def test_effect_collector_is_allowed_but_nested_user_callback_is_not(self):
        self.assertEqual([], self.check('''
            LaunchedEffect(viewModel) {
                viewModel.effects.collect { effect ->
                    when (effect) {
                        is FeedEffect.Navigate -> router.navigate(effect.route)
                        is FeedEffect.Notice -> snackbar.showSnackbar(effect.message)
                    }
                }
            }
        '''))
        self.assertTrue(self.check('''
            viewModel.effects.collect { effect ->
                Button(onClick = { router.navigate(route) })
            }
        '''))

    def test_literal_text_comments_and_non_composable_owners_are_ignored(self):
        self.assertEqual([], self.check('''
            // router.navigate(route)
            /* nested /* repository.load() */ onStartThread(a) */
            Text("Toast.makeText(x) and FeedRouteEvent.Open(id)")
            Text("""repository.load() { }""")
        '''))
        self.assertEqual([], AndroidActionBoundary.failures(Path("FeedViewModel.kt"), '''
            class FeedViewModel { fun onAction() { router.navigate(route) } }
        '''))

    def test_multiline_expression_body_and_import_alias_are_checked(self):
        source = '''
            import example.FeedRouteEvent as Route
            import androidx.compose.runtime.Composable as UI
            @UI fun FeedScreen() = Content(onClick = {
                onRouteEvent(Route.ClipRequested(id))
            })
        '''
        self.assertTrue(AndroidActionBoundary.failures(Path("FeedScreen.kt"), source))
        self.assertTrue(self.check('router\n .navigate(\nroute\n)'))

    def test_leaf_callback_is_not_an_effect_decision(self):
        source = "@Composable fun Content(onNavigate: () -> Unit) { Button(onClick = { onNavigate() }) }"
        self.assertEqual([], AndroidActionBoundary.failures(Path("Content.kt"), source))

    def test_typed_viewmodel_receiver_can_have_a_short_name(self):
        source = """@Composable fun Screen(vm: FeedViewModel) {
            LaunchedEffect(vm) { vm.effects.collect { effect -> router.navigate(effect.route) } }
        }"""
        self.assertEqual([], AndroidActionBoundary.failures(Path("Screen.kt"), source))

    def test_route_singleton_is_an_effect_decision(self):
        self.assertTrue(self.check("Button(onClick = { sink.tryEmit(FeedRouteEvent.Back) })"))

    def test_leaf_parameter_does_not_allow_constructing_requests(self):
        source = """@Composable fun Content(onNavigate: () -> Unit) {
            Button(onClick = { sink.tryEmit(FeedRouteEvent.Back); onNavigate() })
        }"""
        self.assertTrue(AndroidActionBoundary.failures(Path("Content.kt"), source))

    def test_typed_vm_does_not_allow_nested_user_effect_decisions(self):
        source = """@Composable fun Screen(vm: FeedViewModel) {
            vm.effects.collect { Button(onClick = { router.navigate(route) }) }
        }"""
        self.assertTrue(AndroidActionBoundary.failures(Path("Screen.kt"), source))

    def test_leaf_forwarding_and_vm_method_reference_are_allowed(self):
        source = """@Composable fun Screen(vm: FeedViewModel, onNavigate: () -> Unit) {
            Content(onClick = vm::navigate, onNavigate = onNavigate)
        }"""
        self.assertEqual([], AndroidActionBoundary.failures(Path("Screen.kt"), source))

    def test_function_parameter_defaults_do_not_hide_the_body(self):
        source = '''
            @Composable fun FeedScreen(onAction: () -> Unit = {}) {
                onRouteEvent(FeedRouteEvent.ClipRequested(id))
            }
        '''
        self.assertTrue(AndroidActionBoundary.failures(Path("FeedScreen.kt"), source))

    def test_real_structure_cli_fails_bad_code_and_accepts_action_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            subprocess.run(["git", "init", "-q", str(project)], check=True)
            source = project / "FeedScreen.kt"
            source.write_text("@Composable fun FeedScreen() {}\n")
            subprocess.run(["git", "-C", str(project), "add", "."], check=True)
            subprocess.run(["git", "-C", str(project), "-c", "user.name=Test",
                            "-c", "user.email=test@example.invalid", "commit", "-qm", "base"], check=True)
            command = [sys.executable, str(ROOT / "scripts/agent-structure-check.py"),
                       "--project", str(project), "--review-path", "FeedScreen.kt"]
            source.write_text('@Composable fun FeedScreen() { onRouteEvent(FeedRouteEvent.Open(id)) }\n')
            bad = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(0, bad.returncode, bad.stdout)
            self.assertIn("Android action boundary", bad.stdout)
            self.assert_review_rejects_boundary(project)
            source.write_text('@Composable fun FeedScreen() { Content(onAction = viewModel::onAction) }\n')
            good = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(0, good.returncode, good.stdout + good.stderr)
            self.assertEqual("SUCCESS", json.loads(good.stdout)["status"])

    def assert_review_rejects_boundary(self, project):
        """Exercise real review aggregation; isolate unrelated external checks."""
        def run(command, cwd):
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            return dict(returncode=result.returncode, stdout=result.stdout,
                        stderr=result.stderr, command=command, cwd=str(cwd))

        args = SimpleNamespace(
            project=project, rules=ROOT, max_source_file_lines=500,
            max_function_lines=100, structure_review_evidence="",
            side_effect_audit_evidence="", review_outcome="pass",
        )
        failures, checks = [], {}
        with ExitStack() as stack:
            for name in ("record_review_base_drift", "record_review_workflow_validation",
                         "record_review_vibeguard", "record_review_worktree_stability"):
                stack.enter_context(patch("agent_review_hook." + name))
            _run_review_checks(
                args, checks, failures, run, lambda _: ({}, []),
                lambda *_: [], lambda _: "Ready",
                review_paths=["FeedScreen.kt"], review_subject={"kind": "working-tree"},
                review_scope="pathspec", status_before={}, status_before_lines=[],
                full_status_before_lines=[], local_config_scope=False,
            )
        self.assertTrue(any("structure review:" in item and "Android action boundary" in item
                            for item in failures), failures)


if __name__ == "__main__":
    unittest.main()
