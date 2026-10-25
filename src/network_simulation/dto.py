from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScenarioSpecDTO:
    """Structured contract for a scenario definition loaded from YAML."""

    scenario_id: str
    name: str
    objective: str = ""
    required_components: dict[str, str] = field(default_factory=dict)
    acceptance_criteria: list[str] = field(default_factory=list)
    connectivity_requirements: list[str] = field(default_factory=list)
    security_requirements: list[str] = field(default_factory=list)
    architectural_requirements: list[str] = field(default_factory=list)
    extends: list[str] = field(default_factory=list)
    context_chain: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, scenario_id: str, raw: dict[str, Any]) -> "ScenarioSpecDTO":
        return cls(
            scenario_id=scenario_id.upper(),
            name=str(raw.get("name") or scenario_id),
            objective=str(raw.get("objective") or ""),
            required_components={
                str(key): str(value)
                for key, value in (raw.get("required_components") or {}).items()
            },
            acceptance_criteria=list(raw.get("acceptance_criteria") or []),
            connectivity_requirements=list(raw.get("connectivity_requirements") or []),
            security_requirements=list(raw.get("security_requirements") or []),
            architectural_requirements=list(raw.get("architectural_requirements") or []),
            extends=list(raw.get("extends") or []),
            context_chain=list(raw.get("context_chain") or []),
        )


@dataclass(frozen=True)
class GeneratedTemplateDTO:
    """Structured representation of a generated solution candidate."""

    scenario_id: str
    condition: str
    template_path: str
    template_content: str = ""
    iteration_number: int = 0


@dataclass(frozen=True)
class ValidationResultDTO:
    """Validation output normalized for downstream metric computation."""

    scenario_id: str
    condition: str
    template_path: str
    framework: str
    total_checks: int
    passed: int
    failed: int
    skipped: int
    security_violations: int
    policy_violations: int
    raw_findings: list[str] = field(default_factory=list)

    @property
    def total_violations(self) -> int:
        return self.security_violations + self.policy_violations

    @property
    def acceptance_rate(self) -> float:
        if self.total_checks <= 0:
            return 0.0
        return (self.passed / self.total_checks) * 100.0

    @classmethod
    def from_checkov_report(cls, report: Any, condition: str = "T1") -> "ValidationResultDTO":
        return cls(
            scenario_id=str(getattr(report, "scenario_id", "unknown")).upper(),
            condition=condition,
            template_path=str(getattr(report, "template_path", "unknown")),
            framework="bicep",
            total_checks=int(getattr(report, "total_checks", 0) or 0),
            passed=int(getattr(report, "passed", 0) or 0),
            failed=int(getattr(report, "failed", 0) or 0),
            skipped=int(getattr(report, "skipped", 0) or 0),
            security_violations=len(getattr(report, "security_violations", []) or []),
            policy_violations=len(getattr(report, "policy_violations", []) or []),
            raw_findings=[
                getattr(item, "check_id", str(item))
                for item in list(getattr(report, "results", []) or [])
            ],
        )


@dataclass(frozen=True)
class ScenarioEvaluationDTO:
    """Normalized evaluation contract produced after metric aggregation."""

    scenario_id: str
    condition: str
    acceptance_rate: float
    violation_rate: float | None
    connectivity_correctness: float
    architecture_adherence: float
    security_violations_count: int
    policy_violations_count: int
    total_violations: int
    policy_checks_executed: int = 0
    policy_checks_failed: int = 0
    iterations_to_acceptance: int = 0
    total_execution_time_seconds: float = 0.0
