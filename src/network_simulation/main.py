from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Network simulation experiment scaffold"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to an experiment configuration YAML file.",
    )
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
    scenarios_dir = base_dir / "scenarios"
    for scenario_file in sorted(scenarios_dir.glob("*.yaml")):
        print(scenario_file.relative_to(base_dir))
    return 0


def load_yaml(file_path: Path) -> dict:
    with file_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    base_dir = Path(__file__).resolve().parents[2]

    if args.list_scenarios:
        return list_scenarios(base_dir)

    if args.config is None:
        parser.error("--config is required unless --list-scenarios is used")

    config_path = args.config
    if not config_path.is_absolute():
        config_path = base_dir / config_path

    config = load_yaml(config_path)

    if args.dry_run:
        print(yaml.safe_dump(config, sort_keys=False))
        return 0

    print("Execution backend not implemented yet.")
    print("Loaded configuration:")
    print(yaml.safe_dump(config, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
