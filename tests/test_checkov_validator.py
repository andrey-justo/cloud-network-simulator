from validation.checkov_validator import CheckovValidator


def test_checkov_parser_errors_are_not_reported_as_passes() -> None:
    validator = CheckovValidator(framework="bicep")

    report = validator._parse_checkov_output(
        {
            "results": {"failed_checks": [], "passed_checks": [], "skipped_checks": []},
            "summary": {
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "parsing_errors": 1,
            },
        },
        "template.bicep",
        "NET-01",
    )

    assert report.total_checks == 0
    assert report.parsing_errors == 1