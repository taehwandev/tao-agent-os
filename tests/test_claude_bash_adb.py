"""adb device inspection is read-only for the checkout; device writes are not."""

from __future__ import annotations

import shlex
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_worktree_gate as worktree_gate
from claude_bash_adb import adb_command_kind


def _kind(command: str) -> str:
    payload = {"tool_input": {"command": command}}
    cwd, tokens, simple = worktree_gate.bash_invocation(payload, Path("/tmp"))
    return worktree_gate.bash_command_kind(tokens, simple, cwd)


class AdbCommandKindTests(unittest.TestCase):
    def test_device_inspection_is_read_only(self) -> None:
        for command in (
            "devices -l",
            "-s R3CT706TSGJ get-state",
            "-s R3CT706TSGJ logcat -d -v threadtime",
            "-s R3CT706TSGJ shell dumpsys package com.example.dev",
            "-s R3CT706TSGJ shell pm path com.example.dev",
            "-s R3CT706TSGJ shell sha256sum /data/app/base.apk",
            "-s R3CT706TSGJ shell 'getprop ro.product.model'",
            "shell cmd package list packages",
        ):
            with self.subTest(command=command):
                self.assertEqual("read_only", adb_command_kind(shlex.split(command)))

    def test_device_and_local_writes_stay_mutating(self) -> None:
        for command in (
            "-s R3CT706TSGJ install -r app.apk",
            "push local.txt /sdcard/",
            "pull /sdcard/file.txt",
            "reboot",
            "shell rm -rf /sdcard/Download",
            "shell pm clear com.example.dev",
            "shell cmd package install-existing com.example.dev",
            "shell 'cat /proc/version; rm /sdcard/x'",
            "logcat",
            "logcat -d -f /sdcard/log.txt",
            "shell",
            "-x devices",
        ):
            with self.subTest(command=command):
                self.assertEqual("mutating", adb_command_kind(shlex.split(command)))

    def test_the_blocked_codex_verification_pipe_is_read_only(self) -> None:
        command = ("adb -s R3CT706TSGJ shell dumpsys package com.heyratel.cre8orclub.dev "
                   "| rg 'versionCode=|versionName=|lastUpdateTime='")
        self.assertEqual("read_only", _kind(command))

    def test_an_install_chained_after_inspection_keeps_the_strict_verdict(self) -> None:
        self.assertEqual("mutating", _kind("adb devices && adb install -r app.apk"))


if __name__ == "__main__":
    unittest.main()
