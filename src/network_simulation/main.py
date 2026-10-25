from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controlled Azure network IaC study (planning by default)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to an experiment configuration YAML file.",
    )
    parser.add_argument("--workspace", type=Path, help="Workspace containing scenarios/specs.")
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--execute", action="store_true", help="Explicitly permit paid model calls.")
    parser.add_argument("--allow-azure", action="store_true", help="Additionally permit the configured Azure deployment and runtime stages.")
    parser.add_argument("--validate-catalog", action="store_true", help="Validate all ten scenario definitions and study contracts without paid operations.")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List scenarios available in the scenarios directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the loaded experiment configuration without executing it.",
    )
    return parser


def list_scenarios(base_dir: Path) -> int:
    scenarios_dir = base_dir / "scenarios" / "specs"
    for scenario_file in sorted(scenarios_dir.glob("NET-*.yml")):
        print(scenario_file.relative_to(base_dir))
    return 0


def load_yaml(file_path: Path) -> dict:
    with file_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    base_dir = (args.workspace or Path.cwd()).resolve()

    if args.list_scenarios:
        return list_scenarios(base_dir)

    if args.config is None and not args.validate_catalog:
        parser.error("--config is required unless --list-scenarios is used")

    if args.dry_run and args.execute:
        parser.error("--dry-run and --execute cannot be combined")
    from network_simulation.configuration import LLMConfig, POCConfig
    from network_simulation.study import ControlledStudyRunner

    try:
        config_path = args.config
        if config_path is not None and not config_path.is_absolute():
            config_path = base_dir / config_path
        config = POCConfig.load_yaml(str(config_path)) if config_path else POCConfig()
        if args.output_dir:
            config.experiment.output_directory = str(args.output_dir)
        if config.cloud.enabled and args.execute and not args.allow_azure:
            parser.error("cloud.enabled requires --allow-azure as well as --execute")
        scenarios = args.scenarios or (
            config.experiment.pilot_scenarios
            if config.experiment.experiment_phase == "pilot"
            else config.experiment.main_scenarios
        )
        if args.validate_catalog:
            scenarios = [f"NET-{number:02}" for number in range(1, 11)]
        if args.execute:
            credentials = LLMConfig.from_env()
            config.llm.azure_endpoint = config.llm.azure_endpoint or credentials.azure_endpoint
            config.llm.azure_api_key = config.llm.azure_api_key or credentials.azure_api_key
        runner = ControlledStudyRunner(workspace_dir=base_dir, config=config)
        if not args.execute:
            plan = runner.plan(scenarios)
            if args.validate_catalog:
                print(json.dumps({"status": "valid", "scenarios": list(plan["scenarios"]), "paid_execution": False}, indent=2))
            else:
                print(json.dumps(plan, indent=2))
            return 0
        if args.validate_catalog:
            parser.error("--validate-catalog cannot be combined with --execute")
        result = runner.run(scenarios)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"Study configuration failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": result["status"], "output_directory": result["output_directory"],
        "physical_model_calls": result.get("physical_model_calls", 0),
        "retained_resource_groups": result.get("retained_resource_groups", []),
    }, indent=2))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
