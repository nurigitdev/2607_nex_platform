from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import run_platform_local_mock_process_smoke as smoke
from nex_runtime.process_manifest import build_platform_runtime_manifest
from nex_runtime.runtime_orchestrator import RuntimeOrchestrationError


def status(state: str, ready: int) -> dict:
    return {
        "schema_version": "platform_runtime_orchestration_status.v1",
        "profile": "local_mock",
        "state": state,
        "startup_order": [f"process-{index}" for index in range(13)],
        "process_counts": {"READY": ready, "STOPPED": 13 if state == "STOPPED" else 0},
    }


class Orchestrator:
    def __init__(self, *, error=False):
        self.error = error
        self.manifest = build_platform_runtime_manifest(environ={})

    def start(self):
        if self.error:
            raise RuntimeOrchestrationError("start_failed", status("FAILED", 0))
        return status("RUNNING", 13)

    def check_running(self):
        return status("RUNNING", 13)

    def stop(self):
        return status("STOPPED", 0)


def test_smoke_composes_pass_and_safe_failure(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "_local_mock_environment", lambda: {})
    monkeypatch.setattr(smoke.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        smoke,
        "_probe_complete_topology",
        lambda manifest: [
            *({"kind": "api", "ok": True} for _ in range(5)),
            {"kind": "web", "ok": True},
        ],
    )
    monkeypatch.setattr(
        smoke,
        "build_platform_orchestrator",
        lambda *args, **kwargs: Orchestrator(),
    )

    result = smoke.run_platform_local_mock_process_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["actual_process_count"] == 13

    monkeypatch.setattr(
        smoke,
        "build_platform_orchestrator",
        lambda *args, **kwargs: Orchestrator(error=True),
    )
    failed = smoke.run_platform_local_mock_process_smoke()
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "start_failed"


def test_probe_error_and_builder_error_are_normalized(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "_local_mock_environment", lambda: {})
    monkeypatch.setattr(
        smoke,
        "build_platform_orchestrator",
        lambda *args, **kwargs: Orchestrator(),
    )
    monkeypatch.setattr(
        smoke,
        "_probe_complete_topology",
        lambda manifest: (_ for _ in ()).throw(OSError()),
    )
    assert smoke.run_platform_local_mock_process_smoke()["failure_code"] == (
        "platform_local_mock_probe_failed"
    )

    monkeypatch.setattr(
        smoke,
        "build_platform_orchestrator",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError()),
    )
    assert smoke.run_platform_local_mock_process_smoke()["status"] == "FAIL"


def test_environment_probe_privacy_and_summary_helpers(monkeypatch, capsys) -> None:
    ports = iter((19001, 19002, 19003, 19004, 19005, 19006))
    monkeypatch.setattr(smoke, "_free_port", lambda: next(ports))
    environment = smoke._local_mock_environment()
    assert environment["NEX_PROFILE"] == "local_mock"
    assert environment["NEX_AE_WEB_BASE_URL"].endswith(":19006")

    manifest = replace(
        build_platform_runtime_manifest(environ={}),
        processes=(
            SimpleNamespace(
                process_id="api", kind="api", host="127.0.0.1", port=19001
            ),
            SimpleNamespace(
                process_id="web", kind="web", host="127.0.0.1", port=19002
            ),
            SimpleNamespace(process_id="worker", kind="worker"),
        ),
    )

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"ok"

    results = smoke._probe_complete_topology(
        manifest, opener=lambda *args, **kwargs: Response()
    )
    assert [item["kind"] for item in results] == ["api", "web"]
    assert smoke._status_is_private({"state": "READY"})
    assert not smoke._status_is_private({"api_key": "secret"})

    passing = {
        "status": "PASS",
        "actual_process_count": 13,
        "http_probe_count": 6,
        "decision": {"next_slice": "1321"},
    }
    assert smoke.summary_line(passing) == (
        "platform_local_mock_process_smoke=pass processes=13 http=6 next=1321"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_local_mock_process_smoke=fail issues=1"
    )
    monkeypatch.setattr(
        smoke, "run_platform_local_mock_process_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "process_smoke=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_platform_local_mock_process_smoke",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1


def test_free_port_returns_bindable_port() -> None:
    assert smoke._free_port() > 0
