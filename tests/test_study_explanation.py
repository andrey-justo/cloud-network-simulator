from pathlib import Path

from network_simulation import study_acceptance
from network_simulation.live_experiment import _sha256
from network_simulation.study_acceptance import evaluate_structure, scenario_contract
from network_simulation.study_explanation import explain_checks
from test_study import contract_template, write_template


def evidence(template, evaluation):
    return {
        "template": template, "evaluation": evaluation,
        "contract": scenario_contract("NET-04"),
        "evaluator_sha256": _sha256(Path(study_acceptance.__file__).read_text(encoding="utf-8")),
    }


def test_extra_nsg_explains_benchmark_mismatch_without_rescoring(tmp_path, monkeypatch):
    template = contract_template("NET-04")
    template["resources"].append({
        "type": "Microsoft.Network/networkSecurityGroups",
        "name": "benchmark-workload-nsg", "properties": {},
    })
    recorded = evaluate_structure(write_template(tmp_path, template), "NET-04")
    assert [c["id"] for c in recorded["checks"] if c["status"] != "passed"] == ["bounded-resource-types-and-scope"]
    monkeypatch.setattr(study_acceptance, "evaluate_structure", lambda *a: (_ for _ in ()).throw(AssertionError("Explanations must not rescore")))
    explanation = explain_checks(evidence(template, recorded))
    check = next(c for c in explanation["checks"] if c["id"] == "bounded-resource-types-and-scope")
    assert check["status"] == "failed"
    assert "valid and useful" in check["explanation"]
    assert check["evidence"] == ["Extra resource not declared by this contract: Microsoft.Network/networkSecurityGroups / benchmark-workload-nsg"]
    assert explanation["warnings"] == []
    assert recorded["status"] == "failed"


def test_explicit_scope_and_supported_storage_are_distinguished(tmp_path):
    template = contract_template("NET-04")
    template["resources"][0]["scope"] = "[resourceGroup().id]"
    template["resources"].append({"type": "Microsoft.Storage/storageAccounts", "name": "auditstore"})
    recorded = evaluate_structure(write_template(tmp_path, template), "NET-04")
    check = next(c for c in explain_checks(evidence(template, recorded))["checks"] if c["id"] == "bounded-resource-types-and-scope")
    assert len(check["evidence"]) == 1
    assert "Explicit ARM scope rejected" in check["evidence"][0]
    assert "auditstore" not in str(check["evidence"])


def test_unavailable_or_different_evaluator_evidence_is_explicit(tmp_path):
    template = contract_template("NET-04")
    recorded = {"status": "failed", "checks": [{"id": "bounded-resource-types-and-scope", "status": "failed"}]}
    payload = evidence(template, recorded)
    payload.update(template=None, evaluator_sha256="different")
    detail = explain_checks(payload)
    assert "provisional" in detail["warnings"][0]
    assert "unavailable" in detail["checks"][0]["evidence"][0]
    assert detail["checks"][0]["status"] == "failed"
