from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List

from network_simulation.dto import ScenarioEvaluationDTO, ValidationResultDTO


@dataclass
class ConnectivityMetric:
    """Metric for connectivity truth between two network tiers."""

    source_tier: str
    dest_tier: str
    protocol: str
    port: int
    expected_allowed: bool
    actually_allowed: bool

    @property
    def is_correct(self) -> bool:
        return self.expected_allowed == self.actually_allowed


@dataclass
class ArchitectureMetric:
    """Metric describing adherence to a required architecture rule."""

    requirement: str
    satisfied: bool
    description: Optional[str] = None


@dataclass
class NetworkScenarioMetrics:
    """Aggregated metrics for a scenario under a given condition."""

    scenario_id: str
    condition: str

    security_violations_count: int = 0
    policy_violations_count: int = 0
    total_violations: int = 0
    policy_checks_executed: int = 0
    policy_checks_failed: int = 0
    violation_rate: float | None = None

    accepted: bool = False
    acceptance_criteria_met: int = 0
    acceptance_criteria_total: int = 0
    acceptance_rate: float = 0.0

    connectivity_tests: List[ConnectivityMetric] = field(default_factory=list)
    connectivity_correctness: float = 0.0

    architecture_requirements: List[ArchitectureMetric] = field(default_factory=list)
    architecture_adherence: float = 0.0

    iterations_to_acceptance: int | None = None
    total_execution_time_seconds: float = 0.0

    def calculate_metrics(self) -> None:
        """Recompute derived metrics from the raw observed values."""
        from .calculator import MetricCalculator

        self.violation_rate = MetricCalculator.calculate_violation_rate(
            self.policy_checks_failed,
            self.policy_checks_executed,
        )
        self.acceptance_rate = MetricCalculator.calculate_acceptance_rate(
            self.acceptance_criteria_met,
            self.acceptance_criteria_total,
        )
        self.connectivity_correctness = MetricCalculator.calculate_connectivity_correctness(self.connectivity_tests)
        self.architecture_adherence = MetricCalculator.calculate_architecture_adherence(self.architecture_requirements)

    def as_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "condition": self.condition,
            "security_violations_count": self.security_violations_count,
            "policy_violations_count": self.policy_violations_count,
            "total_violations": self.total_violations,
            "policy_checks_executed": self.policy_checks_executed,
            "policy_checks_failed": self.policy_checks_failed,
            "violation_rate": self.violation_rate,
            "accepted": self.accepted,
            "acceptance_criteria_met": self.acceptance_criteria_met,
            "acceptance_criteria_total": self.acceptance_criteria_total,
            "acceptance_rate": self.acceptance_rate,
            "connectivity_correctness": self.connectivity_correctness,
            "architecture_adherence": self.architecture_adherence,
            "iterations_to_acceptance": self.iterations_to_acceptance,
            "total_execution_time_seconds": self.total_execution_time_seconds,
        }

    def to_evaluation_dto(self) -> ScenarioEvaluationDTO:
        return ScenarioEvaluationDTO(
            scenario_id=self.scenario_id,
            condition=self.condition,
            acceptance_rate=self.acceptance_rate,
            violation_rate=self.violation_rate,
            connectivity_correctness=self.connectivity_correctness,
            architecture_adherence=self.architecture_adherence,
            security_violations_count=self.security_violations_count,
            policy_violations_count=self.policy_violations_count,
            total_violations=self.total_violations,
            policy_checks_executed=self.policy_checks_executed,
            policy_checks_failed=self.policy_checks_failed,
            iterations_to_acceptance=self.iterations_to_acceptance,
            total_execution_time_seconds=self.total_execution_time_seconds,
        )

    @classmethod
    def from_validation_result(
        cls,
        validation_result: ValidationResultDTO,
        *,
        scenario_id: str,
        condition: str,
        acceptance_criteria_total: int = 0,
        acceptance_criteria_met: int = 0,
        connectivity_tests: Optional[List[ConnectivityMetric]] = None,
        architecture_requirements: Optional[List[ArchitectureMetric]] = None,
        iterations_to_acceptance: int | None = None,
        total_execution_time_seconds: float = 0.0,
    ) -> "NetworkScenarioMetrics":
        metrics = cls(
            scenario_id=scenario_id,
            condition=condition,
            security_violations_count=validation_result.security_violations,
            policy_violations_count=validation_result.policy_violations,
            total_violations=validation_result.total_violations,
            policy_checks_executed=max(
                validation_result.total_checks - validation_result.skipped,
                0,
            ),
            policy_checks_failed=validation_result.failed,
            accepted=acceptance_criteria_met >= acceptance_criteria_total,
            acceptance_criteria_met=acceptance_criteria_met,
            acceptance_criteria_total=acceptance_criteria_total,
            connectivity_tests=connectivity_tests or [],
            architecture_requirements=architecture_requirements or [],
            iterations_to_acceptance=iterations_to_acceptance,
            total_execution_time_seconds=total_execution_time_seconds,
        )
        metrics.calculate_metrics()
        return metrics
