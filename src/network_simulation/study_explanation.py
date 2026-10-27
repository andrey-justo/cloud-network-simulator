"""Read-only interpretation of recorded outcomes, never an acceptance oracle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from network_simulation import study_acceptance
from network_simulation.live_experiment import _sha256
from network_simulation.study_acceptance import ArmDocument, ArmEvaluationError

DESCRIPTIONS = {
    "addressing-and-completeness": (
        "Addressing and network completeness",
        "The contract requires the declared virtual networks/subnets, private IPv4 ranges, valid containment and nonoverlapping address spaces.",
    ),
    "experiment-tags": ("Experiment tags", "Each virtual network needs a nonempty Experiment tag."),
    "no-public-workload-nics": ("Workload public-IP restriction", "Workload NICs must not have public IP attachments, except the specifically permitted NET-03 web subnet."),
    "standard-public-ips": ("Public-IP SKU", "Every declared public IP must use the Standard SKU."),
    "bounded-resource-types-and-scope": (
        "Allowed resource identities and deployment scope",
        "The frozen benchmark permits only the declared resource type/name pairs, plus ancillary storage-account/blob-service/container resources. It also rejects a nonempty explicit ARM scope. Extra resources can be valid and useful but still fail this exact-shape benchmark.",
    ),
    "parameter-contract": ("Parameter declarations", "Required parameter types/defaults must match the contract, and secureString parameters must not embed defaults."),
    "unique-service-names": ("Service-name parameterization", "NET-09/NET-10 service names and references must continue to match when studySuffix changes, not merely match a hardcoded local name."),
}


def explain_checks(payload: dict[str, Any]) -> dict[str, Any]:
    evaluation = payload["evaluation"]
    contract = payload["contract"]
    template = payload.get("template")
    expected_hash = payload.get("evaluator_sha256")
    case_contract = contract.get("version") == "network-intents-v1"
    actual_hash = None if case_contract else _sha256(Path(study_acceptance.__file__).read_text(encoding="utf-8"))
    warnings = []
    if case_contract or expected_hash != actual_hash:
        warnings.append("The current ARM resolver or case evaluator differs from the recorded evaluator, or its hash is missing. Resource diagnostics are provisional; recorded outcomes are unchanged.")
    checks = []
    for recorded in evaluation.get("checks", []):
        identity = recorded["id"]
        if identity.startswith("resource:"):
            role = identity.partition(":")[2]
            expected = contract.get("resources", {}).get(role, {})
            title = f"Required resource: {role}"
            explanation = "The named resource must exist and its required properties/references must match the scenario contract."
            evidence = [f"Expected: {expected.get('type', 'unknown type')} / {expected.get('name', 'unknown name')}"]
        else:
            title, explanation = DESCRIPTIONS.get(identity, (identity, "An independent scenario-contract requirement. See the recorded structural report for its exact result."))
            evidence = []
        if recorded.get("error") or recorded.get("reason"):
            evidence.append(str(recorded.get("error") or recorded.get("reason")))
        if identity == "bounded-resource-types-and-scope" and recorded["status"] != "passed" and not case_contract:
            if template is None:
                evidence.append("Compiled ARM evidence is unavailable, so exact offending resources cannot be identified.")
            else:
                try:
                    document = ArmDocument(template, {"studySuffix": "local"})
                    declared = {(item["type"].lower(), item["name"].lower()) for item in contract["resources"].values()}
                    # Interpret the frozen rule; do not replace or rerun the acceptance evaluator.
                    support = {"microsoft.storage/storageaccounts", "microsoft.storage/storageaccounts/blobservices", "microsoft.storage/storageaccounts/blobservices/containers"}
                    for resource in document.resources:
                        label = f"{resource['type']} / {resource['name']}"
                        if resource["type"].lower() not in support and (resource["type"].lower(), resource["name"].lower()) not in declared:
                            evidence.append(f"Extra resource not declared by this contract: {label}")
                        if resource.get("scope"):
                            evidence.append(f"Explicit ARM scope rejected: {label}; scope={resource['scope']}")
                    if not evidence:
                        evidence.append("No offending resource could be identified with the available resolver/parameters. The saved failure remains authoritative; this is not a newly computed pass.")
                except (ArmEvaluationError, ValueError, KeyError, TypeError, IndexError) as error:
                    evidence.append(f"Resource diagnostic unavailable: {error}. The recorded outcome is unchanged.")
        checks.append({
            "id": identity, "status": recorded["status"], "title": title,
            "explanation": explanation, "evidence": evidence,
        })
    return {"checks": checks, "warnings": warnings, "evaluationError": evaluation.get("error")}
