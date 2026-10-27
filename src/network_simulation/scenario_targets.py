"""Target capabilities and file-backed high-level scenario expansion."""

from typing import Any

TARGETS = {
    "azure-bicep": {"cloud": "azure", "language": "bicep", "file": "template.bicep"},
    "azure-terraform": {
        "cloud": "azure",
        "language": "terraform",
        "file": "main.tf",
        "provider": "azurerm",
        "version": "4.0.1",
    },
    "aws-terraform": {
        "cloud": "aws",
        "language": "terraform",
        "file": "main.tf",
        "provider": "aws",
        "version": "5.70.0",
    },
}


def scenario_variants(
    scenario_id: str,
    specification: dict[str, Any],
    sources: dict[str, str],
    targets: list[str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    supported = specification.get("supported_targets")
    if (
        not isinstance(supported, list)
        or not supported
        or any(
            not isinstance(target, str) or target not in TARGETS for target in supported
        )
        or len(set(supported)) != len(supported)
    ):
        raise ValueError(
            f"{scenario_id}: supported_targets must list unique known targets."
        )
    for field in ("name", "objective", "family"):
        if (
            not isinstance(specification.get(field), str)
            or not specification[field].strip()
        ):
            raise ValueError(f"{scenario_id}: {field} must be a nonempty string.")
    if not specification.get("acceptance_criteria"):
        raise ValueError(f"{scenario_id}: high-level acceptance_criteria are required.")
    if any(
        key in specification for key in ("resources", "contract", "benchmark_contract")
    ):
        raise ValueError(
            f"{scenario_id}: specifications must not prescribe a resource graph."
        )
    variants = {}
    skipped = []
    for target in targets:
        if target not in supported:
            skipped.append(
                {
                    "intent": scenario_id,
                    "target": target,
                    "reason": f"The YAML specification does not support {target}.",
                }
            )
            continue
        variants[f"{scenario_id}--{target}"] = {
            "intent": scenario_id,
            "target": target,
            "family": specification["family"],
            "specification": {
                key: value
                for key, value in specification.items()
                if key not in ("supported_targets", "family")
            },
            "sources": dict(sources),
            "contract": {
                "version": "high-level-specs-v1",
                "parameters": {},
                "runtime_checks": [],
                "scope": "Independent requirement acceptance is not implemented.",
            },
        }
    return variants, skipped
