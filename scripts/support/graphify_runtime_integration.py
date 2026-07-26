"""Deprecated no-op adapter for removed target-project Graphify integrations."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def normalize_runtime_integrations(
    project_path: Path,
    platforms: Iterable[str],
) -> list[dict[str, str]]:
    del project_path, platforms
    return []
