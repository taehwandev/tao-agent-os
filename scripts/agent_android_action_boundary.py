"""Bounded Kotlin Compose action/effect ownership checks.

Owner: source-level Android action boundary diagnostics.
Allowed imports: standard library. Forbidden: execution, network, project writes.
Callers/tests: structure_review; test_agent_android_action_boundary.
Verification: positive/negative Kotlin fixtures and real structure CLI tests.
This is a lexical guard, not Kotlin type resolution or whole-program analysis.
"""

from __future__ import annotations

import re
from pathlib import Path


class AndroidActionBoundary:
    """Reject recognizable effect decisions in changed composable bodies."""

    _event = re.compile(r"\b\w*(?:RouteEvent|NavigationEvent|NoticeEffect)\s*\.\s*[A-Z]\w*\b")
    _data = re.compile(
        r"\b(?:\w*(?:Repository|UseCase|DataSource|ApiClient)|repository|useCase|api|dao)"
        r"\s*(?:\?\.)?\s*\.?(?:\s*\w+\s*)?\("
    )
    _effect = re.compile(
        r"\b(?:\w+\s*\.)?(?:navigate|popBackStack|navigateUp|showSnackbar|showToast|"
        r"showNotice|showAlert|startActivity|onRouteEvent|onNavigate\w*|onStartThread|"
        r"onShowNotice|onShowToast|onShowAlert)\s*\(|\bToast\s*\.\s*makeText\s*\("
    )
    _callback = re.compile(r"\bon\w+\s*=\s*\{|\b(?:clickable|combinedClickable)\s*(?:\([^{}]*\))?\s*\{")

    @classmethod
    def failures(cls, path: Path, source: str) -> list[str]:
        if path.suffix != ".kt":
            return []
        code = _mask_kotlin_literals(source)
        for original, alias in re.findall(r"import\s+([\w.]+)\s+as\s+(\w+)", code):
            if original == "androidx.compose.runtime.Composable":
                code = re.sub(r"@" + re.escape(alias) + r"\b", "@Composable", code)
            elif re.search(r"(?:RouteEvent|NavigationEvent|NoticeEffect)(?:\.|$)", original):
                code = re.sub(r"\b" + re.escape(alias) + r"\b", original, code)
        findings = []
        for signature, start, end in cls._bodies(code):
            body = code[start:end]
            parameters = code[signature:start]
            # Resolve explicit parameter types locally, never from another function.
            vm_names = re.findall(r"\b(\w+)\s*:\s*(?:\w+\.)*\w*ViewModel\b", parameters)
            receivers = r"(?:viewModel|\w+ViewModel" + "".join("|" + re.escape(name) for name in vm_names) + ")"
            leaf_callbacks = set(re.findall(r"\b(on\w+)\s*:\s*\(\s*\)\s*->\s*Unit\b", parameters))
            callbacks = cls._regions(body, cls._callback)
            collectors = cls._regions(body, re.compile(
                r"\b" + receivers + r"\s*\.\s*(?:effects|uiEffects|sideEffects)\s*"
                r"\.\s*(?:collect|collectLatest)\s*\{"
            ))
            matches = [(m, "effect construction") for m in cls._event.finditer(body)]
            matches += [(m, "data request") for m in cls._data.finditer(body)]
            for match in cls._effect.finditer(body):
                if any(re.fullmatch(re.escape(name) + r"\s*\(", match[0])
                       for name in leaf_callbacks):
                    continue
                if re.match(receivers + r"\s*\.", body[match.start():]):
                    continue
                in_callback = any(a <= match.start() < b for a, b in callbacks)
                in_collector = any(a <= match.start() < b for a, b in collectors)
                if in_callback or not in_collector:
                    matches.append((match, "effect dispatch"))
            # A business callback passed through unchanged still bypasses the VM.
            matches += [(m, "effect callback forwarding") for m in re.finditer(
                r"\bon\w+\s*=\s*(?:onStartThread|onRouteEvent|onNavigate\w*|onShowNotice|onShowToast|onShowAlert)\b(?!\s*\()",
                body,
            ) if m[0].split("=", 1)[1].strip() not in leaf_callbacks]
            for match in re.finditer(
                r"\b\w+\s*::\s*(?:navigate|popBackStack|navigateUp|showSnackbar|"
                r"showToast|showNotice|showAlert|startActivity)\b", body,
            ):
                receiver = match.group().split("::", 1)[0].strip()
                if receiver not in vm_names and receiver != "viewModel" and not receiver.endswith("ViewModel"):
                    matches.append((match, "effect callback forwarding"))
            for match, reason in matches:
                line = code.count("\n", 0, start + match.start()) + 1
                findings.append(
                    f"{path}:{line}: Android action boundary: {reason} in Compose; "
                    "send a typed Action to ViewModel, let it invoke data/effect ports. "
                    "Only consume ViewModel effects in the lifecycle UI host."
                )
        return sorted(set(findings))

    @classmethod
    def _regions(cls, code: str, pattern: re.Pattern) -> list[tuple[int, int]]:
        return [(match.end() - 1, cls._close(code, match.end() - 1, "{", "}"))
                for match in pattern.finditer(code)]

    @staticmethod
    def _close(code: str, start: int, opening: str, closing: str) -> int:
        depth = 0
        for index in range(start, len(code)):
            if code[index] == opening:
                depth += 1
            elif code[index] == closing:
                depth -= 1
                if depth == 0:
                    return index + 1
        return len(code)

    @classmethod
    def _bodies(cls, code: str):
        for annotation in re.finditer(r"@(?:androidx\.compose\.runtime\.)?Composable\b", code):
            declaration = re.search(r"\bfun\s+(?:\w+\.)?\w+\s*\(", code[annotation.end():])
            if not declaration:
                continue
            signature = annotation.end() + declaration.end() - 1
            # A Composable function-typed parameter is not a new declaration.
            between = code[annotation.end():signature]
            if re.search(r"[{}=]", between):
                continue
            end = cls._close(code, signature, "(", ")")
            body = re.match(r"\s*(?::\s*[\w?.<>]+\s*)?(\{|=)", code[end:])
            if not body:
                continue
            start = end + body.end() - 1
            if body[1] == "{":
                yield signature, start, cls._close(code, start, "{", "}")
            else:
                following = re.search(r"\n(?:@|(?:private |internal )?fun\b)", code[start:])
                yield signature, start, start + following.start() if following else len(code)


def _mask_kotlin_literals(source: str) -> str:
    """Blank comments and literal text while preserving offsets and newlines."""
    chars = list(source)
    index = 0
    while index < len(source):
        start = index
        if source.startswith("//", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
        elif source.startswith("/*", index):
            index += 2
            depth = 1
            while index < len(source) and depth:
                if source.startswith("/*", index):
                    depth += 1
                    index += 2
                elif source.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
        elif source.startswith('"""', index):
            end = source.find('"""', index + 3)
            index = len(source) if end < 0 else end + 3
        elif source[index] in "\"'":
            quote = source[index]
            index += 1
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                elif source[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
        else:
            index += 1
            continue
        for position in range(start, min(index, len(source))):
            if chars[position] != "\n":
                chars[position] = " "
    return "".join(chars)
