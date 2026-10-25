from dataclasses import dataclass, field


@dataclass
class ExperimentConfig:
    experiment_phase: str = "pilot"
    pilot_scenarios: list[str] = field(
        default_factory=lambda: ["NET-01", "NET-02", "NET-03"]
    )
    main_scenarios: list[str] = field(
        default_factory=lambda: [
            "NET-01",
            "NET-02",
            "NET-03",
            "NET-04",
            "NET-05",
            "NET-06",
        ]
    )
    run_b0: bool = True
    run_b1: bool = True
    run_t1: bool = True
    b1_max_iterations: int = 5
    t1_max_iterations: int = 5
    acceptance_criteria_threshold: float = 0.8
    max_violations_acceptable: int = 0
    output_directory: str = "reports"
    save_templates: bool = True
    save_validation_logs: bool = True