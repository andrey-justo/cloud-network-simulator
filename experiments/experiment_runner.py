"""
Framework de experimentos controlados: B1 vs T1
Compara geração via IA sem validação (B1) vs com validação iterativa (T1)
"""

import json
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any
from enum import Enum
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConditionType(str, Enum):
    """Tipo de condição experimental"""
    B1 = "B1"  # AI sem validação
    T1 = "T1"  # AI com validação iterativa
    B0 = "B0"  # Baseline manual (referência)


@dataclass
class IterationResult:
    """Resultado de uma iteração (B1 ou T1)"""
    iteration_num: int
    condition: ConditionType
    template_content: str
    template_path: str
    validation_passed: bool = False
    security_violations: int = 0
    policy_violations: int = 0
    checkov_score: float = 0.0
    llm_model: Optional[str] = None
    prompt_used: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    execution_time_seconds: float = 0.0
    
    @property
    def total_violations(self) -> int:
        return self.security_violations + self.policy_violations


@dataclass
class ScenarioExperimentResult:
    """Resultado de um experimento completo para um cenário"""
    scenario_id: str
    scenario_name: str
    
    # Condições
    b1_iterations: List[IterationResult] = field(default_factory=list)
    t1_iterations: List[IterationResult] = field(default_factory=list)
    b0_template: Optional[IterationResult] = None  # Baseline de referência
    
    # Métricas agregadas
    b1_acceptance_rate: float = 0.0  # Taxa de configs aceitas sem validação
    t1_acceptance_rate: float = 0.0  # Taxa de configs aceitas com validação
    
    b1_avg_iterations: float = 0.0   # Média de iterações para B1 chegar a aceito
    t1_avg_iterations: float = 0.0   # Média de iterações para T1 chegar a aceito
    
    b1_avg_violations: float = 0.0   # Média de violações em B1
    t1_avg_violations: float = 0.0   # Média de violações em T1
    
    b1_total_time: float = 0.0       # Tempo total B1 (segundos)
    t1_total_time: float = 0.0       # Tempo total T1 (segundos)
    
    # Metadata
    experiment_date: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""
    
    def calculate_metrics(self):
        """Calcula métricas agregadas"""
        if self.b1_iterations:
            accepted_b1 = sum(1 for it in self.b1_iterations if it.validation_passed)
            self.b1_acceptance_rate = (accepted_b1 / len(self.b1_iterations)) * 100
            self.b1_avg_iterations = len(self.b1_iterations) / max(accepted_b1, 1)
            self.b1_avg_violations = sum(
                it.total_violations for it in self.b1_iterations
            ) / len(self.b1_iterations)
            self.b1_total_time = sum(it.execution_time_seconds for it in self.b1_iterations)
        
        if self.t1_iterations:
            accepted_t1 = sum(1 for it in self.t1_iterations if it.validation_passed)
            self.t1_acceptance_rate = (accepted_t1 / len(self.t1_iterations)) * 100
            self.t1_avg_iterations = len(self.t1_iterations) / max(accepted_t1, 1)
            self.t1_avg_violations = sum(
                it.total_violations for it in self.t1_iterations
            ) / len(self.t1_iterations)
            self.t1_total_time = sum(it.execution_time_seconds for it in self.t1_iterations)
    
    @property
    def improvement_acceptance_rate(self) -> float:
        """Melhoria em taxa de aceitação: T1 - B1 (percentage points)"""
        return self.t1_acceptance_rate - self.b1_acceptance_rate
    
    @property
    def improvement_iterations(self) -> float:
        """Melhoria em iterações: B1 - T1 (menos iterações é melhor)"""
        return self.b1_avg_iterations - self.t1_avg_iterations
    
    @property
    def improvement_violations(self) -> float:
        """Melhoria em violações: B1 - T1 (menos violações é melhor)"""
        return self.b1_avg_violations - self.t1_avg_violations


@dataclass
class ExperimentRunMetadata:
    """Metadata de uma execução completa"""
    experiment_id: str
    experiment_phase: str = "pilot"  # "pilot" ou "main"
    run_date: datetime = field(default_factory=datetime.utcnow)
    llm_provider: Optional[str] = None  # "openai", "anthropic", "azure"
    llm_model: Optional[str] = None
    validator_version: str = "checkov-3.2.0"
    scenarios_tested: List[str] = field(default_factory=list)
    notes: str = ""


class ExperimentRunner:
    """Orquestrador de experimentos B1 vs T1"""
    
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: Dict[str, ScenarioExperimentResult] = {}
        self.metadata = ExperimentRunMetadata(
            experiment_id=self._generate_experiment_id()
        )
    
    @staticmethod
    def _generate_experiment_id() -> str:
        """Gera ID único para experimento"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"experiment_{timestamp}"
    
    def add_scenario_result(
        self,
        scenario_result: ScenarioExperimentResult
    ) -> None:
        """Adiciona resultado de um cenário"""
        scenario_result.calculate_metrics()
        self.results[scenario_result.scenario_id] = scenario_result
        logger.info(
            f"Added {scenario_result.scenario_id}: "
            f"B1={scenario_result.b1_acceptance_rate:.1f}%, "
            f"T1={scenario_result.t1_acceptance_rate:.1f}%, "
            f"Δ={scenario_result.improvement_acceptance_rate:+.1f}pp"
        )
    
    def save_report(self, filename: Optional[str] = None) -> Path:
        """Salva relatório completo em JSON"""
        if filename is None:
            filename = f"{self.metadata.experiment_id}.json"
        
        output_file = self.output_dir / filename
        
        report = {
            "metadata": asdict(self.metadata),
            "results": {
                scenario_id: asdict(result)
                for scenario_id, result in self.results.items()
            },
            "summary": self._compute_summary()
        }
        
        # Converter datetime para string
        report_str = json.dumps(
            report,
            indent=2,
            default=self._json_serialize
        )
        
        with open(output_file, 'w') as f:
            f.write(report_str)
        
        logger.info(f"Report saved to {output_file}")
        return output_file
    
    def _compute_summary(self) -> Dict[str, Any]:
        """Computa resumo agregado de todos os cenários"""
        if not self.results:
            return {}
        
        b1_acceptance_rates = [
            r.b1_acceptance_rate for r in self.results.values()
        ]
        t1_acceptance_rates = [
            r.t1_acceptance_rate for r in self.results.values()
        ]
        improvements = [
            r.improvement_acceptance_rate for r in self.results.values()
        ]
        
        return {
            "total_scenarios": len(self.results),
            "avg_b1_acceptance_rate": sum(b1_acceptance_rates) / len(b1_acceptance_rates),
            "avg_t1_acceptance_rate": sum(t1_acceptance_rates) / len(t1_acceptance_rates),
            "avg_improvement_pp": sum(improvements) / len(improvements),
            "hypothesis_h1_supported": self._test_h1(),  # B1 tem mais violações
            "hypothesis_h2_supported": self._test_h2(),  # T1 tem mais aceitação
            "hypothesis_h3_supported": self._test_h3(),  # T1 usa menos tempo
        }
    
    def _test_h1(self) -> bool:
        """H1: B1 tem mais violações que T1"""
        b1_violations = [
            r.b1_avg_violations for r in self.results.values()
        ]
        t1_violations = [
            r.t1_avg_violations for r in self.results.values()
        ]
        
        avg_b1 = sum(b1_violations) / len(b1_violations) if b1_violations else 0
        avg_t1 = sum(t1_violations) / len(t1_violations) if t1_violations else 0
        
        return avg_b1 > avg_t1
    
    def _test_h2(self) -> bool:
        """H2: T1 tem taxa de aceitação maior"""
        improvements = [
            r.improvement_acceptance_rate for r in self.results.values()
        ]
        avg_improvement = sum(improvements) / len(improvements) if improvements else 0
        
        return avg_improvement > 0
    
    def _test_h3(self) -> bool:
        """H3: T1 usa menos tempo total (IA + validação < IA iterativo)"""
        # Simplificação: assumir T1 convergiu mais rápido
        improvements = [
            r.t1_avg_iterations < r.b1_avg_iterations 
            for r in self.results.values()
        ]
        return sum(improvements) / len(improvements) > 0.5 if improvements else False
    
    @staticmethod
    def _json_serialize(obj):
        """Helper para serializar objetos complexos"""
        if isinstance(obj, (datetime, Path)):
            return str(obj)
        if isinstance(obj, ConditionType):
            return obj.value
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


if __name__ == "__main__":
    # Exemplo de uso
    runner = ExperimentRunner(output_dir="reports")
    runner.metadata.experiment_phase = "pilot"
    runner.metadata.llm_model = "gpt-4-turbo"
    runner.metadata.scenarios_tested = ["NET-01", "NET-02"]
    
    # Criar resultado exemplo
    result = ScenarioExperimentResult(
        scenario_id="NET-01",
        scenario_name="Basic Virtual Network"
    )
    
    # Simular iterações B1
    result.b1_iterations = [
        IterationResult(
            iteration_num=1,
            condition=ConditionType.B1,
            template_content="dummy",
            template_path="/path/to/net-01.bicep",
            validation_passed=False,
            security_violations=2,
            policy_violations=1,
        )
    ]
    
    # Simular iterações T1
    result.t1_iterations = [
        IterationResult(
            iteration_num=1,
            condition=ConditionType.T1,
            template_content="dummy",
            template_path="/path/to/net-01.bicep",
            validation_passed=True,
            security_violations=0,
            policy_violations=0,
        )
    ]
    
    runner.add_scenario_result(result)
    runner.save_report()
