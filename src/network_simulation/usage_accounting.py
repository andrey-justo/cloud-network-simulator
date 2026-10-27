"""Observed usage only; workflow attribution is not a billing total."""

from typing import Any


def call_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    known = [call["usage"] for call in calls if call.get("usage") is not None]
    inputs = sum(item["input_tokens"] for item in known) if known else None
    outputs = sum(item["output_tokens"] for item in known) if known else None
    return {
        "known_requests": len(known),
        "unknown_requests": len(calls) - len(known),
        "input_tokens": inputs, "output_tokens": outputs,
        "total_tokens": inputs + outputs if known else None,
        "generation_seconds": sum(call["generation_seconds"] for call in calls)
        if calls and all(call.get("generation_seconds") is not None for call in calls) else None,
    }


def workflow_usage(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        condition.get("usage_accounting") or {
            "known_requests": condition["attempts"] if condition.get("usage") is not None else 0,
            "unknown_requests": 0 if condition.get("usage") is not None else condition["attempts"],
            "input_tokens": (condition.get("usage") or {}).get("input_tokens"),
            "output_tokens": (condition.get("usage") or {}).get("output_tokens"),
        }
        for condition in conditions
    ]
    known = sum(value["known_requests"] for value in values)
    inputs = sum(value["input_tokens"] or 0 for value in values) if known else None
    outputs = sum(value["output_tokens"] or 0 for value in values) if known else None
    return {
        "workflows": len(conditions),
        "known_requests": known,
        "unknown_requests": sum(value["unknown_requests"] for value in values),
        "input_tokens": inputs, "output_tokens": outputs,
        "total_tokens": inputs + outputs if known else None,
        "mean_elapsed_seconds": sum(value["elapsed_seconds"] for value in conditions) / len(conditions) if conditions else None,
    }
