from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from types import UnionType
from typing import Any, get_args, get_origin, get_type_hints

import yaml

from .experiment import ExperimentConfig
from .llm import LLMConfig
from .prompts import PromptConfig
from .validation import ValidationConfig
from .study import StudyConfig
from network_simulation.study_cloud import CloudStudyConfig


def _matches_type(value: Any, expected: Any) -> bool:
    origin = get_origin(expected)
    if origin is UnionType:
        return any(_matches_type(value, item) for item in get_args(expected))
    if origin is list:
        return isinstance(value, list) and all(
            _matches_type(item, get_args(expected)[0]) for item in value
        )
    if origin is dict:
        key_type, value_type = get_args(expected)
        return isinstance(value, dict) and all(
            _matches_type(key, key_type) and _matches_type(item, value_type)
            for key, item in value.items()
        )
    if expected is float:
        return type(value) in (int, float)
    return type(value) is expected


def _apply_section(section: Any, raw: Any, aliases: dict[str, str]) -> None:
    if not isinstance(raw, dict):
        raise ValueError(f"{type(section).__name__} must be a YAML object.")
    hints = get_type_hints(type(section))
    for key, value in raw.items():
        name = aliases.get(key, key)
        if name not in hints:
            raise ValueError(f"Unknown {type(section).__name__} setting: {key}")
        if not _matches_type(value, hints[name]):
            raise ValueError(f"Invalid type for {type(section).__name__}.{key}")
        setattr(section, name, value)


@dataclass
class POCConfig:
    experiment: ExperimentConfig = field(default_factory=ExperimentConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    prompts: PromptConfig = field(default_factory=PromptConfig)
    study: StudyConfig = field(default_factory=StudyConfig)
    cloud: CloudStudyConfig = field(default_factory=CloudStudyConfig)
    poc_name: str = "Network Simulation POC"
    poc_description: str = "AI-assisted IaC for Azure Network Configuration Evaluation"

    def save_yaml(self, filepath: str) -> None:
        experiment = asdict(self.experiment)
        experiment["phase"] = experiment.pop("experiment_phase")
        experiment["max_iterations_b1"] = experiment.pop("b1_max_iterations")
        experiment["max_iterations_t1"] = experiment.pop("t1_max_iterations")
        llm = asdict(self.llm)
        for name in ("azure_api_key", "openai_api_key", "anthropic_api_key"):
            llm.pop(name)
        llm["model"] = llm.pop("model_name")
        validation = asdict(self.validation)
        for key, name in {
            "checkov": "run_checkov",
            "opa": "run_opa_policies",
            "bicep_syntax": "validate_bicep_syntax",
        }.items():
            validation[key] = validation.pop(name)
        prompts = {
            item.name: getattr(self.prompts, item.name)
            for item in fields(self.prompts)
            if item.name != "template_directory"
        }
        if self.prompts.template_directory is not None:
            prompts["template_directory"] = str(self.prompts.template_directory)
        config_dict = {
            "poc": {"name": self.poc_name, "description": self.poc_description},
            "experiment": experiment,
            "llm": llm,
            "validation": validation,
            "prompts": prompts,
            "study": asdict(self.study),
            "cloud": asdict(self.cloud),
        }
        with open(filepath, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config_dict, handle, sort_keys=False)

    @classmethod
    def load_yaml(cls, filepath: str) -> "POCConfig":
        with open(filepath, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        if not isinstance(raw, dict):
            raise ValueError("POC configuration must contain a YAML object.")
        unknown = raw.keys() - {"poc", "experiment", "llm", "validation", "prompts", "study", "cloud"}
        if unknown:
            raise ValueError(f"Unknown configuration sections: {', '.join(sorted(unknown))}")
        config = cls()
        _apply_section(config, raw.get("poc", {}), {"name": "poc_name", "description": "poc_description"})
        experiment = raw.get("experiment", {})
        if not isinstance(experiment, dict):
            raise ValueError("Experiment configuration must be a YAML object.")
        experiment = dict(experiment)
        scenarios = experiment.pop("scenarios", None)
        _apply_section(config.experiment, experiment, {
            "phase": "experiment_phase",
            "max_iterations_b1": "b1_max_iterations",
            "max_iterations_t1": "t1_max_iterations",
        })
        if config.experiment.experiment_phase not in ("pilot", "main"):
            raise ValueError("Experiment phase must be pilot or main.")
        if scenarios is not None:
            name = "pilot_scenarios" if config.experiment.experiment_phase == "pilot" else "main_scenarios"
            _apply_section(config.experiment, {name: scenarios}, {})
        if min(config.experiment.b1_max_iterations, config.experiment.t1_max_iterations) < 1:
            raise ValueError("Iteration limits must be positive.")
        _apply_section(config.llm, raw.get("llm", {}), {"model": "model_name"})
        _apply_section(config.validation, raw.get("validation", {}), {
            "checkov": "run_checkov",
            "opa": "run_opa_policies",
            "bicep_syntax": "validate_bicep_syntax",
        })
        prompts = raw.get("prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError("Prompt configuration must be a YAML object.")
        prompts = dict(prompts)
        directory = prompts.pop("template_directory", None)
        if directory is not None:
            if not isinstance(directory, str):
                raise ValueError("Prompt template_directory must be a path string.")
            path = Path(directory)
            if not path.is_absolute():
                path = Path(filepath).resolve().parent / path
            config.prompts = PromptConfig(template_directory=path)
        _apply_section(config.prompts, prompts, {})
        _apply_section(config.study, raw.get("study", {}), {})
        config.study.validate()
        _apply_section(config.cloud, raw.get("cloud", {}), {})
        for name in ("parameters_file", "runtime_bindings_file"):
            value = getattr(config.cloud, name)
            if value is not None:
                path = Path(value)
                if not path.is_absolute():
                    path = Path(filepath).resolve().parent / path
                setattr(config.cloud, name, str(path.resolve()))
        return config