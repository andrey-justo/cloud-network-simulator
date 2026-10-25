import sys

from .llm import LLMConfig
from .poc import POCConfig


def main() -> None:
    config = POCConfig()
    config.experiment.experiment_phase = "pilot"
    config.llm = LLMConfig.from_env()

    output_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config.save_yaml(output_file)
    print(f"Configuration saved to {output_file}")


if __name__ == "__main__":
    main()