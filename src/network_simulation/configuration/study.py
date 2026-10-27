import math
from dataclasses import dataclass, field


@dataclass
class StudyConfig:
    repetitions: int = 1
    max_iterations: int = 5
    random_seed: int = 1729
    models: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=lambda: ["azure-bicep"])
    assessment_mode: str = "finite_contract"
    input_usd_per_million: float | None = None
    output_usd_per_million: float | None = None
    model_prices: dict[str, list[float]] = field(default_factory=dict)
    bootstrap_samples: int = 2000

    def validate(self) -> None:
        from network_simulation.scenario_targets import TARGETS
        if self.assessment_mode not in ("finite_contract", "human_review"):
            raise ValueError("study.assessment_mode must be finite_contract or human_review.")

        if (
            not isinstance(self.targets, list) or not self.targets
            or any(not isinstance(target, str) or target not in TARGETS for target in self.targets)
            or len(set(self.targets)) != len(self.targets)
        ):
            raise ValueError(f"study.targets must be unique supported targets: {', '.join(TARGETS)}.")
        for name in ("repetitions", "max_iterations", "bootstrap_samples"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"study.{name} must be a positive integer.")
        if type(self.random_seed) is not int:
            raise ValueError("study.random_seed must be an integer.")
        if not isinstance(self.models, list) or any(
            not isinstance(model, str) or not model.strip() for model in self.models
        ):
            raise ValueError("study.models must contain nonempty model identifiers.")
        if len(set(self.models)) != len(self.models):
            raise ValueError("study.models must not contain duplicates.")
        rates = (self.input_usd_per_million, self.output_usd_per_million)
        if any(rate is None for rate in rates) and not all(
            rate is None for rate in rates
        ):
            raise ValueError("Set both token prices or neither.")
        if any(
            rate is not None
            and (type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0)
            for rate in rates
        ):
            raise ValueError(
                "Token prices must be finite nonnegative USD per million tokens."
            )
        if not isinstance(self.model_prices, dict) or any(
            not isinstance(model, str)
            or not isinstance(prices, list)
            or len(prices) != 2
            or any(
                type(price) not in (int, float) or not math.isfinite(price) or price < 0
                for price in prices
            )
            for model, prices in self.model_prices.items()
        ):
            raise ValueError(
                "study.model_prices maps model IDs to [input, output] USD per million tokens."
            )
