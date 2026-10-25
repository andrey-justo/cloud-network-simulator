"""
Orquestrador principal: POC de experimento B1 vs T1 para IaC de rede Azure
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

from validation.checkov_validator import CheckovValidator, validate_all_scenarios
from experiments.experiment_runner import ExperimentRunner, ScenarioExperimentResult, IterationResult, ConditionType
from network_simulation.metrics import MetricAnalyzer, NetworkScenarioMetrics, ConnectivityMetric
from network_simulation.configuration import LLMConfig, POCConfig
from network_simulation.live_experiment import LiveExperimentRunner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NetworkSimulationPOC:
    """Orquestrador da POC de simulação de rede"""
    
    def __init__(
        self,
        workspace_dir: str = ".",
        output_directory: str | None = None,
    ):
        self.workspace = Path(workspace_dir)
        self.templates_dir = self.workspace / "templates" / "bicep"
        self.reports_dir = Path(output_directory or "reports")
        if not self.reports_dir.is_absolute():
            self.reports_dir = self.workspace / self.reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)
    
    def stage_1_validate_baseline_templates(self) -> dict:
        """Stage 1: Validar templates base (B0 - Baseline Manual)"""
        logger.info("=" * 60)
        logger.info("STAGE 1: Validar Templates Base (B0)")
        logger.info("=" * 60)
        
        validator = CheckovValidator(framework="bicep")
        reports = {}
        
        for bicep_file in sorted(self.templates_dir.glob("net-*.bicep")):
            scenario_id = bicep_file.stem.upper()
            logger.info(f"\nValidando {scenario_id}...")
            
            try:
                report = validator.validate_template(
                    str(bicep_file),
                    scenario_id=scenario_id
                )
                reports[scenario_id] = report
                
                logger.info(
                    f"  ✓ {scenario_id}: "
                    f"{report.passed}/{report.total_checks} checks passed, "
                    f"{report.violation_count} violations"
                )
            except Exception as e:
                logger.error(f"  ✗ {scenario_id} failed: {e}")
        
        # Salvar relatório
        summary_file = self.reports_dir / "stage1_baseline_validation.json"
        summary = {
            scenario_id: {
                "total_checks": report.total_checks,
                "passed": report.passed,
                "failed": report.failed,
                "acceptance_rate": report.acceptance_rate,
                "security_violations": len(report.security_violations),
                "policy_violations": len(report.policy_violations),
            }
            for scenario_id, report in reports.items()
        }
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"\n✓ Stage 1 completo. Relatório salvo em {summary_file}")
        return summary
    
    def stage_2_simulate_experiment(self) -> dict:
        """Stage 2: Simular experimento B1 vs T1"""
        logger.info("=" * 60)
        logger.info("STAGE 2: Simular Experimento B1 vs T1")
        logger.info("=" * 60)
        
        runner = ExperimentRunner(output_dir=str(self.reports_dir))
        runner.metadata.experiment_phase = "pilot"
        runner.metadata.llm_model = "simulated"
        runner.metadata.scenarios_tested = ["NET-01", "NET-02", "NET-03"]
        
        # Simular resultados para cenários
        scenarios_data = {
            "NET-01": {
                "name": "Basic Virtual Network",
                "b1_violations": [3, 2, 1],      # Iterações B1: 3, 2, 1 violações (convergiu)
                "t1_violations": [1],             # Iterações T1: 1 violação (converge mais rápido)
            },
            "NET-02": {
                "name": "Network Segmentation",
                "b1_violations": [4, 3, 2, 1],   # B1: 4 iterações
                "t1_violations": [2, 1],         # T1: 2 iterações
            },
            "NET-03": {
                "name": "Secure Network with NSGs",
                "b1_violations": [5, 4, 3, 2, 1], # B1: 5 iterações
                "t1_violations": [2],             # T1: 1 iteração (feedback validação ajuda)
            }
        }
        
        for scenario_id, data in scenarios_data.items():
            logger.info(f"\nCenário {scenario_id}: {data['name']}")
            
            result = ScenarioExperimentResult(
                scenario_id=scenario_id,
                scenario_name=data['name']
            )
            
            # Simular iterações B1
            for i, violations in enumerate(data['b1_violations'], 1):
                iteration = IterationResult(
                    iteration_num=i,
                    condition=ConditionType.B1,
                    template_content="dummy_bicep_content",
                    template_path=f"templates/bicep/{scenario_id.lower()}.bicep",
                    validation_passed=(violations == 0),
                    security_violations=max(0, violations - 1),
                    policy_violations=max(0, violations // 2),
                    checkov_score=(100 - violations * 10),
                    execution_time_seconds=5.0 + i * 2,
                )
                result.b1_iterations.append(iteration)
            
            # Simular iterações T1
            for i, violations in enumerate(data['t1_violations'], 1):
                iteration = IterationResult(
                    iteration_num=i,
                    condition=ConditionType.T1,
                    template_content="optimized_bicep_content",
                    template_path=f"templates/bicep/{scenario_id.lower()}.bicep",
                    validation_passed=(violations == 0),
                    security_violations=max(0, violations - 1),
                    policy_violations=max(0, violations // 2),
                    checkov_score=(100 - violations * 10),
                    execution_time_seconds=3.0 + i * 1.5,
                )
                result.t1_iterations.append(iteration)
            
            runner.add_scenario_result(result)
            
            logger.info(f"  B1: {len(data['b1_violations'])} iterações, "
                       f"avg violations: {sum(data['b1_violations'])/len(data['b1_violations']):.1f}")
            logger.info(f"  T1: {len(data['t1_violations'])} iterações, "
                       f"avg violations: {sum(data['t1_violations'])/len(data['t1_violations']):.1f}")
        
        # Salvar relatório de experimento
        experiment_file = runner.save_report()
        logger.info(f"\n✓ Stage 2 completo. Relatório salvo em {experiment_file}")
        
        return runner.results
    
    def stage_3_analyze_results(self, experiment_results: dict) -> dict:
        """Stage 3: Analisar resultados e testar hipóteses"""
        logger.info("=" * 60)
        logger.info("STAGE 3: Analisar Resultados")
        logger.info("=" * 60)
        
        analyzer = MetricAnalyzer()
        
        # Criar métricas agregadas para cada cenário
        for scenario_id, exp_result in experiment_results.items():
            logger.info(f"\nAnalisando {scenario_id}...")
            
            # Métricas B1
            b1_violations = [
                it.total_violations for it in exp_result.b1_iterations
            ]
            b1_avg = sum(b1_violations) / len(b1_violations) if b1_violations else 0
            
            metrics_b1 = NetworkScenarioMetrics(
                scenario_id=scenario_id,
                condition="B1",
                total_violations=int(sum(b1_violations)),
                policy_checks_executed=10 * len(exp_result.b1_iterations),
                policy_checks_failed=int(sum(b1_violations)),
                acceptance_criteria_total=10,
                acceptance_criteria_met=len([it for it in exp_result.b1_iterations if it.validation_passed]),
                iterations_to_acceptance=len(exp_result.b1_iterations),
                total_execution_time_seconds=exp_result.b1_total_time,
            )
            metrics_b1.calculate_metrics()
            
            # Métricas T1
            t1_violations = [
                it.total_violations for it in exp_result.t1_iterations
            ]
            t1_avg = sum(t1_violations) / len(t1_violations) if t1_violations else 0
            
            metrics_t1 = NetworkScenarioMetrics(
                scenario_id=scenario_id,
                condition="T1",
                total_violations=int(sum(t1_violations)),
                policy_checks_executed=10 * len(exp_result.t1_iterations),
                policy_checks_failed=int(sum(t1_violations)),
                acceptance_criteria_total=10,
                acceptance_criteria_met=len([it for it in exp_result.t1_iterations if it.validation_passed]),
                iterations_to_acceptance=len(exp_result.t1_iterations),
                total_execution_time_seconds=exp_result.t1_total_time,
            )
            metrics_t1.calculate_metrics()
            
            analyzer.add_scenario_metrics(scenario_id, "B1", metrics_b1)
            analyzer.add_scenario_metrics(scenario_id, "T1", metrics_t1)
            
            improvement = metrics_b1.violation_rate - metrics_t1.violation_rate
            logger.info(f"  B1 avg violations: {b1_avg:.1f}")
            logger.info(f"  T1 avg violations: {t1_avg:.1f}")
            logger.info(f"  Melhoria: {improvement:+.1f}pp")
        
        # Análise agregada
        aggregated = analyzer.aggregate_all_scenarios()
        
        logger.info("\n" + "=" * 60)
        logger.info("HIPÓTESES TESTADAS")
        logger.info("=" * 60)
        logger.info(f"H1 (B1 > T1 violações): {aggregated['hypothesis_support']['h1_supported']*100:.0f}% de suporte")
        logger.info(f"H2 (T1 melhor aceitação): {aggregated['hypothesis_support']['h2_supported']*100:.0f}% de suporte")
        logger.info(f"H3 (T1 mais eficiente): {aggregated['hypothesis_support']['h3_supported']*100:.0f}% de suporte")
        
        logger.info(f"\nMelhoria média em violation rate: {aggregated['violation_rate']['mean_delta']:+.1f}pp")
        logger.info(f"Melhoria média em acceptance rate: {aggregated['acceptance_rate']['mean_delta']:+.1f}pp")
        logger.info(f"Redução média de iterações: {aggregated['iterations_to_acceptance']['mean_reduction']:+.1f}")
        
        # Salvar análise
        analysis_file = self.reports_dir / "stage3_analysis.json"
        with open(analysis_file, 'w') as f:
            json.dump(aggregated, f, indent=2, default=str)
        
        logger.info(f"\n✓ Stage 3 completo. Análise salva em {analysis_file}")
        return aggregated
    
    def run_poc(self):
        """Executa POC completa: Stages 1, 2, 3"""
        logger.info("\n" + "=" * 60)
        logger.info("PROOF OF CONCEPT: IA-Assisted IaC for Azure Network")
        logger.info("=" * 60 + "\n")
        
        try:
            # Stage 1: Validar templates base
            baseline_validation = self.stage_1_validate_baseline_templates()
            
            # Stage 2: Simular experimento
            experiment_results = self.stage_2_simulate_experiment()
            
            # Stage 3: Analisar resultados
            analysis = self.stage_3_analyze_results(experiment_results)
            
            # Resumo final
            logger.info("\n" + "=" * 60)
            logger.info("RESUMO DA POC")
            logger.info("=" * 60)
            logger.info(f"\n✓ Cenários analisados: {analysis['total_scenarios']}")
            logger.info(f"✓ Validação baseline (B0): {len(baseline_validation)} templates")
            logger.info(f"✓ Experimentos (B1 vs T1): 3 cenários de pilot")
            logger.info(f"\nResultados:")
            logger.info(f"  - Melhoria acceptance rate: {analysis['acceptance_rate']['mean_delta']:+.1f}pp")
            logger.info(f"  - Redução de violações: {abs(analysis['violation_rate']['mean_delta']):+.1f}pp")
            logger.info(f"  - Menos iterações: {analysis['iterations_to_acceptance']['mean_reduction']:+.1f}")
            logger.info(f"\nRelatórios salvos em: {self.reports_dir}")
            
        except Exception as e:
            logger.error(f"POC falhou: {e}", exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Azure network IaC experiment runner")
    parser.add_argument(
        "--mode",
        choices=("simulated", "live"),
        default="simulated",
        help="Run the historical synthetic pilot or a live model experiment.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help="Scenario ID to run; may be repeated. Defaults to the configured pilot set.",
    )
    parser.add_argument(
        "--output-dir",
        help="Root folder for reports and traceable run artifacts.",
    )
    parser.add_argument(
        "--disable-opa",
        action="store_true",
        help="Explicitly exclude OPA from the live validation protocol.",
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent

    if args.mode == "live":
        config = POCConfig()
        config.llm = LLMConfig.from_env()
        if args.disable_opa:
            config.validation.run_opa_policies = False
        if args.output_dir:
            config.experiment.output_directory = args.output_dir
        scenarios = args.scenarios or config.experiment.pilot_scenarios
        result = LiveExperimentRunner(
            workspace_dir=project_root,
            config=config,
            output_directory=args.output_dir,
        ).run(scenarios)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] == "completed_with_scenario_acceptance" else 2)

    poc = NetworkSimulationPOC(
        workspace_dir=str(project_root),
        output_directory=args.output_dir,
    )
    poc.run_poc()
