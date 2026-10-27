"""Normalize bounded HCL and reject executable Terraform constructs."""

from typing import Any

TERRAFORM_NESTED_BLOCKS = {
    "ip_configuration",
    "security_rule",
    "vpc",
    "ingress",
    "egress",
    "delegation",
    "service_delegation",
    "rule",
    "apply_server_side_encryption_by_default",
}


def parse_terraform(text: str) -> dict[str, Any]:
    import hcl2

    raw = hcl2.loads(text)

    def body(attributes: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for key, values in attributes.items():
            if key in ("__start_line__", "__end_line__"):
                continue
            if not isinstance(values, list):
                raise ValueError(f"Unexpected HCL attribute representation: {key}.")
            if (
                key in TERRAFORM_NESTED_BLOCKS
                and values
                and all(isinstance(item, dict) for item in values)
            ):
                result[key] = [body(item) for item in values]
            elif len(values) == 1:
                result[key] = values[0]
            else:
                raise ValueError(f"Duplicate or unsupported HCL attribute: {key}.")
        return result

    return {
        **raw,
        "resource": [
            {
                kind: {name: body(attributes) for name, attributes in entries.items()}
                for kind, entries in block.items()
            }
            for block in raw.get("resource", [])
        ],
    }


def terraform_resources(
    document: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    if any(
        key not in {"resource", "locals", "variable", "output", "terraform", "provider"}
        for key in document
    ):
        raise ValueError(
            "Unsupported Terraform block; modules, data sources and imports are not permitted."
        )
    result = {}
    for block in document.get("resource", []):
        for kind, entries in block.items():
            for name, attributes in entries.items():
                if (kind, name) in result or any(
                    key in attributes
                    for key in (
                        "count",
                        "for_each",
                        "dynamic",
                        "provisioner",
                        "connection",
                        "lifecycle",
                    )
                ):
                    raise ValueError(
                        "Repeated, dynamic or executable Terraform resources are not supported."
                    )
                result[kind, name] = attributes
    return result
