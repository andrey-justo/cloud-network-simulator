import json
import os
from pathlib import Path

import pytest

from network_simulation.study_state import atomic_json, read_checkpoint, save_checkpoint


def denied(winerror):
    error = PermissionError("replacement denied")
    error.winerror = winerror
    return error


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_atomic_json_retries_windows_sharing_conflicts(tmp_path, monkeypatch, caplog, winerror):
    path = tmp_path / "calls.json"
    path.write_text('{"old": true}', encoding="utf-8")
    replace = Path.replace
    attempts = []
    sleeps = []

    def transient_replace(source, target):
        attempts.append(target)
        if len(attempts) < 3:
            assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
            raise denied(winerror)
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", transient_replace)
    monkeypatch.setattr("network_simulation.study_state.time.sleep", sleeps.append)
    atomic_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert len(attempts) == 3
    assert sleeps == [0.1, 0.2]
    assert len(caplog.records) == 2
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(("winerror", "attempt_count"), [(5, 10), (None, 1), (19, 1)])
def test_atomic_json_surfaces_persistent_or_unrelated_denials(tmp_path, monkeypatch, winerror, attempt_count):
    path = tmp_path / "calls.json"
    path.write_text('{"old": true}', encoding="utf-8")
    attempts = []
    sleeps = []

    def failed_replace(source, target):
        attempts.append(target)
        raise denied(winerror)

    monkeypatch.setattr(Path, "replace", failed_replace)
    monkeypatch.setattr("network_simulation.study_state.time.sleep", sleeps.append)
    with pytest.raises(PermissionError, match="replacement denied"):
        atomic_json(path, {"new": True})

    assert len(attempts) == attempt_count
    assert len(sleeps) == attempt_count - 1
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert not list(tmp_path.glob("*.tmp"))


def checkpoint_manifest(directory):
    return {
        "schema_version": 1, "mode": "controlled_study", "status": "started",
        "output_directory": str(directory), "schedule": [], "trials": [],
    }


def test_persistent_windows_locks_commit_recovery_without_losing_state(tmp_path, monkeypatch, caplog):
    import os

    manifest = checkpoint_manifest(tmp_path)
    save_checkpoint(tmp_path, manifest, [])
    original = Path.replace

    def blocked(source, target):
        if target.name in ("checkpoint.json", "manifest.json", "calls.json"):
            raise denied(5)
        return original(source, target)

    monkeypatch.setattr(Path, "replace", blocked)
    monkeypatch.setattr("network_simulation.study_state.time.sleep", lambda _: None)
    manifest["recovery_marker"] = "new complete snapshot"
    save_checkpoint(tmp_path, manifest, [])
    recovery, = tmp_path.glob("checkpoint-recovery-*.json")
    os.utime(tmp_path / "checkpoint.json", (1, 1))
    assert read_checkpoint(tmp_path)["manifest"]["recovery_marker"] == "new complete snapshot"
    assert "committed complete recovery checkpoint" in caplog.text
    assert "mirror manifest.json could not be refreshed" in caplog.text
    assert "recovery_marker" not in json.loads((tmp_path / "manifest.json").read_text())

    monkeypatch.setattr(Path, "replace", original)
    manifest["recovery_marker"] = "canonical restored"
    save_checkpoint(tmp_path, manifest, [])
    os.utime(recovery, (1, 1))
    assert read_checkpoint(tmp_path)["manifest"]["recovery_marker"] == "canonical restored"
    assert not list(tmp_path.glob("*.tmp"))


def test_checkpoint_recovery_never_hides_storage_errors_or_corrupt_latest_state(tmp_path, monkeypatch):
    import os

    manifest = checkpoint_manifest(tmp_path)
    save_checkpoint(tmp_path, manifest, [])
    recovery = tmp_path / ("checkpoint-recovery-" + "a" * 32 + ".json")
    recovery.write_text("{", encoding="utf-8")
    os.utime(tmp_path / "checkpoint.json", (1, 1))
    with pytest.raises(json.JSONDecodeError):
        read_checkpoint(tmp_path)
    monkeypatch.setattr("network_simulation.study_state.time.sleep", lambda _: None)
    monkeypatch.setattr(Path, "replace", lambda *args: (_ for _ in ()).throw(denied(5)))
    with pytest.raises(PermissionError):
        save_checkpoint(tmp_path, manifest, [])


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
def test_real_windows_handle_cannot_block_durable_checkpoint_progress(tmp_path, monkeypatch):
    import ctypes
    from ctypes import wintypes

    manifest = checkpoint_manifest(tmp_path)
    save_checkpoint(tmp_path, manifest, [])
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(
        str(tmp_path / "checkpoint.json"), 0x80000000, 0x1 | 0x2,
        None, 3, 0x80, None,
    )
    assert handle != ctypes.c_void_p(-1).value
    monkeypatch.setattr("network_simulation.study_state.time.sleep", lambda _: None)
    try:
        manifest["durable_progress"] = 55
        save_checkpoint(tmp_path, manifest, [])
        assert read_checkpoint(tmp_path)["manifest"]["durable_progress"] == 55
        assert len(list(tmp_path.glob("checkpoint-recovery-*.json"))) == 1
        assert "durable_progress" not in json.loads((tmp_path / "checkpoint.json").read_text())
    finally:
        assert kernel.CloseHandle(handle)
