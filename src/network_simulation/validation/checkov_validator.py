"""
Validação de templates Bicep/Terraform usando Checkov
Integra verificações de segurança, compliance e best practices
"""

import argparse
import importlib.util
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


def is_checkov_available() -> bool:
    return bool(shutil.which("checkov") or importlib.util.find_spec("checkov"))


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
        if not is_checkov_available():
            raise RuntimeError("Checkov not found. Install with: pip install checkov")

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
            else:
                result = self._run_python_module(cmd)

            if result.returncode not in (0, 1):
                raise RuntimeError(
                    f"Checkov execution failed ({result.returncode}): {result.stderr.strip()}"
                )
            if not result.stdout.strip():
                raise ValueError(f"Checkov returned no JSON report: {result.stderr.strip()}")

            output = json.loads(result.stdout)
            outputs = output if isinstance(output, list) else [output]
            if not outputs:
                raise ValueError("Checkov returned an empty report list.")
            reports = [
                self._parse_checkov_output(item, template_path, scenario_id)
                for item in outputs
            ]
            report = ValidationReport(
                template_path=template_path,
                scenario_id=scenario_id,
                total_checks=sum(item.total_checks for item in reports),
                passed=sum(item.passed for item in reports),
                failed=sum(item.failed for item in reports),
                skipped=sum(item.skipped for item in reports),
                results=[check for item in reports for check in item.results],
                security_violations=[check for item in reports for check in item.security_violations],
                policy_violations=[check for item in reports for check in item.policy_violations],
                parsing_errors=sum(item.parsing_errors for item in reports),
            )
            if result.returncode == 1 and report.failed == 0 and report.parsing_errors == 0:
                raise RuntimeError("Checkov exited unsuccessfully without reporting any failures.")
            return report

        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Checkov validation failed for %s: %s", template_path, e)
            raise

    @staticmethod
    def _run_python_module(arguments: List[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "from checkov.main import Checkov; import sys; sys.exit(Checkov().run())",
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def _parse_checkov_output(
        self,
        output: dict,
        template_path: str,
        scenario_id: str
    ) -> ValidationReport:
        """Parse JSON output do Checkov"""
        if not isinstance(output, dict):
            raise ValueError("Checkov report must be a JSON object.")
        if "results" in output:
            if not isinstance(output["results"], dict):
                raise ValueError("Checkov results must be an object.")
            output = {**output["results"], "summary": output.get("summary", {})}
        if not any(key in output for key in ("summary", "passed_checks", "failed_checks", "skipped_checks")):
            raise ValueError("Checkov report contains neither a summary nor check results.")
        summary = output.get("summary", {})
        if not isinstance(summary, dict):
            raise ValueError("Checkov summary must be an object.")
        for key in ("passed", "failed", "skipped", "parsing_errors"):
            count = summary.get(key, 0)
            if type(count) is not int or count < 0:
                raise ValueError(f"Checkov summary {key} must be a non-negative integer.")
        for key in ("passed_checks", "failed_checks", "skipped_checks"):
            checks = output.get(key, [])
            if not isinstance(checks, list) or not all(isinstance(check, dict) for check in checks):
                raise ValueError(f"Checkov {key} must be a list of objects.")

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
                file_line=(check.get("file_line_range") or [0])[0],
                description=check.get("description")
            )
            all_results.append(result)

            # Classificar como security ou policy
            if self._is_security_check(check.get("check_id") or ""):
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
                file_line=(check.get("file_line_range") or [0])[0]
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
                file_line=(check.get("file_line_range") or [0])[0]
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an explicit experiment artifact.")
    parser.add_argument("template", type=Path, help="Path to generated Bicep or compiled ARM JSON.")
    parser.add_argument("scenario", nargs="?", default="UNKNOWN")
    parser.add_argument("--framework", choices=("bicep", "arm", "terraform"), default="bicep")
    args = parser.parse_args()
    validator = CheckovValidator(framework=args.framework)
    report = validator.validate_template(str(args.template), scenario_id=args.scenario)
    print(json.dumps(asdict(report), indent=2, default=str))


if __name__ == "__main__":
    main()
