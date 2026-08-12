from __future__ import annotations

from typing import Any

from figma_util import _color_dict_to_hex

__all__ = ["parse_variables"]


def parse_variables(variables: dict[str, Any]) -> dict[str, Any]:
    meta = variables.get("meta", {})
    collections: list[dict[str, Any]] = []
    raw_collections = meta.get("variableCollections", {})
    for collection in raw_collections.values() if isinstance(raw_collections, dict) else []:
        modes = [
            {"modeId": mode.get("modeId", ""), "name": mode.get("name", "")}
            for mode in collection.get("modes", [])
            if isinstance(mode, dict)
        ]
        collections.append(
            {
                "id": collection.get("id", ""),
                "name": collection.get("name", ""),
                "modes": modes,
                "defaultModeId": collection.get("defaultModeId", ""),
            }
        )

    parsed_variables: list[dict[str, Any]] = []
    raw_variables = meta.get("variables", {})
    default_modes = {
        str(collection["id"]): str(collection.get("defaultModeId", ""))
        for collection in collections
        if collection.get("id")
    }
    for variable in raw_variables.values() if isinstance(raw_variables, dict) else []:
        entry: dict[str, Any] = {
            "id": variable.get("id", ""),
            "name": variable.get("name", ""),
            "resolvedType": variable.get("resolvedType", ""),
            "collectionId": variable.get("variableCollectionId", ""),
            "valuesByMode": {},
        }
        for mode_id, raw_value in variable.get("valuesByMode", {}).items():
            if isinstance(raw_value, dict) and raw_value.get("type") == "VARIABLE_ALIAS":
                alias_id = raw_value.get("id", "")
                entry["valuesByMode"][mode_id] = {"alias": alias_id, "aliasId": alias_id}
            elif isinstance(raw_value, dict) and variable.get("resolvedType") == "COLOR":
                entry["valuesByMode"][mode_id] = {"hex": _color_dict_to_hex(raw_value), "raw": raw_value}
            else:
                entry["valuesByMode"][mode_id] = raw_value
        parsed_variables.append(entry)

    variables_by_id = {str(variable.get("id", "")): variable for variable in parsed_variables if variable.get("id")}
    collections_by_id = {str(collection.get("id", "")): str(collection.get("name", "")) for collection in collections}
    for variable in parsed_variables:
        for mode_id, value in variable.get("valuesByMode", {}).items():
            if not isinstance(value, dict) or not value.get("aliasId"):
                continue
            alias_id = str(value["aliasId"])
            value["aliasName"] = _variable_display_name(alias_id, variables_by_id, collections_by_id)
            resolved = _resolve_variable_value(alias_id, str(mode_id), variables_by_id, default_modes, set())
            if isinstance(resolved, dict):
                if resolved.get("hex"):
                    value["resolvedHex"] = resolved["hex"]
                elif resolved.get("aliasName"):
                    value["resolvedAliasName"] = resolved["aliasName"]
    return {"collections": collections, "variables": parsed_variables}


def _variable_display_name(
    variable_id: str,
    variables_by_id: dict[str, dict[str, Any]],
    collections_by_id: dict[str, str],
) -> str:
    variable = variables_by_id.get(variable_id)
    if not variable:
        return variable_id
    collection_name = collections_by_id.get(str(variable.get("collectionId", "")), "")
    variable_name = str(variable.get("name", ""))
    return "/".join(part for part in (collection_name, variable_name) if part) or variable_id


def _resolve_variable_value(
    variable_id: str,
    mode_id: str,
    variables_by_id: dict[str, dict[str, Any]],
    default_modes: dict[str, str],
    seen: set[str],
) -> Any:
    if variable_id in seen:
        return None
    seen.add(variable_id)
    variable = variables_by_id.get(variable_id)
    if not variable:
        return None
    values = variable.get("valuesByMode", {})
    if not isinstance(values, dict) or not values:
        return None
    value = values.get(mode_id)
    if value is None:
        default_mode = default_modes.get(str(variable.get("collectionId", "")), "")
        value = values.get(default_mode) if default_mode else None
    if value is None:
        value = next(iter(values.values()))
    if isinstance(value, dict) and value.get("aliasId"):
        return _resolve_variable_value(str(value["aliasId"]), mode_id, variables_by_id, default_modes, seen)
    return value
