from __future__ import annotations

from typing import Any

from figma_util import normalize_node_id, round_number

__all__ = ["summarize_flow_interactions"]


def summarize_flow_interactions(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interactions: list[dict[str, Any]] = []
    for node in nodes:
        node_id = normalize_node_id(str(node.get("id", "")))
        if not node_id:
            continue
        node_name = str(node.get("name", ""))
        legacy_target = _normalize_optional_node_id(node.get("transitionNodeID"))
        legacy_transition = {
            "type": None,
            "durationSeconds": _duration_to_seconds(node.get("transitionDuration")),
            "easingType": node.get("transitionEasing"),
        }
        raw_interactions = node.get("interactions")
        if isinstance(raw_interactions, list) and raw_interactions:
            for interaction in raw_interactions:
                if not isinstance(interaction, dict):
                    continue
                trigger = interaction.get("trigger") if isinstance(interaction.get("trigger"), dict) else {}
                actions = interaction.get("actions")
                if isinstance(actions, list) and actions:
                    interactions.extend(
                        _parse_interaction_action(node_id, node_name, trigger, action, legacy_target)
                        for action in actions
                        if isinstance(action, dict)
                    )
                else:
                    interactions.append(
                        {
                            "fromNodeId": node_id,
                            "fromName": node_name,
                            "triggerType": trigger.get("type"),
                            "actionType": None,
                            "navigation": None,
                            "toNodeId": legacy_target,
                            "destinationSource": "transitionNodeID" if legacy_target else None,
                            "transition": legacy_transition,
                            "rawTrigger": trigger,
                            "rawAction": None,
                        }
                    )
        elif legacy_target:
            interactions.append(
                {
                    "fromNodeId": node_id,
                    "fromName": node_name,
                    "triggerType": None,
                    "actionType": "NODE",
                    "navigation": None,
                    "toNodeId": legacy_target,
                    "destinationSource": "transitionNodeID",
                    "transition": legacy_transition,
                    "rawTrigger": None,
                    "rawAction": None,
                }
            )
    return interactions


def _parse_interaction_action(
    node_id: str,
    node_name: str,
    trigger: dict[str, Any],
    action: dict[str, Any],
    legacy_target: str | None,
) -> dict[str, Any]:
    destination_key = ""
    raw_destination = None
    for key in ("destinationId", "destinationID", "destinationNodeID"):
        if action.get(key):
            destination_key = key
            raw_destination = action.get(key)
            break
    destination = _normalize_optional_node_id(raw_destination)
    destination_source = f"action.{destination_key}" if destination_key and destination else None
    if destination is None and legacy_target:
        destination = legacy_target
        destination_source = "transitionNodeID"

    transition = action.get("transition") if isinstance(action.get("transition"), dict) else {}
    easing = transition.get("easing") if isinstance(transition.get("easing"), dict) else {}
    return {
        "fromNodeId": node_id,
        "fromName": node_name,
        "triggerType": trigger.get("type"),
        "actionType": action.get("type"),
        "navigation": action.get("navigation"),
        "toNodeId": destination,
        "destinationSource": destination_source,
        "transition": {
            "type": transition.get("type"),
            "durationSeconds": _duration_to_seconds(transition.get("duration")),
            "easingType": easing.get("type") or transition.get("easing"),
            "direction": transition.get("direction"),
            "matchLayers": transition.get("matchLayers"),
            "easingFunctionCubicBezier": transition.get("easingFunctionCubicBezier"),
        },
        "rawTrigger": trigger,
        "rawAction": action,
    }


def _normalize_optional_node_id(value: Any) -> str | None:
    return normalize_node_id(value) if isinstance(value, str) and value else None


def _duration_to_seconds(value: Any) -> int | float | None:
    duration = round_number(value)
    if duration is None:
        return None
    return round_number(duration / 1000) if duration > 10 else duration
