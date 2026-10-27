import json
from copy import deepcopy
from pathlib import Path

import pytest

from network_simulation.study_retry import retry_trial
from network_simulation.study_state import execution_lock, read_checkpoint
from test_study import make_runner


def failed_study(tmp_path):
    class Client:
        calls = 0
        last_usage = None

        def __call__(self, prompt):
            self.calls += 1
            if self.calls == 1:
                self.last_usage = None
                raise RuntimeError("Mock service outage")
            self.last_usage = {"input_tokens": 10, "output_tokens": 5}
            return "// mocked generation"

    client = Client()
    runner, _ = make_runner(tmp_path, pass_visible=True, repetitions=2, client=client)
    runner.config.study.assessment_mode = "human_review"
    manifest = runner.run(["NET-01"])
    assert manifest["status"] == "completed_with_operational_failures"
    return runner, client, Path(manifest["output_directory"]), manifest


def test_preview_never_calls_model_or_changes_saved_results(tmp_path):
    runner, client, directory, _ = failed_study(tmp_path)
    checkpoint = (directory / "checkpoint.json").read_bytes()
    result = retry_trial(runner, directory, 1)
    assert result["paid_execution"] is False
    assert result["preserved_other_trials"] == 1
    assert result["maximum_new_generation_requests"] == 5
    assert client.calls == 2
    assert (directory / "checkpoint.json").read_bytes() == checkpoint
    assert not (directory / "operational-retries").exists()


def test_retry_preserves_other_trials_original_artifacts_and_usage(tmp_path):
    runner, client, directory, original = failed_study(tmp_path)
    before = deepcopy(original)
    original_bytes = (directory / "trial-00001" / "result.json").read_bytes()
    checkpoint = (directory / "checkpoint.json").read_bytes()
    with execution_lock(directory), pytest.raises(ValueError, match="already running"):
        retry_trial(runner, directory, 1, execute=True)
    assert (directory / "checkpoint.json").read_bytes() == checkpoint
    result = retry_trial(runner, directory, 1, execute=True)
    assert result["status"] == "completed"
    assert client.calls == 3
    assert result["trials"][1] == before["trials"][1]
    assert len(result["trials"]) == 2
    assert (directory / "trial-00001" / "result.json").read_bytes() == original_bytes
    event = result["operational_retries"][0]
    assert json.loads(Path(event["original_checkpoint_file"]).read_text())["manifest"] == before
    assert json.loads(Path(event["original_result_file"]).read_text()) == before["trials"][0]
    assert event["status"] == "completed" and event["new_generation_requests"] == 1
    for arm, value in result["trials"][0]["conditions"].items():
        assert value["accepted"] is None
        assert value["operational_error"] is False
        assert value["candidates"][0].startswith(event["replacement_directory"])
        assert len(value["candidates"]) == 1
    assert read_checkpoint(directory)["manifest"] == result
    ledger = read_checkpoint(directory)["calls"]
    assert len(ledger) == 3
    assert ledger[0]["status"] == "generation_failed"
    assert ledger[0]["usage"] is None
    assert "superseded_by_operational_retry" in ledger[0]
    unique = result["summary"]["usage"]["unique_execution"]
    assert unique["known_requests"] == 2 and unique["unknown_requests"] == 1
    assert unique["input_tokens"] == 20
    assert result["maximum_generation_requests"] == before["maximum_generation_requests"] + 5
    assert json.loads((directory / "summary.json").read_text()) == result["summary"]


@pytest.mark.parametrize("index", [0, -1, 3, True, 2])
def test_retry_rejects_bad_indices_and_nonoperational_results(tmp_path, index):
    runner, client, directory, _ = failed_study(tmp_path)
    with pytest.raises(ValueError):
        retry_trial(runner, directory, index, execute=True)
    assert client.calls == 2


def test_retry_rejects_changed_frozen_protocol(tmp_path):
    runner, client, directory, _ = failed_study(tmp_path)
    runner.config.llm.max_tokens += 1
    with pytest.raises(ValueError, match="frozen study field changed"):
        retry_trial(runner, directory, 1, execute=True)
    assert client.calls == 2


def test_interrupted_retry_preserves_original_and_records_extra_requests(tmp_path, monkeypatch):
    runner, client, directory, before = failed_study(tmp_path)
    original_trial = runner._trial

    def interrupt(job, scenario, output):
        original_trial(job, scenario, output)
        raise RuntimeError("Interrupted after saved generation")

    monkeypatch.setattr(runner, "_trial", interrupt)
    with pytest.raises(RuntimeError, match="Interrupted after"):
        retry_trial(runner, directory, 1, execute=True)
    saved = read_checkpoint(directory)
    assert saved["manifest"]["trials"] == before["trials"]
    assert saved["manifest"]["status"] == "completed_with_operational_failures"
    assert saved["manifest"]["operational_retries"][-1]["status"] == "interrupted"
    assert saved["calls"][-1]["excluded_from_completed_trials"] is True
    assert len(saved["calls"]) == client.calls == 3


def test_retry_that_fails_again_is_not_silently_reported_as_success(tmp_path):
    runner, _, directory, _ = failed_study(tmp_path)
    model = runner.config.llm.model_name

    def failed(prompt):
        raise RuntimeError("Still unavailable")

    runner.clients[model] = failed
    result = retry_trial(runner, directory, 1, execute=True)
    assert result["status"] == "completed_with_operational_failures"
    assert result["operational_retries"][-1]["new_generation_requests"] == 1
    assert all(value["operational_error"] for value in result["trials"][0]["conditions"].values())
    assert len(read_checkpoint(directory)["calls"]) == 3
