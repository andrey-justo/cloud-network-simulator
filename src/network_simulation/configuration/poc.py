from dataclasses import dataclass, field

import yaml

from .experiment import ExperimentConfig
from .llm import LLMConfig
from .prompts import PromptConfig
from .validation import ValidationConfig


@dataclass
class POCConfig:
    experiment: ExperimentConfig = field(default_factory=ExperimentConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    prompts: PromptConfig = field(default_factory=PromptConfig)
    poc_name: str = "Network Simulation POC"
    poc_description: str = "AI-assisted IaC for Azure Network Configuration Evaluation"

    def save_yaml(self, filepath: str) -> None:
        config_dict = {
            "poc": {"name": self.poc_name, "description": self.poc_description},
            "experiment": {
                "phase": self.experiment.experiment_phase,
                "scenarios": (
                    self.experiment.pilot_scenarios
                    if self.experiment.experiment_phase == "pilot"
                    else self.experiment.main_scenarios
                ),
                "max_iterations_b1": self.experiment.b1_max_iterations,
                "max_iterations_t1": self.experiment.t1_max_iterations,
            },
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model_name,
                "available_models": self.llm.available_models,
                "azure_endpoint": self.llm.azure_endpoint,
                "temperature": self.llm.temperature,
            },
            "validation": {
                "checkov": self.validation.run_checkov,
                "opa": self.validation.run_opa_policies,
                "bicep_syntax": self.validation.validate_bicep_syntax,
            },
        }
        with open(filepath, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config_dict, handle, sort_keys=False)

    @classmethod
    def load_yaml(cls, filepath: str) -> "POCConfig":
        with open(filepath, "r", encoding="utf-8") as handle:
            yaml.safe_load(handle)
        return cls()