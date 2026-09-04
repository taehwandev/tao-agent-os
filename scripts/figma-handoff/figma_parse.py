"""Compatibility facade for style and variable parsing."""

from figma_style_parse import (  # noqa: F401
    StyleParser,
    _parse_effect_entry,
)
from figma_variable_parse import parse_variables

build_referenced_styles = StyleParser.build_referenced_styles
parse_named_color_styles = StyleParser.parse_named_color_styles
parse_named_effect_styles = StyleParser.parse_named_effect_styles
parse_named_text_styles = StyleParser.parse_named_text_styles

__all__ = [
    "build_referenced_styles",
    "parse_named_color_styles",
    "parse_named_effect_styles",
    "parse_named_text_styles",
    "parse_variables",
]
