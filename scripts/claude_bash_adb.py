"""Read-only classification of the `adb` command line.

`adb` acts on a connected device, not on the checkout, so most of what it does
never touches a project file. The gate still classified every `adb` call as
unknown, and a device check piped to `rg` in a protected checkout stopped a
Codex session for an operator question after it had already installed and was
only verifying the build.

Only inspection is admitted here: listing devices, reading their state or a
dumped log, and a device shell running one known reader. `install`, `push`,
`pull` (which writes into the local directory), `reboot`, `root`, a shell
running anything else, and a device command with shell syntax of its own keep
the conservative verdict.
"""

from __future__ import annotations

import shlex

# Global options that take a value and only choose a device or server.
_DEVICE_OPTIONS = frozenset({"-s", "-t", "-H", "-P"})
_DEVICE_SWITCHES = frozenset({"-d", "-e", "-a"})
_READ_ONLY_SUBCOMMANDS = frozenset({"devices", "get-state", "get-serialno", "get-devpath", "version"})
_DEVICE_READERS = frozenset(
    {"dumpsys", "getprop", "sha256sum", "md5sum", "ls", "cat", "ps", "pidof", "df", "id", "whoami"}
)
_DEVICE_READER_SUBCOMMANDS = frozenset(
    {("pm", "path"), ("pm", "list"), ("settings", "get"), ("wm", "size"), ("wm", "density")}
)
# A device shell interprets these itself, so a reader followed by one could run anything.
_DEVICE_SHELL_SYNTAX = frozenset(";&|<>`$()\n")


def adb_command_kind(arguments: list[str]) -> str:
    """Read-only when the call only inspects the device; otherwise mutating."""

    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        if arguments[index] in _DEVICE_OPTIONS:
            index += 2
        elif arguments[index] in _DEVICE_SWITCHES:
            index += 1
        else:
            return "mutating"
    rest = arguments[index:]
    if not rest:
        return "mutating"
    if rest[0] in _READ_ONLY_SUBCOMMANDS:
        return "read_only"
    if rest[0] == "logcat":
        return "read_only" if "-d" in rest[1:] and not _writes_a_log_file(rest[1:]) else "mutating"
    if rest[0] == "shell":
        return "read_only" if _device_command_reads(rest[1:]) else "mutating"
    return "mutating"


def _writes_a_log_file(arguments: list[str]) -> bool:
    return any(argument in {"-f", "--file"} or argument.startswith("--file=") for argument in arguments)


def _device_command_reads(arguments: list[str]) -> bool:
    text = " ".join(arguments)
    if not text or any(character in _DEVICE_SHELL_SYNTAX for character in text):
        return False
    try:
        words = shlex.split(text)
    except ValueError:
        return False
    if not words:
        return False
    if words[0] == "cmd":
        # `cmd package list|path` only reports; other `cmd package` verbs install or clear.
        return words[1:3] in (["package", "list"], ["package", "path"])
    return words[0] in _DEVICE_READERS or tuple(words[:2]) in _DEVICE_READER_SUBCOMMANDS
