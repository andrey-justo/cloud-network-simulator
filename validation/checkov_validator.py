"""
Validação de templates Bicep/Terraform usando Checkov
Integra verificações de segurança, compliance e best practices
"""

import contextlib
import importlib.metadata
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CheckovResult:
    """Resultado de uma verificação Checkov"""
    check_id: str
    check_name: str
    resource: str
    result: str  # "passed" | "failed" | "skipped"
    file_path: str
    file_line: Optional[int] = None
    description: Optional[str] = None


@dataclass
class ValidationReport:
    """Relatório de validação completo"""
    template_path: str
    scenario_id: str
    total_checks: int
    passed: int
    failed: int
    skipped: int
    results: List[CheckovResult]
    security_violations: List[CheckovResult]
    policy_violations: List[CheckovResult]
    parsing_errors: int = 0
    
    @property
    def acceptance_rate(self) -> float:
        """Taxa de aceitação: checks passed / total"""
        return (self.passed / self.total_checks * 100) if self.total_checks > 0 else 0
    
    @property
    def violation_count(self) -> int:
        """Total de violações"""
        return len(self.security_violations) + len(self.policy_violations)


class CheckovValidator:
    """Valida templates IaC usando Checkov"""
    
    def __init__(self, framework: str = "bicep"):
        """
        Args:
            framework: 'bicep' ou 'terraform'
        """
        self.framework = framework
        self._verify_checkov_installed()
    
    def _verify_checkov_installed(self) -> bool:
        """Verifica se Checkov está instalado"""
        executable = shutil.which("checkov")
        if executable is None:
            if importlib.util.find_spec("checkov.main") is not None:
                logger.info("Checkov CLI launcher missing; using installed Python module")
                return True
            logger.error("Checkov not found. Install with: pip install checkov")
            return False
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                check=False
            )
            logger.info(f"Checkov version: {result.stdout.strip()}")
            return True
        except FileNotFoundError:
            logger.error("Checkov not found. Install with: pip install checkov")
            return False
    
    def validate_template(
        self,
        template_path: str,
        scenario_id: str = "unknown",
        custom_checks_dir: Optional[str] = None
    ) -> ValidationReport:
        """
        Valida um template Bicep/Terraform
        
        Args:
            template_path: Caminho para o template
            scenario_id: ID do cenário (ex: NET-01)
            custom_checks_dir: Diretório com checks customizados
        
        Returns:
            ValidationReport com resultados detalhados
        """
        template_file = Path(template_path)
        if not template_file.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        logger.info(f"Validating {scenario_id}: {template_path}")
        
        # Construir comando Checkov
        cmd = [
            "-f", str(template_file),
            "--framework", self.framework,
            "--output", "json",
            "--quiet"
        ]
        
        # Adicionar checks customizados se fornecido
        if custom_checks_dir:
            cmd.extend(["--external-checks-dir", custom_checks_dir])
        
        # Executar Checkov
        try:
            executable = shutil.which("checkov")
            if executable:
                result = subprocess.run(
                    [executable, *cmd],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                stdout = result.stdout
            else:
                stdout = self._run_python_module(cmd)
            
            # Parse output JSON
            output = json.loads(stdout) if stdout else {}
            if isinstance(output, list):
                output = output[0] if output else {}
            if isinstance(output, dict) and isinstance(output.get("results"), dict):
                output = {
                    **output["results"],
                    "summary": output.get("summary", {}),
                }
            
            return self._parse_checkov_output(
                output,
                template_path,
                scenario_id
            )
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Checkov output: {e}")
            raise

    @staticmethod
    def _run_python_module(arguments: List[str]) -> str:
        from checkov.main import Checkov

        output_buffer = io.BytesIO()
        output_stream = io.TextIOWrapper(
            output_buffer,
            encoding="utf-8",
            write_through=True,
        )
        error_stream = io.StringIO()
        try:
            with contextlib.redirect_stdout(output_stream), contextlib.redirect_stderr(error_stream):
                Checkov(argv=arguments).run()
            output_stream.flush()
        except SystemExit as error:
            if error.code not in (0, None):
                logger.warning("In-process Checkov exited with code %s", error.code)
        finally:
            output_stream.flush()
        return output_buffer.getvalue().decode("utf-8", errors="replace")
    
    def _parse_checkov_output(
        self,
        output: dict,
        template_path: str,
        scenario_id: str
    ) -> ValidationReport:
        """Parse JSON output do Checkov"""
        
        all_results = []
        security_violations = []
        policy_violations = []
        
        # Processarsed checks (failed)
        for check in output.get("failed_checks", []):
            result = CheckovResult(
                check_id=check.get("check_id", "unknown"),
                check_name=check.get("check_name", "unknown"),
                resource=check.get("resource", "unknown"),
                result="failed",
                file_path=check.get("file_path", template_path),
                file_line=check.get("file_line_range", [0])[0],
                description=check.get("description")
            )
            all_results.append(result)
            
            # Classificar como security ou policy
            if self._is_security_check(check.get("check_id")):
                security_violations.append(result)
            else:
                policy_violations.append(result)
        
        # Processar passed checks
        for check in output.get("passed_checks", []):
            result = CheckovResult(
                check_id=check.get("check_id", "unknown"),
                check_name=check.get("check_name", "unknown"),
                resource=check.get("resource", "unknown"),
                result="passed",
                file_path=check.get("file_path", template_path),
                file_line=check.get("file_line_range", [0])[0]
            )
            all_results.append(result)
        
        # Processar skipped checks
        for check in output.get("skipped_checks", []):
            result = CheckovResult(
                check_id=check.get("check_id", "unknown"),
                check_name=check.get("check_name", "unknown"),
                resource=check.get("resource", "unknown"),
                result="skipped",
                file_path=check.get("file_path", template_path),
                file_line=check.get("file_line_range", [0])[0]
            )
            all_results.append(result)
        
        # Use structured summary counts when Checkov omits empty result arrays.
        summary = output.get("summary", {})
        passed = len([r for r in all_results if r.result == "passed"])
        failed = len([r for r in all_results if r.result == "failed"])
        skipped = len([r for r in all_results if r.result == "skipped"])
        passed = max(passed, int(summary.get("passed", 0) or 0))
        failed = max(failed, int(summary.get("failed", 0) or 0))
        skipped = max(skipped, int(summary.get("skipped", 0) or 0))
        total = len(all_results)
        total = max(total, passed + failed + skipped)
        
        return ValidationReport(
            template_path=template_path,
            scenario_id=scenario_id,
            total_checks=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            results=all_results,
            security_violations=security_violations,
            policy_violations=policy_violations,
            parsing_errors=int(summary.get("parsing_errors", 0) or 0),
        )
    
    @staticmethod
    def _is_security_check(check_id: str) -> bool:
        """Determina se é check de segurança (vs policy/compliance)"""
        security_keywords = [
            "CKV_AZURE_1",  # Network
            "CKV_AZURE_9",  # NSG
            "CKV_AZURE_11",  # VPN
            "CKV_AZURE_12",  # MFA
            "CKV_AZURE_37",  # Storage
        ]
        return any(keyword in check_id for keyword in security_keywords)


def validate_all_scenarios(
    templates_dir: str,
    output_file: Optional[str] = None
) -> dict:
    """Valida todos os templates em um diretório"""
    
    templates_path = Path(templates_dir)
    validator = CheckovValidator(framework="bicep")
    
    all_reports = {}
    
    for bicep_file in templates_path.glob("net-*.bicep"):
        scenario_id = bicep_file.stem.upper()
        logger.info(f"Processing {scenario_id}...")
        
        try:
            report = validator.validate_template(
                str(bicep_file),
                scenario_id=scenario_id
            )
            all_reports[scenario_id] = report
            
            logger.info(
                f"{scenario_id}: {report.passed}/{report.total_checks} passed, "
                f"{report.violation_count} violations"
            )
        
        except Exception as e:
            logger.error(f"Failed to validate {scenario_id}: {e}")
    
    # Salvar relatório consolidado
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        summary = {
            scenario_id: {
                "total_checks": report.total_checks,
                "passed": report.passed,
                "failed": report.failed,
                "acceptance_rate": report.acceptance_rate,
                "violations": report.violation_count,
                "security_violations": len(report.security_violations),
                "policy_violations": len(report.policy_violations),
            }
            for scenario_id, report in all_reports.items()
        }
        
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Report saved to {output_file}")
    
    return all_reports


if __name__ == "__main__":
    # Exemplo: validar todos os templates
    templates_dir = Path(__file__).parent.parent / "templates" / "bicep"
    
    if len(sys.argv) > 1:
        # Validar um arquivo específico
        template_file = sys.argv[1]
        scenario = sys.argv[2] if len(sys.argv) > 2 else "UNKNOWN"
        
        validator = CheckovValidator()
        report = validator.validate_template(template_file, scenario_id=scenario)
        
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        # Validar todos
        reports = validate_all_scenarios(
            str(templates_dir),
            output_file="validation/checkov/reports/summary.json"
        )
