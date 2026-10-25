from __future__ import annotations

from typing import Iterable, Any


class MetricCalculator:
    """Class-based utilities for scenario evaluation calculations."""

    @staticmethod
    def calculate_violation_rate(failed_checks: int, executed_checks: int) -> float | None:
        if executed_checks <= 0:
            return None
        return (failed_checks / executed_checks) * 100.0

    @staticmethod
    def calculate_acceptance_rate(accepted: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return (accepted / total) * 100.0

    @staticmethod
    def calculate_connectivity_correctness(test_cases: Iterable[Any]) -> float:
        test_cases = list(test_cases)
        if not test_cases:
            return 0.0
        correct = sum(1 for item in test_cases if item.is_correct)
        return (correct / len(test_cases)) * 100.0

    @staticmethod
    def calculate_architecture_adherence(items: Iterable[Any]) -> float:
        items = list(items)
        if not items:
            return 0.0
        satisfied = sum(1 for item in items if item.satisfied)
        return (satisfied / len(items)) * 100.0

