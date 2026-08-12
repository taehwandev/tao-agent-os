"""Compatibility facade for purpose-specific Figma analysis modules."""

from figma_asset_analysis import AssetAnalysis
from figma_color_analysis import ColorAnalysis
from figma_component_analysis import ComponentAnalysis
from figma_interaction_analysis import summarize_flow_interactions
from figma_layout_analysis import LayoutAnalysis

build_asset_inventory = AssetAnalysis.build_asset_inventory
summarize_asset_candidates = AssetAnalysis.summarize_asset_candidates
build_variable_name_map = ColorAnalysis.build_variable_name_map
summarize_colors = ColorAnalysis.summarize_colors
summarize_effects = ColorAnalysis.summarize_effects
summarize_gradients = ColorAnalysis.summarize_gradients
summarize_text_styles = ColorAnalysis.summarize_text_styles
summarize_component_blueprints = ComponentAnalysis.summarize_component_blueprints
summarize_components = ComponentAnalysis.summarize_components
summarize_layout_metrics = LayoutAnalysis.summarize_layout_metrics
summarize_layout_nodes = LayoutAnalysis.summarize_layout_nodes
summarize_text_runs = LayoutAnalysis.summarize_text_runs

__all__ = [
    "build_asset_inventory",
    "build_variable_name_map",
    "summarize_asset_candidates",
    "summarize_colors",
    "summarize_component_blueprints",
    "summarize_components",
    "summarize_effects",
    "summarize_flow_interactions",
    "summarize_gradients",
    "summarize_layout_metrics",
    "summarize_layout_nodes",
    "summarize_text_runs",
    "summarize_text_styles",
]
