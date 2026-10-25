from network_simulation.metrics import (
    ArchitectureMetric,
    ConnectivityMetric,
    MetricAnalyzer,
    MetricCalculator,
    NetworkScenarioMetrics,
)
from evaluation.metric_analyzer import NetworkScenarioMetrics as LegacyScenarioMetrics
from evaluation.metric_analyzer import MetricAnalyzer as LegacyMetricAnalyzer
from experiments.experiment_runner import (
    ConditionType, ExperimentRunner, IterationResult, ScenarioExperimentResult,
)


def test_network_metrics_calculate_derived_values() -> None:
    metrics = NetworkScenarioMetrics(
        scenario_id="NET-01",
        condition="T1",
        total_violations=2,
        policy_checks_executed=10,
        policy_checks_failed=2,
        acceptance_criteria_total=10,
        acceptance_criteria_met=8,
        connectivity_tests=[
            ConnectivityMetric(
                source_tier="web",
                dest_tier="app",
                protocol="tcp",
                port=443,
                expected_allowed=True,
                actually_allowed=True,
            ),
            ConnectivityMetric(
                source_tier="app",
                dest_tier="db",
                protocol="tcp",
                port=5432,
                expected_allowed=False,
                actually_allowed=False,
            ),
        ],
        architecture_requirements=[
            ArchitectureMetric("Segmentation boundary enforced", True),
            ArchitectureMetric("Private endpoint required", False),
        ],
    )

    metrics.calculate_metrics()

    assert metrics.violation_rate == 20.0
    assert metrics.acceptance_rate == 80.0
    assert metrics.connectivity_correctness == 100.0
    assert metrics.architecture_adherence == 50.0
    assert metrics.violation_rate == 20.0


def test_violation_rate_is_undefined_without_executed_policy_checks() -> None:
    metrics = NetworkScenarioMetrics(scenario_id="NET-01", condition="B1")

    metrics.calculate_metrics()

    assert metrics.violation_rate is None


def test_legacy_violation_rate_uses_executed_policy_checks() -> None:
    metrics = LegacyScenarioMetrics(
        scenario_id="NET-01",
        condition="B1",
        total_violations=7,
        acceptance_criteria_total=3,
        policy_checks_executed=20,
        policy_checks_failed=4,
    )

    metrics.calculate_metrics()

    assert metrics.violation_rate == 20.0


def test_metric_analyzer_compare_conditions() -> None:
    analyzer = MetricAnalyzer()

    b1 = NetworkScenarioMetrics(
        scenario_id="NET-02",
        condition="B1",
        total_violations=5,
        policy_checks_executed=10,
        policy_checks_failed=5,
        acceptance_criteria_total=10,
        acceptance_criteria_met=5,
        connectivity_tests=[
            ConnectivityMetric("a", "b", "tcp", 80, True, True),
            ConnectivityMetric("b", "c", "tcp", 443, True, False),
        ],
        architecture_requirements=[
            ArchitectureMetric("segmentation", True),
            ArchitectureMetric("private endpoint", False),
        ],
        iterations_to_acceptance=4,
        total_execution_time_seconds=12.0,
    )
    b1.calculate_metrics()

    t1 = NetworkScenarioMetrics(
        scenario_id="NET-02",
        condition="T1",
        total_violations=1,
        policy_checks_executed=10,
        policy_checks_failed=1,
        acceptance_criteria_total=10,
        acceptance_criteria_met=9,
        connectivity_tests=[
            ConnectivityMetric("a", "b", "tcp", 80, True, True),
            ConnectivityMetric("b", "c", "tcp", 443, True, True),
        ],
        architecture_requirements=[
            ArchitectureMetric("segmentation", True),
            ArchitectureMetric("private endpoint", True),
        ],
        iterations_to_acceptance=2,
        total_execution_time_seconds=7.0,
    )
    t1.calculate_metrics()

    analyzer.add_scenario_metrics("NET-02", "B1", b1)
    analyzer.add_scenario_metrics("NET-02", "T1", t1)

    comparison = analyzer.compare_conditions("NET-02")

    assert comparison["hypothesis_tests"]["h1_violation_difference"] is True
    assert comparison["hypothesis_tests"]["h2_acceptance_improvement"] is True
    assert "quality_score_delta" not in comparison["comparison"]


def test_efficiency_uses_elapsed_time_not_iteration_count(tmp_path):
    result = ScenarioExperimentResult("NET-01", "test")
    result.b1_iterations = [
        IterationResult(number, ConditionType.B1, "", "", validation_passed=number == 2, execution_time_seconds=1)
        for number in (1, 2)
    ]
    result.t1_iterations = [
        IterationResult(1, ConditionType.T1, "", "", validation_passed=True, execution_time_seconds=100)
    ]
    runner = ExperimentRunner(output_dir=str(tmp_path))
    runner.add_scenario_result(result)
    assert result.improvement_iterations == 1
    assert runner._test_h3() is False
    result.t1_iterations[0].execution_time_seconds = 0.5
    runner.add_scenario_result(result)
    assert runner._test_h3() is True


def test_non_convergent_runs_have_no_iterations_to_acceptance(tmp_path):
    result = ScenarioExperimentResult("NET-01", "test")
    result.b1_iterations = [IterationResult(1, ConditionType.B1, "", "")]
    result.t1_iterations = [IterationResult(1, ConditionType.T1, "", "")]
    runner = ExperimentRunner(output_dir=str(tmp_path))
    runner.add_scenario_result(result)
    assert result.b1_avg_iterations is None
    assert result.t1_avg_iterations is None
    assert result.improvement_iterations is None
    assert runner._test_h3() is None
    analyzer = MetricAnalyzer()
    for condition in ("B1", "T1"):
        analyzer.add_scenario_metrics("NET-01", condition, NetworkScenarioMetrics("NET-01", condition))
    aggregated = analyzer.aggregate_all_scenarios()
    assert aggregated["hypothesis_support"]["h3_supported"] is None
    assert aggregated["iterations_to_acceptance"]["mean_reduction"] is None
    legacy = LegacyMetricAnalyzer()
    for condition in ("B1", "T1"):
        legacy.add_scenario_metrics("NET-01", condition, LegacyScenarioMetrics("NET-01", condition))
    assert legacy.aggregate_all_scenarios()["hypothesis_support"]["h3_supported"] is None


def test_iterations_to_acceptance_is_first_successful_iteration():
    result = ScenarioExperimentResult("NET-01", "test")
    result.t1_iterations = [
        IterationResult(number, ConditionType.T1, "", "", validation_passed=number >= 2)
        for number in (1, 2, 3)
    ]
    result.calculate_metrics()
    assert result.t1_avg_iterations == 2
