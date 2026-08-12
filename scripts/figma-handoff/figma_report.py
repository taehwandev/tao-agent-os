"""Compatibility facade for summary, Markdown, and manifest generation."""

from figma_manifest import build_manifest
from figma_markdown import _format_gradient, render_markdown
from figma_summary import build_summary

__all__ = ["build_manifest", "build_summary", "render_markdown"]
