"""YAML-backed scenario catalog with lazy loading and a small in-memory cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from network_simulation.scenario_context import resolve_scenario_context as resolve_context

SCENARIO_DIR = Path(__file__).resolve().parent / "specs"
SCENARIO_CATALOG_PATH = Path(__file__).resolve().parent / "scenario_catalog.yml"
NET_SCENARIO_SPECS: dict[str, dict[str, Any]] = {}
SCENARIO_CATALOG: dict[str, dict[str, Any]] = {}


def _load_scenario_catalog() -> dict[str, dict[str, Any]]:
    """Load the initial scenario metadata catalog from YAML."""
    global SCENARIO_CATALOG

    if SCENARIO_CATALOG:
        return SCENARIO_CATALOG

    if not SCENARIO_CATALOG_PATH.exists():
        return {}

    with SCENARIO_CATALOG_PATH.open("r", encoding="utf-8") as fh:
        raw_catalog = yaml.safe_load(fh) or {}

    if isinstance(raw_catalog, list):
        normalized = {}
        for item in raw_catalog:
            scenario_id = str(item.get("id", "")).strip()
            if not scenario_id:
                continue
            normalized[scenario_id.upper()] = item
        raw_catalog = normalized

    catalog = {}
    for scenario_id, metadata in (raw_catalog or {}).items():
        if not isinstance(metadata, dict):
            continue
        catalog[str(scenario_id).upper()] = metadata

    SCENARIO_CATALOG = catalog
    return catalog


def _scenario_slug(scenario_id: str) -> str:
    """Build a descriptive filename slug from the scenario id."""
    scenario_key = scenario_id.strip().upper()
    if not scenario_key:
        return ""
    return scenario_key.lower().replace("-", "-")


def _scenario_file_path(scenario_id: str) -> Path:
    scenario_key = scenario_id.strip().upper()
    if not scenario_key:
        return SCENARIO_DIR / "unknown.yml"

    catalog = _load_scenario_catalog()
    metadata = catalog.get(scenario_key, {})
    filename = metadata.get("file") or metadata.get("filename")
    if filename:
        return SCENARIO_DIR / str(filename)

    scenario_slug = scenario_key.lower()
    if scenario_key.startswith("NET-"):
        return SCENARIO_DIR / f"{scenario_slug}-{_scenario_title_lookup(scenario_key).lower().replace(' ', '-')}.yml"

    return SCENARIO_DIR / f"{scenario_slug}.yml"


def _scenario_title_lookup(scenario_id: str) -> str:
    scenario_key = scenario_id.upper()
    catalog = _load_scenario_catalog()
    metadata = catalog.get(scenario_key, {})
    title = metadata.get("title") or metadata.get("name")
    if title:
        return str(title)
    return scenario_key


def _normalize_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("A scenario file must contain a YAML object.")

    normalized = dict(raw)
    for key in ("acceptance_criteria", "connectivity_requirements", "security_requirements", "architectural_requirements"):
        value = normalized.get(key, [])
        if value is None:
            normalized[key] = []
        elif isinstance(value, str):
            normalized[key] = [value]
        else:
            normalized[key] = list(value)

    extends = normalized.get("extends", [])
    if extends is None:
        normalized["extends"] = []
    elif isinstance(extends, str):
        normalized["extends"] = [extends]
    else:
        normalized["extends"] = list(extends)

    required = normalized.get("required_components", {})
    if required is None:
        normalized["required_components"] = {}
    elif not isinstance(required, dict):
        normalized["required_components"] = {"value": str(required)}

    return normalized


def _load_scenario_from_disk(scenario_id: str) -> dict[str, Any]:
    file_path = _scenario_file_path(scenario_id)
    if not file_path.exists():
        return {}

    with file_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    spec = _normalize_scenario(data)
    NET_SCENARIO_SPECS[scenario_id.upper()] = spec
    return spec


def resolve_scenario_context(scenario_id: str) -> dict[str, Any]:
    """Return the merged scenario context including inherited parent scenarios."""
    return resolve_context(scenario_id, get_scenario_spec)


def get_scenario_spec(scenario_id: str) -> dict:
    """Return a scenario specification, loading it on demand and caching it."""
    scenario_key = scenario_id.upper()
    if scenario_key in NET_SCENARIO_SPECS:
        return NET_SCENARIO_SPECS[scenario_key]

    spec = _load_scenario_from_disk(scenario_key)
    return spec


def list_all_scenarios() -> list[str]:
    """List all scenario ids and populate the cache lazily."""
    if not SCENARIO_DIR.exists():
        return []

    ids = []
    for path in sorted(SCENARIO_DIR.glob("*.yml")):
        if not path.is_file():
            continue
        scenario_name = path.stem
        ids.append(scenario_name)
        if scenario_name.upper() not in NET_SCENARIO_SPECS:
            _load_scenario_from_disk(scenario_name)

    return ids


if __name__ == "__main__":
    import json

    scenarios = {scenario_id: get_scenario_spec(scenario_id) for scenario_id in list_all_scenarios()}
    print(json.dumps(scenarios, indent=2, ensure_ascii=False))
