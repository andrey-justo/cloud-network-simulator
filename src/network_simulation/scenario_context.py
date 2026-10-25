"""Shared scenario inheritance resolution for catalogs and live workspaces."""

from collections.abc import Callable
from typing import Any


def resolve_scenario_context(
    scenario_id: str,
    load_spec: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    specs: dict[str, dict[str, Any]] = {}
    chain: list[str] = []

    def visit(key: str, ancestors: tuple[str, ...]) -> None:
        if key in ancestors:
            raise ValueError(f"Cyclic scenario inheritance: {' -> '.join((*ancestors, key))}")
        if key in specs:
            return
        spec = load_spec(key)
        if not isinstance(spec, dict) or not spec:
            raise ValueError(f"Scenario {key} is missing or is not a YAML object.")
        parents = spec.get("extends") or []
        if isinstance(parents, str):
            parents = [parents]
        if not isinstance(parents, list) or not all(isinstance(parent, str) and parent.strip() for parent in parents):
            raise ValueError(f"Scenario {key}: extends must contain scenario IDs.")
        for parent in parents:
            visit(parent.strip().upper(), (*ancestors, key))
        specs[key] = spec
        chain.append(key)

    scenario_key = scenario_id.strip().upper()
    visit(scenario_key, ())
    merged = dict(specs[scenario_key])
    merged.update(scenario_id=scenario_key, context_chain=chain, required_components={})
    list_fields = (
        "acceptance_criteria",
        "connectivity_requirements",
        "security_requirements",
        "architectural_requirements",
    )
    for name in list_fields:
        merged[name] = []
    for key in chain:
        spec = specs[key]
        for name in ("name", "objective"):
            if spec.get(name):
                merged[name] = spec[name]
        components = spec.get("required_components") or {}
        if not isinstance(components, dict):
            raise ValueError(f"Scenario {key}: required_components must be an object.")
        merged["required_components"].update(components)
        for name in list_fields:
            values = spec.get(name) or []
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list):
                raise ValueError(f"Scenario {key}: {name} must be a list.")
            for value in values:
                if isinstance(value, dict) and len(value) == 1:
                    flow, outcome = next(iter(value.items()))
                    if isinstance(flow, str) and isinstance(outcome, str):
                        value = f"{flow}: {outcome}"
                if not isinstance(value, str):
                    raise ValueError(f"Scenario {key}: {name} must contain strings or flow mappings.")
                if value not in merged[name]:
                    merged[name].append(value)
    return merged
