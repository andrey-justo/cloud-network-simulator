from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any

from .types import NetworkScenarioMetrics

logger = logging.getLogger(__name__)


class MetricAnalyzer:
    """Analyze scenario-level results across experimental conditions."""

    def __init__(self) -> None:
        self.scenario_metrics: dict[str, dict[str, NetworkScenarioMetrics]] = {}

    def add_scenario_metrics(
        self,
        scenario_id: str,
        condition: str,
        metrics: NetworkScenarioMetrics,
    ) -> None:
        self.scenario_metrics.setdefault(scenario_id, {})[condition] = metrics

    def compare_conditions(
        self,
        scenario_id: str,
        condition_1: str = "B1",
        condition_2: str = "T1",
    ) -> dict[str, Any]:
        if scenario_id not in self.scenario_metrics:
            logger.warning("No metrics for scenario %s", scenario_id)
            return {}

        metrics_1 = self.scenario_metrics[scenario_id].get(condition_1)
        metrics_2 = self.scenario_metrics[scenario_id].get(condition_2)
        if not metrics_1 or not metrics_2:
            logger.warning("Incomplete data for %s (%s vs %s)", scenario_id, condition_1, condition_2)
            return {}

        return {
            "scenario": scenario_id,
            "condition_1": condition_1,
            "condition_2": condition_2,
            "comparison": {
                "violation_rate_delta": (
                    metrics_2.violation_rate - metrics_1.violation_rate
                    if metrics_1.violation_rate is not None
                    and metrics_2.violation_rate is not None
                    else None
                ),
                "acceptance_rate_delta": metrics_2.acceptance_rate - metrics_1.acceptance_rate,
                "connectivity_correctness_delta": metrics_2.connectivity_correctness - metrics_1.connectivity_correctness,
                "architecture_adherence_delta": metrics_2.architecture_adherence - metrics_1.architecture_adherence,
                "iterations_delta": metrics_1.iterations_to_acceptance - metrics_2.iterations_to_acceptance,
                "time_delta": metrics_1.total_execution_time_seconds - metrics_2.total_execution_time_seconds,
            },
            "hypothesis_tests": {
                "h1_violation_difference": (
                    metrics_1.violation_rate > metrics_2.violation_rate
                    if metrics_1.violation_rate is not None
                    and metrics_2.violation_rate is not None
                    else None
                ),
                "h2_acceptance_improvement": metrics_2.acceptance_rate > metrics_1.acceptance_rate,
                "h3_efficiency": metrics_1.total_execution_time_seconds > metrics_2.total_execution_time_seconds,
            },
        }

    def aggregate_all_scenarios(
        self,
        condition_1: str = "B1",
        condition_2: str = "T1",
    ) -> dict[str, Any]:
        comparisons = []
        for scenario_id in self.scenario_metrics:
            comparison = self.compare_conditions(scenario_id, condition_1, condition_2)
            if comparison:
                comparisons.append(comparison)

        if not comparisons:
            return {}

        violation_deltas = [
            item["comparison"]["violation_rate_delta"]
            for item in comparisons
            if item["comparison"]["violation_rate_delta"] is not None
        ]
        acceptance_deltas = [item["comparison"]["acceptance_rate_delta"] for item in comparisons]
        connectivity_deltas = [item["comparison"]["connectivity_correctness_delta"] for item in comparisons]
        iterations_deltas = [item["comparison"]["iterations_delta"] for item in comparisons]
        h1_results = [
            item["hypothesis_tests"]["h1_violation_difference"]
            for item in comparisons
            if item["hypothesis_tests"]["h1_violation_difference"] is not None
        ]

        return {
            "total_scenarios": len(comparisons),
            "violation_rate": {
                "mean_delta": statistics.mean(violation_deltas) if violation_deltas else None,
                "stdev": statistics.stdev(violation_deltas) if len(violation_deltas) > 1 else 0,
                "details": violation_deltas,
            },
            "acceptance_rate": {
                "mean_delta": statistics.mean(acceptance_deltas),
                "stdev": statistics.stdev(acceptance_deltas) if len(acceptance_deltas) > 1 else 0,
                "details": acceptance_deltas,
            },
            "connectivity_correctness": {
                "mean_delta": statistics.mean(connectivity_deltas),
                "stdev": statistics.stdev(connectivity_deltas) if len(connectivity_deltas) > 1 else 0,
                "details": connectivity_deltas,
            },
            "iterations_to_acceptance": {
                "mean_reduction": statistics.mean(iterations_deltas),
                "stdev": statistics.stdev(iterations_deltas) if len(iterations_deltas) > 1 else 0,
                "details": iterations_deltas,
            },
            "hypothesis_support": {
                "h1_supported": (
                    sum(h1_results) / len(h1_results) if h1_results else None
                ),
                "h2_supported": sum(
                    item["hypothesis_tests"]["h2_acceptance_improvement"] for item in comparisons
                ) / len(comparisons),
                "h3_supported": sum(
                    item["hypothesis_tests"]["h3_efficiency"] for item in comparisons
                ) / len(comparisons),
            },
        }

    def save_analysis(self, output_file: str) -> None:
        analysis = self.aggregate_all_scenarios()
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(analysis, handle, indent=2, default=str)
        logger.info("Analysis saved to %s", output_file)
