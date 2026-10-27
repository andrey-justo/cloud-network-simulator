import io
import json
import shutil
from pathlib import Path
from http.client import HTTPConnection
from urllib.parse import urlsplit

import pytest

from network_simulation.main import main
from network_simulation.ui_worker import options, prepare, preview

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path):
    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    shutil.copytree(ROOT / "scenarios", tmp_path / "scenarios")
    return tmp_path


def test_preview_is_static_and_does_not_generate(workspace, monkeypatch):
    monkeypatch.setattr("network_simulation.study.ControlledStudyRunner.run", lambda *a, **kw: pytest.fail("Preview must never execute"))
    request = {"operation": "new", "config": "configs/smoke-static.yaml"}
    plan = preview(workspace, request)
    assert plan["total"] == 2
    assert plan["completed"] == 0
    assert plan["maximum_new_generation_requests"] == 6
    assert not (workspace / "results").exists()
    request.update(repetitions=2, max_iterations=3, models=["gpt-5.3-codex"], scenarios=["NET-01", "NET-02"])
    changed = preview(workspace, request)
    assert changed["total"] == 4
    assert changed["maximum_new_generation_requests"] == 20
    assert changed["digest"] != plan["digest"]


@pytest.mark.parametrize("changes", [
    {"config": "../pyproject.toml"}, {"config": 123},
    {"repetitions": True}, {"max_tokens": 0}, {"models": "not-an-array"},
    {"scenarios": "NET-01"}, {"login": "true"},
    {"cloud": {"enabled": True}}, {"operation": "arbitrary-command"},
])
def test_ui_rejects_invalid_and_unbounded_path_inputs(workspace, changes):
    request = {"operation": "new", "config": "configs/smoke-static.yaml", **changes}
    with pytest.raises((ValueError, OSError)):
        preview(workspace, request)


def test_cloud_enabled_profile_is_rejected(workspace):
    profile = workspace / "configs" / "unsafe.yaml"
    profile.write_text("cloud:\n  enabled: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="never permits Azure"):
        prepare(workspace, {"operation": "new", "config": "configs/unsafe.yaml"})
    assert "configs/unsafe.yaml" not in {item["config"] for item in options(workspace)["configs"]}


def test_cli_ui_only_needs_no_configuration_and_never_executes(monkeypatch, workspace):
    calls = []
    monkeypatch.setattr("network_simulation.ui.launch_ui", lambda *a, **kw: calls.append(kw) or 0)
    assert main(["--workspace", str(workspace), "--ui"]) == 0
    assert calls[0]["execute"] is False
    assert calls[0]["parameters"] == {"operation": "new", "login": False}
    assert main(["--workspace", str(workspace), "--ui", "--config", "configs/smoke-static.yaml", "--execute", "--login"]) == 0
    assert calls[1]["execute"] is True
    assert calls[1]["parameters"]["login"] is True


@pytest.mark.parametrize("arguments", [
    ["--ui", "--allow-azure"], ["--ui", "--execute"],
    ["--ui", "--dry-run"], ["--full-rerun"],
    ["--ui", "--login"], ["--resume", "somewhere", "--scenario", "NET-01"],
])
def test_cli_rejects_conflicting_launch_flags(arguments):
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_worker_run_revalidates_preview_and_uses_explicit_parameters(workspace, monkeypatch, capsys):
    from network_simulation import ui_worker

    parameters = {"operation": "new", "config": "configs/smoke-static.yaml"}
    expected = preview(workspace, parameters)
    captured = []

    def run(self, scenarios, **kwargs):
        captured.append((scenarios, kwargs))
        directory = workspace / "results" / "ui-runs" / "study-mocked"
        kwargs["on_started"](directory)
        return {"status": "completed", "output_directory": str(directory)}

    monkeypatch.setattr("network_simulation.study.ControlledStudyRunner.run", run)
    monkeypatch.setattr("sys.argv", ["worker", "--workspace", str(workspace), "run"])
    request = {"parameters": parameters, "expected_digest": expected["digest"]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request)))
    assert ui_worker.main() == 0
    assert captured[0][0] == ["NET-01"]
    assert captured[0][1]["allow_browser_auth"] is False
    assert captured[0][1]["resume_from"] is None
    assert "study-mocked" in capsys.readouterr().out
    request["expected_digest"] = "modified"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request)))
    assert ui_worker.main() == 2
    assert len(captured) == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for the dashboard")
def test_real_cli_ui_server_previews_without_execution_and_shuts_down(workspace, monkeypatch, capsys):
    from network_simulation.ui import launch_ui

    def inspect_ui(url):
        port = urlsplit(url).port

        def request(method, endpoint, payload=None):
            connection = HTTPConnection("127.0.0.1", port, timeout=15)
            try:
                connection.request(method, endpoint, body=json.dumps(payload) if payload is not None else None,
                                   headers={"Origin": url, "Content-Type": "application/json"})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            assert request("GET", "/api/state")[1]["status"] == "empty"
            control = request("GET", "/api/control")[1]
            assert control["enabled"] is True
            assert control["job"] is None
            status, plan = request("POST", "/api/plan", {
                "operation": "new", "config": "configs/smoke-static.yaml",
            })
            assert status == 200
            assert plan["maximum_new_generation_requests"] == 6
            assert request("POST", "/api/start", {"plan_id": plan["plan_id"], "confirmed": False})[0] == 400
            assert request("GET", "/api/control")[1]["job"] is None
        finally:
            assert request("POST", "/api/shutdown", {})[0] == 200
        return True

    monkeypatch.setattr("webbrowser.open", inspect_ui)
    assert launch_ui(workspace) == 0
    assert "Study dashboard: http://127.0.0.1:" in capsys.readouterr().out
    assert not (workspace / "results").exists()
