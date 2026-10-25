from dataclasses import dataclass


@dataclass
class ValidationConfig:
    run_checkov: bool = True
    checkov_framework: str = "bicep"
    checkov_quiet_mode: bool = False
    custom_checks_dir: str | None = None
    validate_bicep_syntax: bool = True
    validate_terraform_syntax: bool = False
    run_opa_policies: bool = True
    opa_policies_dir: str = "policies/azure"
    max_security_violations: int = 0
    max_policy_violations: int = 2
    validate_connectivity: bool = True
    connectivity_policy_file: str = "policies/azure/network.rego"