"""
Métricas de avaliação para experimentos de IaC em rede
Coleta e analisa: violações, aceitação, conectividade, iterações, tempo
"""

import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path
import statistics
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ConnectivityMetric:
    """Métrica de conectividade entre camadas"""
    source_tier: str  # "web", "app", "data"
    dest_tier: str
    protocol: str  # "tcp", "udp"
    port: int
    expected_allowed: bool
    actually_allowed: bool  # Baseado em NSG rules
    
    @property
    def is_correct(self) -> bool:
        """Verdadeiro se conectividade coincide com expectativa"""
        return self.expected_allowed == self.actually_allowed


@dataclass
class ArchitectureMetric:
    """Métrica de aderência arquitetural"""
    requirement: str  # ex: "Hub-and-Spoke topology", "Private endpoints for data"
    satisfied: bool
    description: Optional[str] = None


@dataclass
class NetworkScenarioMetrics:
    """Métricas agregadas de um cenário de rede"""
    scenario_id: str
    condition: str  # "B0", "B1", "T1"
    
    # Taxa de violações
    security_violations_count: int = 0
    policy_violations_count: int = 0
    total_violations: int = 0
    policy_checks_executed: int = 0
    policy_checks_failed: int = 0
    violation_rate: Optional[float] = None  # failed policy checks / executed policy checks
    
    # Taxa de aceitação
    accepted: bool = False
    acceptance_criteria_met: int = 0
    acceptance_criteria_total: int = 0
    acceptance_rate: float = 0.0  # (met / total) * 100
    
    # Conectividade
    connectivity_tests: List[ConnectivityMetric] = field(default_factory=list)
    connectivity_correctness: float = 0.0  # (correct / total) * 100
    
    # Arquitetura
    architecture_requirements: List[ArchitectureMetric] = field(default_factory=list)
    architecture_adherence: float = 0.0  # (satisfied / total) * 100
    
    # Metadata
    iterations_to_acceptance: Optional[int] = None
    total_execution_time_seconds: float = 0.0
    
    def calculate_metrics(self):
        """Recalcula todas as métricas derivadas"""
        # Violation rate
        if self.policy_checks_executed > 0:
            self.violation_rate = (
                self.policy_checks_failed / self.policy_checks_executed
            ) * 100
        else:
            self.violation_rate = None
        
        # Acceptance rate
        if self.acceptance_criteria_total > 0:
            self.acceptance_rate = (self.acceptance_criteria_met / self.acceptance_criteria_total) * 100
        
        # Connectivity correctness
        if self.connectivity_tests:
            correct = sum(1 for t in self.connectivity_tests if t.is_correct)
            self.connectivity_correctness = (correct / len(self.connectivity_tests)) * 100
        
        # Architecture adherence
        if self.architecture_requirements:
            satisfied = sum(1 for r in self.architecture_requirements if r.satisfied)
            self.architecture_adherence = (satisfied / len(self.architecture_requirements)) * 100


class MetricAnalyzer:
    """Analisa relatórios de experimentos e extrai insights"""
    
    def __init__(self):
        self.scenario_metrics: Dict[str, Dict[str, NetworkScenarioMetrics]] = {}
    
    def add_scenario_metrics(
        self,
        scenario_id: str,
        condition: str,
        metrics: NetworkScenarioMetrics
    ) -> None:
        """Adiciona métricas de um cenário"""
        if scenario_id not in self.scenario_metrics:
            self.scenario_metrics[scenario_id] = {}
        
        self.scenario_metrics[scenario_id][condition] = metrics
    
    def compare_conditions(
        self,
        scenario_id: str,
        condition_1: str = "B1",
        condition_2: str = "T1"
    ) -> Dict[str, Any]:
        """Compara métricas entre duas condições de um cenário"""
        
        if scenario_id not in self.scenario_metrics:
            logger.warning(f"No metrics for scenario {scenario_id}")
            return {}
        
        metrics_1 = self.scenario_metrics[scenario_id].get(condition_1)
        metrics_2 = self.scenario_metrics[scenario_id].get(condition_2)
        
        if not metrics_1 or not metrics_2:
            logger.warning(f"Incomplete data for {scenario_id} ({condition_1} vs {condition_2})")
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
                "iterations_delta": (
                    metrics_1.iterations_to_acceptance - metrics_2.iterations_to_acceptance
                    if metrics_1.iterations_to_acceptance is not None
                    and metrics_2.iterations_to_acceptance is not None
                    else None
                ),
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
                "h3_efficiency": (
                    metrics_1.total_execution_time_seconds > metrics_2.total_execution_time_seconds
                    if metrics_1.iterations_to_acceptance is not None
                    and metrics_2.iterations_to_acceptance is not None
                    else None
                ),
            }
        }
    
    def aggregate_all_scenarios(
        self,
        condition_1: str = "B1",
        condition_2: str = "T1"
    ) -> Dict[str, Any]:
        """Agrega resultados de todos os cenários"""
        
        comparisons = []
        for scenario_id in self.scenario_metrics.keys():
            comp = self.compare_conditions(scenario_id, condition_1, condition_2)
            if comp:
                comparisons.append(comp)
        
        if not comparisons:
            return {}
        
        # Extrair deltas
        violation_deltas = [
            c["comparison"]["violation_rate_delta"]
            for c in comparisons
            if c["comparison"]["violation_rate_delta"] is not None
        ]
        acceptance_deltas = [c["comparison"]["acceptance_rate_delta"] for c in comparisons]
        connectivity_deltas = [c["comparison"]["connectivity_correctness_delta"] for c in comparisons]
        iterations_deltas = [
            c["comparison"]["iterations_delta"] for c in comparisons
            if c["comparison"]["iterations_delta"] is not None
        ]
        h3_results = [
            c["hypothesis_tests"]["h3_efficiency"] for c in comparisons
            if c["hypothesis_tests"]["h3_efficiency"] is not None
        ]
        
        # Calcular estatísticas
        return {
            "total_scenarios": len(comparisons),
            "violation_rate": {
                "mean_delta": statistics.mean(violation_deltas) if violation_deltas else None,
                "stdev": statistics.stdev(violation_deltas) if len(violation_deltas) > 1 else 0,
                "details": violation_deltas
            },
            "acceptance_rate": {
                "mean_delta": statistics.mean(acceptance_deltas),
                "stdev": statistics.stdev(acceptance_deltas) if len(acceptance_deltas) > 1 else 0,
                "details": acceptance_deltas
            },
            "connectivity_correctness": {
                "mean_delta": statistics.mean(connectivity_deltas),
                "stdev": statistics.stdev(connectivity_deltas) if len(connectivity_deltas) > 1 else 0,
                "details": connectivity_deltas
            },
            "iterations_to_acceptance": {
                "mean_reduction": statistics.mean(iterations_deltas) if iterations_deltas else None,
                "stdev": statistics.stdev(iterations_deltas) if len(iterations_deltas) > 1 else 0,
                "details": iterations_deltas
            },
            "hypothesis_support": {
                "h1_supported": (
                    sum(
                        c["hypothesis_tests"]["h1_violation_difference"]
                        for c in comparisons
                        if c["hypothesis_tests"]["h1_violation_difference"] is not None
                    )
                    / sum(
                        c["hypothesis_tests"]["h1_violation_difference"] is not None
                        for c in comparisons
                    )
                    if any(
                        c["hypothesis_tests"]["h1_violation_difference"] is not None
                        for c in comparisons
                    )
                    else None
                ),
                "h2_supported": sum(
                    c["hypothesis_tests"]["h2_acceptance_improvement"] for c in comparisons
                ) / len(comparisons),
                "h3_supported": sum(h3_results) / len(h3_results) if h3_results else None,
            }
        }
    
    def save_analysis(self, output_file: str) -> None:
        """Salva análise em JSON"""
        analysis = self.aggregate_all_scenarios()
        
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        
        logger.info(f"Analysis saved to {output_file}")


if __name__ == "__main__":
    # Exemplo de uso
    analyzer = MetricAnalyzer()
    
    # Criar métricas de exemplo
    metrics_b1 = NetworkScenarioMetrics(
        scenario_id="NET-01",
        condition="B1",
        security_violations_count=3,
        policy_violations_count=2,
        total_violations=5,
        policy_checks_executed=10,
        policy_checks_failed=5,
        acceptance_criteria_total=10,
        acceptance_criteria_met=5,
    )
    metrics_b1.calculate_metrics()
    
    metrics_t1 = NetworkScenarioMetrics(
        scenario_id="NET-01",
        condition="T1",
        security_violations_count=1,
        policy_violations_count=0,
        total_violations=1,
        policy_checks_executed=10,
        policy_checks_failed=1,
        acceptance_criteria_total=10,
        acceptance_criteria_met=9,
    )
    metrics_t1.calculate_metrics()
    
    analyzer.add_scenario_metrics("NET-01", "B1", metrics_b1)
    analyzer.add_scenario_metrics("NET-01", "T1", metrics_t1)
    
    # Análise
    comparison = analyzer.compare_conditions("NET-01")
    print(json.dumps(comparison, indent=2))
    
    analyzer.save_analysis("evaluation/analysis.json")
