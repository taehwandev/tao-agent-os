"""Opt in to Codex approval review without rewriting user configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path


_SETTING = "approvals_reviewer"
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")
_PUNCTUATION = "[]{}=.,"


def merge_codex_approvals_reviewer(
    target: Path, dry_run: bool, *, enable_auto_review: bool = False
) -> str:
    """Change only an explicitly opted-in, safely identified root setting.

    This is a conservative lexical merge, not a TOML serializer. Unsupported
    keys, malformed statements, unknown reviewer values, and symlink paths are
    conflicts; ordinary setup neither reads nor changes the user's choice.
    """
    if not enable_auto_review:
        return "ok_preserved"
    if _unsafe_path(target):
        return "conflict"
    try:
        original = target.read_bytes() if target.exists() else b""
        text = original.decode("utf-8")
    except (OSError, UnicodeError):
        return "missing"
    try:
        assignment, first_table = _reviewer_assignment(text)
    except ValueError:
        return "conflict"
    if assignment is None:
        newline = "\r\n" if "\r\n" in text else "\n"
        prefix = text[:first_table]
        separator = "" if not prefix or prefix.endswith("\n") else newline
        updated = (
            prefix + separator + f'{_SETTING} = "auto_review"{newline}'
            + text[first_table:]
        )
    else:
        start, end = assignment
        value = text[start:end]
        if value in {'"auto_review"', "'auto_review'"}:
            return "ok"
        if value not in {'"user"', "'user'"}:
            return "conflict"
        updated = text[:start] + value[0] + "auto_review" + value[-1] + text[end:]
    if dry_run:
        return "would_update"
    # Recheck before writing so a concurrent user edit is never overwritten.
    if _unsafe_path(target):
        return "conflict"
    current = target.read_bytes() if target.exists() else b""
    if current != original:
        return "conflict"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(updated.encode("utf-8"))
    return "installed"


def _unsafe_path(target: Path) -> bool:
    return (
        target.is_symlink() or target.parent.is_symlink()
        or (target.exists() and not target.is_file())
        or (target.parent.exists() and not target.parent.is_dir())
    )


def _reviewer_assignment(text: str) -> tuple[tuple[int, int] | None, int]:
    assignment = None
    first_table = len(text)
    at_root = True
    for tokens in _statements(text):
        raw = [text[start:end] for start, end in tokens]
        if raw[0] == "[":
            if "\n" in text[tokens[0][0]:tokens[-1][1]]:
                raise ValueError("multiline table header")
            array = len(raw) > 1 and raw[1] == "["
            trim = 2 if array else 1
            if raw[-trim:] != ["]"] * trim:
                raise ValueError("malformed table")
            names = _key_parts(raw[trim:-trim])
            if names[0] == _SETTING:
                raise ValueError("reviewer table conflicts with root value")
            line_start = text.rfind("\n", 0, tokens[0][0]) + 1
            first_table = min(first_table, line_start)
            at_root = False
            continue
        equals = raw.index("=") if "=" in raw else -1
        if equals < 1 or equals == len(raw) - 1:
            raise ValueError("malformed assignment")
        names = _key_parts(raw[:equals])
        if not at_root or names[0] != _SETTING:
            continue
        if len(names) != 1 or assignment is not None or len(raw[equals + 1:]) != 1:
            raise ValueError("ambiguous reviewer")
        assignment = tokens[equals + 1]
    return assignment, first_table


def _key_parts(tokens: list[str]) -> list[str]:
    if not tokens or len(tokens) % 2 == 0:
        raise ValueError("malformed key")
    names = []
    for index, token in enumerate(tokens):
        if index % 2:
            if token != ".":
                raise ValueError("malformed dotted key")
        elif _BARE_KEY.fullmatch(token):
            names.append(token)
        elif (
            len(token) >= 2 and token[0] in {'"', "'"}
            and token[-1] == token[0]
            and "\n" not in token and "\r" not in token
            and not token.startswith(('"""', "'''"))
        ):
            # TOML literal keys retain backslashes; basic keys decode the
            # JSON-compatible escape subset after TOML lexical validation.
            name = token[1:-1] if token[0] == "'" else json.loads(token)
            if any(0xD800 <= ord(character) <= 0xDFFF for character in name):
                raise ValueError("unsupported unicode key")
            names.append(name)
        else:
            raise ValueError("unsupported key")
    return names


def _statements(text: str):
    """Yield token spans; quoted strings and comments never become headers."""
    tokens = []
    brackets = []
    index = 0
    while index < len(text):
        character = text[index]
        if character in " \t\r":
            index += 1
            continue
        if character == "#":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        if character == "\n":
            if tokens and not brackets:
                yield tokens
                tokens = []
            index += 1
            continue
        start = index
        if character in {'"', "'"}:
            index = _string_end(text, index)
        elif character in _PUNCTUATION:
            if character in "[{":
                brackets.append(character)
            elif character in "]}":
                expected = "[" if character == "]" else "{"
                if not brackets or brackets.pop() != expected:
                    raise ValueError("unbalanced brackets")
            index += 1
        else:
            while (
                index < len(text) and not text[index].isspace()
                and text[index] not in _PUNCTUATION + "#\"'"
            ):
                if ord(text[index]) < 32 or ord(text[index]) == 127:
                    raise ValueError("invalid control character")
                index += 1
            if index == start:
                raise ValueError("unsupported whitespace")
        tokens.append((start, index))
    if brackets:
        raise ValueError("unclosed brackets")
    if tokens:
        yield tokens


def _string_end(text: str, start: int) -> int:
    quote = text[start]
    multiline = text.startswith(quote * 3, start)
    index = start + (3 if multiline else 1)
    while index < len(text):
        character = text[index]
        if character == quote:
            if not multiline:
                return index + 1
            end = index
            while end < len(text) and text[end] == quote:
                end += 1
            if 3 <= end - index <= 5:
                return end
            if end - index > 5:
                raise ValueError("unsupported quote run")
            index = end
            continue
        if character in "\r\n" and not multiline:
            raise ValueError("newline in single-line string")
        if ord(character) < 32 and character not in "\t\r\n":
            raise ValueError("invalid string control character")
        if character == "\\" and quote == '"':
            index += 1
            if index >= len(text):
                break
            escape = text[index]
            if multiline and escape in " \t\r\n":
                while index < len(text) and text[index] in " \t\r\n":
                    index += 1
                continue
            if escape in "uU":
                width = 4 if escape == "u" else 8
                digits = text[index + 1:index + 1 + width]
                if len(digits) != width or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                    raise ValueError("invalid unicode escape")
                index += width
            elif escape not in 'btnfr"\\':
                raise ValueError("invalid escape")
        index += 1
    raise ValueError("unclosed string")
