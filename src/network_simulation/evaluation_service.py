from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from network_simulation.dto import GeneratedTemplateDTO, ScenarioEvaluationDTO, ValidationResultDTO
from network_simulation.metrics import MetricAnalyzer, NetworkScenarioMetrics


@dataclass
class EvaluationService:
    """Translate generated templates + validation results into scenario metrics."""

    analyzer: MetricAnalyzer | None = None

    def __post_init__(self) -> None:
        if self.analyzer is None:
            self.analyzer = MetricAnalyzer()

    def evaluate_condition(
        self,
        *,
        template: GeneratedTemplateDTO,
        validation: ValidationResultDTO,
        acceptance_criteria_total: int,
        acceptance_criteria_met: int,
        connectivity_tests: Iterable | None = None,
        architecture_requirements: Iterable | None = None,
        iterations_to_acceptance: int | None = None,
        total_execution_time_seconds: float = 0.0,
    ) -> ScenarioEvaluationDTO:
        metrics = NetworkScenarioMetrics.from_validation_result(
            validation,
            scenario_id=template.scenario_id,
            condition=template.condition,
            acceptance_criteria_total=acceptance_criteria_total,
            acceptance_criteria_met=acceptance_criteria_met,
            connectivity_tests=list(connectivity_tests or []),
            architecture_requirements=list(architecture_requirements or []),
            iterations_to_acceptance=iterations_to_acceptance,
            total_execution_time_seconds=total_execution_time_seconds,
        )
        self.analyzer.add_scenario_metrics(template.scenario_id, template.condition, metrics)
        return metrics.to_evaluation_dto()
