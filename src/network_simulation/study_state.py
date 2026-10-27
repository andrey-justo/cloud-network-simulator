"""Durable paired-trial checkpoints and OS-owned execution locks."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


logger = logging.getLogger(__name__)


def _nonnegative(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _sharing_conflict(error: OSError) -> bool:
    return isinstance(error, PermissionError) and getattr(error, "winerror", None) in (5, 32, 33)


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(10):
            try:
                temporary.replace(path)
                break
            except PermissionError as error:
                if not _sharing_conflict(error) or attempt == 9:
                    raise
                logger.warning(
                    "Checkpoint replacement temporarily denied for %s; retry %s/9: %s",
                    path, attempt + 1, error,
                )
                time.sleep(0.1 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def execution_lock(directory: Path) -> Iterator[None]:
    with (directory / ".execution.lock").open("a+b") as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("This execution is already running or its lock is unavailable.") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_checkpoint(directory: Path) -> dict[str, Any]:
    filename = directory / "checkpoint.json"
    recovery_files = list(directory.glob("checkpoint-recovery-*.json"))
    candidates = ([filename] if filename.is_file() else []) + recovery_files
    if candidates:
        filename = max(candidates, key=lambda candidate: candidate.stat().st_mtime_ns)
    if not filename.is_file():
        raise ValueError(
            "Resume requires a managed checkpoint. Legacy runs cannot safely be "
            "resumed; use a full rerun in a new directory instead."
        )
    checkpoint = json.loads(filename.read_text(encoding="utf-8"))
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("schema_version") != 1
        or not isinstance(checkpoint.get("manifest"), dict)
        or not isinstance(checkpoint.get("calls"), list)
    ):
        raise ValueError("Invalid execution checkpoint.")
    manifest = checkpoint["manifest"]
    if manifest.get("schema_version") != 1 or manifest.get("mode") != "controlled_study":
        raise ValueError("Unsupported checkpoint manifest.")
    schedule = manifest.get("schedule")
    if not isinstance(manifest.get("study", {}), dict):
        raise ValueError("Checkpoint study configuration is invalid.")
    human_review = manifest.get("study", {}).get("assessment_mode") == "human_review"
    trials = manifest.get("trials")
    if not isinstance(schedule, list) or not isinstance(trials, list) or len(trials) > len(schedule):
        raise ValueError("Invalid checkpoint schedule/trials.")
    for trial, job in zip(trials, schedule):
        if not isinstance(job, dict) or not isinstance(trial, dict) or any(
            trial.get(field) != job.get(field)
            for field in ("scenario_id", "model", "repetition")
        ) or not isinstance(trial.get("conditions"), dict) or set(trial["conditions"]) != {"one_shot", "blind_refinement", "tool_feedback"}:
            raise ValueError("Checkpoint trials must be a complete prefix of the frozen schedule.")
        for result in trial["conditions"].values():
            if (
                not isinstance(result, dict)
                or any(type(result.get(field)) is not bool for field in (
                    "visible_checks_passed",
                    "generation_failed", "operational_error",
                ))
                or (
                    not (result.get("accepted") is None and result.get("structural_accepted") is None
                         and isinstance(result.get("requirement_assessment"), dict)
                         and result.get("requirement_assessment", {}).get("status") == "awaiting_human_review")
                    if human_review else
                    any(type(result.get(field)) is not bool for field in ("accepted", "structural_accepted"))
                )
                or not _nonnegative(result.get("elapsed_seconds"))
                or (result.get("cost_usd") is not None and not _nonnegative(result["cost_usd"]))
                or not isinstance(result.get("cloud"), dict)
                or not isinstance(result.get("candidates"), list)
                or not result["candidates"]
            ):
                raise ValueError("Invalid completed condition in checkpoint.")
    for call in checkpoint["calls"]:
        if (
            not isinstance(call, dict)
            or not isinstance(call.get("directory"), str)
            or not isinstance(call.get("model"), str)
            or call.get("status") not in ("generated", "generation_failed")
            or (call.get("cost_usd") is not None and not _nonnegative(call["cost_usd"]))
        ):
            raise ValueError("Invalid checkpoint call ledger.")
        usage = call.get("usage")
        if usage is not None and (
            not isinstance(usage, dict)
            or any(type(usage.get(field)) is not int or usage[field] < 0 for field in ("input_tokens", "output_tokens"))
        ):
            raise ValueError("Invalid checkpoint token usage.")
    return checkpoint


def save_checkpoint(directory: Path, manifest: dict[str, Any], calls: list[dict[str, Any]]) -> None:
    checkpoint = {"schema_version": 1, "manifest": manifest, "calls": calls}
    try:
        atomic_json(directory / "checkpoint.json", checkpoint)
    except PermissionError as error:
        if not _sharing_conflict(error):
            raise
        recovery = directory / f"checkpoint-recovery-{uuid4().hex}.json"
        atomic_json(recovery, checkpoint)
        logger.error(
            "Checkpoint replacement is blocked; committed complete recovery checkpoint to %s. "
            "Execution can continue; readers and resume use the newest checkpoint.",
            recovery,
        )
    for filename, value in (("calls.json", calls), ("manifest.json", manifest)):
        try:
            atomic_json(directory / filename, value)
        except PermissionError as error:
            if not _sharing_conflict(error):
                raise
            logger.error(
                "Checkpoint mirror %s could not be refreshed; complete state is durable "
                "in the newest checkpoint: %s", filename, error,
            )
