from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controlled network IaC study (Azure/Bicep and static multi-cloud Terraform; planning by default)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to an experiment configuration YAML file.",
    )
    parser.add_argument("--workspace", type=Path, help="Workspace containing scenarios/specs.")
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--execute", action="store_true", help="Explicitly permit paid model calls.")
    parser.add_argument("--ui", action="store_true", help="Open the integrated static-study dashboard and execution controls.")
    parser.add_argument("--resume", type=Path, help="Resume a managed static run directory, preserving completed paired trials.")
    parser.add_argument("--full-rerun", action="store_true", help="With --resume, copy its parameters into a new execution instead.")
    parser.add_argument("--login", action="store_true", help="Permit Copilot browser sign-in if cached credentials are unavailable (automatic in an interactive terminal).")
    parser.add_argument("--allow-azure", action="store_true", help="Additionally permit the configured Azure deployment and runtime stages.")
    parser.add_argument("--validate-catalog", action="store_true", help="Validate the selected legacy or multi-cloud scenario catalog without paid operations.")
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

    if args.full_rerun and not args.resume:
        parser.error("--full-rerun requires --resume")
    if args.resume and not args.full_rerun and (args.config or args.scenarios or args.output_dir):
        parser.error("Resume cannot override config, scenarios or output directory; use --full-rerun.")
    if args.ui:
        if args.dry_run or args.validate_catalog or args.list_scenarios or args.allow_azure:
            parser.error("--ui cannot combine with --dry-run, --validate-catalog, --list-scenarios or --allow-azure.")
        if args.output_dir:
            parser.error("UI executions are saved under results/ui-runs; --output-dir is not supported with --ui.")
        if args.execute and not (args.config or args.resume):
            parser.error("--ui --execute requires --config or --resume.")
        if args.login and not args.execute:
            parser.error("--login requires --execute; the Run tab has a separate sign-in option.")
        from network_simulation.ui import launch_ui
        try:
            parameters = {"operation": "new", "login": args.login}
            if args.resume:
                source = (base_dir / args.resume).resolve()
                parameters.update(
                    operation="full-rerun" if args.full_rerun else "resume",
                    source_run=source.relative_to(base_dir / "results").as_posix(),
                )
            elif args.config:
                parameters["config"] = (base_dir / args.config).resolve().relative_to(base_dir).as_posix()
            if args.scenarios:
                parameters["scenarios"] = args.scenarios
            return launch_ui(base_dir, parameters=parameters, execute=args.execute)
        except (OSError, ValueError) as error:
            print(f"Dashboard failed: {error}", file=sys.stderr)
            return 2

    if args.list_scenarios:
        return list_scenarios(base_dir)

    if args.config is None and not args.validate_catalog and not args.resume:
        parser.error("--config is required unless --resume or a catalog/list operation is used")

    if args.dry_run and args.execute:
        parser.error("--dry-run and --execute cannot be combined")
    if args.login and not args.execute:
        parser.error("--login requires --execute; use python -m network_simulation.copilot_client --login for sign-in without generation.")
    from network_simulation.configuration import LLMConfig, POCConfig
    from network_simulation.study import ControlledStudyRunner

    try:
        config_path = args.config
        if config_path is not None and not config_path.is_absolute():
            config_path = base_dir / config_path
        source = (base_dir / args.resume).resolve() if args.resume else None
        source_scenarios = None
        if source:
            from network_simulation.ui_worker import load_run_config
            config, source_scenarios = load_run_config(source)
            if config_path:
                config = POCConfig.load_yaml(str(config_path))
        else:
            config = POCConfig.load_yaml(str(config_path)) if config_path else POCConfig()
        if args.login and config.llm.provider != "copilot":
            parser.error("--login is only supported by the Copilot provider.")
        if args.output_dir:
            config.experiment.output_directory = str(args.output_dir)
        if config.cloud.enabled and args.execute and not args.allow_azure:
            parser.error("cloud.enabled requires --allow-azure as well as --execute")
        scenarios = args.scenarios or source_scenarios or (
            config.experiment.pilot_scenarios
            if config.experiment.experiment_phase == "pilot"
            else config.experiment.main_scenarios
        )
        if args.validate_catalog:
            if args.config is None and not args.scenarios:
                scenarios = [path.stem for path in sorted((base_dir / "scenarios" / "specs").glob("NET-*.yml"))]
        if args.execute and config.llm.provider == "azure_responses":
            credentials = LLMConfig.from_env()
            config.llm.azure_endpoint = config.llm.azure_endpoint or credentials.azure_endpoint
            config.llm.azure_api_key = config.llm.azure_api_key or credentials.azure_api_key
            config.llm.azure_tenant_id = config.llm.azure_tenant_id or credentials.azure_tenant_id
            config.llm.azure_subscription_id = config.llm.azure_subscription_id or credentials.azure_subscription_id
        runner = ControlledStudyRunner(workspace_dir=base_dir, config=config)
        if not args.execute:
            plan = runner.plan(scenarios)
            if args.validate_catalog:
                print(json.dumps({
                    "status": "valid", "scenarios": list(plan["scenarios"]),
                    "specifications": plan["requested_scenarios"],
                    "skipped_variants": plan["skipped_variants"],
                    "execution_blockers": plan["execution_blockers"],
                    "paid_execution": False,
                }, indent=2))
            else:
                print(json.dumps(plan, indent=2))
            return 0
        if args.validate_catalog:
            parser.error("--validate-catalog cannot be combined with --execute")
        recovery = (
            {"rerun_of": str(source)} if args.full_rerun
            else {"resume_from": source}
        ) if source else {}
        result = runner.run(
            scenarios, allow_browser_auth=args.login or sys.stdin.isatty(), **recovery
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"Study configuration failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": result["status"], "output_directory": result["output_directory"],
        "physical_model_calls": result.get("physical_model_calls", 0),
        "generation_requests": result.get("generation_requests", result.get("physical_model_calls", 0)),
        "retained_resource_groups": result.get("retained_resource_groups", []),
    }, indent=2))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
