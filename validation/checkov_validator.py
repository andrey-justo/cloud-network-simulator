"""Compatibility entry point for the packaged Checkov adapter."""

from network_simulation.validation.checkov_validator import (
    CheckovResult,
    CheckovValidator,
    ValidationReport,
    main,
    validate_all_scenarios,
)

__all__ = ["CheckovResult", "CheckovValidator", "ValidationReport", "validate_all_scenarios"]


if __name__ == "__main__":
    main()
