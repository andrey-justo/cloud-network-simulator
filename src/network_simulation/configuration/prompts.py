from dataclasses import dataclass, field
from pathlib import Path
from importlib.resources import files


@dataclass
class PromptConfig:
    template_directory: Path | None = None
    system_prompt_b1: str = field(init=False)
    system_prompt_t1: str = field(init=False)
    system_prompt_iterative: str = field(init=False)

    def __post_init__(self) -> None:
        self.system_prompt_b1 = self._load("prompt_b1.md")
        self.system_prompt_t1 = self._load("prompt_t1.md")
        self.system_prompt_iterative = self._load("prompt_iterative.md")

    def _load(self, filename: str) -> str:
        prompt_path = (
            self.template_directory / filename
            if self.template_directory is not None
            else files("network_simulation").joinpath("prompts", filename)
        )
        try:
            return prompt_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise FileNotFoundError(
                f"Could not load prompt template: {prompt_path}"
            ) from error