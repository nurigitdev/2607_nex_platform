from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import run_platform_oa_backed_trust_postgres_smoke as smoke


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _test_database_env() -> dict[str, str]:
    return {
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret@127.0.0.1/nex_oa_test"
        ),
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
        ),
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
        ),
        "NEX_MO_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_mo_user:secret@127.0.0.1/nex_mo_test"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ag_user:secret@127.0.0.1/nex_ag_test"
        ),
    }


def _token_map() -> dict[str, str]:
    return {
        name: f"signed-{name}"
        for name in (
            "ae_to_oa",
            "ae_to_cx",
            "ae_to_ag",
            "ae_to_cx_no_call",
            "cx_to_mo",
            "ae_introspect",
            "cx_introspect",
            "mo_introspect",
            "ag_introspect",
            "revoke_control",
        )
    }


def _active(service_id: str, request_id: str) -> dict[str, Any]:
    return {
        "service_id": service_id,
        "request_id": request_id,
        "trace_id": TRACE_ID,
        "claims": {
            "token_kind": "SIGNED",
            "scopes": ["service:call"],
            "introspection_status": "ACTIVE",
        },
    }


def test_smoke_is_protected_by_default() -> None:
    result = smoke.run_smoke({})

    assert result["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in result["skip_reason"]
    assert "reason=" in smoke.summary_line(result)


def test_runtime_environment_maps_test_databases_and_local_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ports = iter(range(18101, 18107))
    monkeypatch.setattr(smoke, "_free_port", lambda: next(ports))

    result = smoke._runtime_environment(_test_database_env(), work_root=tmp_path)

    assert result["NEX_PROFILE"] == "test"
    assert result["NEX_PERSISTENCE_MODE"] == "postgres"
    assert result["NEX_SERVICE_TOKEN_ROLLOUT_PROFILE"] == "SIGNED_ONLY"
    assert result["NEX_OA_DATABASE_URL"].endswith("/nex_oa_test")
    assert result["NEX_CX_VECTOR_DATABASE_URL"].endswith("/nex_cx_test")
    assert result["NEX_OA_BASE_URL"] == "http://127.0.0.1:18101"
    assert result["NEX_OA_SIGNING_PROVIDER"] == "TEST_FILE"
    assert result["NEX_CX_SOURCE_STORAGE_ROOT"] == str(tmp_path / "cx-source")


def test_service_environment_assigns_least_privilege_tokens() -> None:
    result = smoke._service_environments({"base": "value"}, _token_map())

    assert result["nex-ae-api"]["NEX_AE_TO_OA_SERVICE_TOKEN"] == "signed-ae_to_oa"
    assert result["nex-cx"]["NEX_CX_TO_MO_SERVICE_TOKEN"] == "signed-cx_to_mo"
    assert result["nex-mo"]["NEX_OA_INTROSPECTION_SERVICE_TOKEN"] == (
        "signed-mo_introspect"
    )
    assert result["nex-ag"]["NEX_OA_INTROSPECTION_SERVICE_TOKEN"] == (
        "signed-ag_introspect"
    )
    assert result["nex-oa"] == {"base": "value"}


def test_workflow_projection_passes_exact_trust_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_login_context_observed",
        lambda *args, **kwargs: {"request_id": True, "trace_id": True},
    )
    first = {
        "wrong_audience": {"status": 403, "error_code": "wrong"},
        "missing_scope": {"status": 403, "error_code": "scope"},
    }
    request_id = "s134-g2"
    second = {
        "request_id": request_id,
        "trace_id": TRACE_ID,
        "session": {
            "status": "ACTIVE",
            "tenant_ref": {"id": "tenant-s134"},
            "subject_ref": {"id": "user-s134"},
        },
        "active": {
            service_id: _active(service_id, request_id)
            for service_id in ("nex-cx", "nex-mo", "nex-ag")
        },
        "jwks": {"key_count": 1},
        "revoked_session": {"status": 401, "error_code": "session-revoked"},
        "revoked_token": {
            "status": 401,
            "error_code": "nex.token_introspection_inactive",
        },
    }
    context = {"tenant_id": "tenant-s134", "subject_id": "user-s134"}

    workflow = smoke._build_workflow(first, second, {}, context, "s134")
    evaluated = smoke.evaluate_platform_trust_evidence(
        {
            **workflow,
            "databases": {
                "service_count": 5,
                "migration_count": 89,
                "cleanup_residue_count": 0,
                "temporary_key_residue_count": 0,
            },
        }
    )

    assert evaluated["status"] == "PASS"
    assert evaluated["summary"]["passed_hop_count"] == 5
    assert evaluated["summary"]["passed_denial_count"] == 4


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[object, ...]] = []

    def request(self, *args: object, **kwargs: object) -> _Response:
        self.calls.append((*args, kwargs))
        return self.response


def test_json_request_and_projection_helpers_fail_closed() -> None:
    client = _Client(_Response(200, {"status": "ok"}))
    assert smoke._json_request(
        client,  # type: ignore[arg-type]
        "GET",
        "http://local/test",
        expected_status=200,
    ) == {"status": "ok"}
    assert smoke._trace_headers("request", TRACE_ID)["traceparent"].startswith(
        f"00-{TRACE_ID}-"
    )
    assert smoke._denial("scope", "nex-cx", {"status_code": 403}) == {
        "scenario": "scope",
        "service_id": "nex-cx",
        "status_code": 403,
        "error_code": "denied",
        "failed_closed": True,
    }

    with pytest.raises(RuntimeError, match="status mismatch"):
        smoke._json_request(
            _Client(_Response(503, {})),  # type: ignore[arg-type]
            "GET",
            "http://local/test",
            expected_status=200,
        )
    with pytest.raises(RuntimeError, match="JSON object"):
        smoke._json_request(
            _Client(_Response(200, [])),  # type: ignore[arg-type]
            "GET",
            "http://local/test",
            expected_status=200,
        )


class _Process:
    def __init__(self, *, running: bool = True, timeout_once: bool = False) -> None:
        self.running = running
        self.timeout_once = timeout_once
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return None if self.running else 1

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> int:
        if self.timeout_once:
            self.timeout_once = False
            raise smoke.subprocess.TimeoutExpired("test", timeout)
        self.running = False
        return 0

    def kill(self) -> None:
        self.killed = True


def test_process_wait_and_stop_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        smoke.httpx,
        "get",
        lambda *args, **kwargs: _Response(503, {"checks": [{"ok": True}]}),
    )
    smoke._wait_for_database_ready("http://local", _Process(), timeout_seconds=0.1)  # type: ignore[arg-type]

    exited = _Process(running=False)
    with pytest.raises(RuntimeError, match="exited"):
        smoke._wait_for_database_ready(
            "http://local", exited, timeout_seconds=0.1  # type: ignore[arg-type]
        )

    stubborn = _Process(timeout_once=True)
    stopped: list[Any] = [stubborn]
    smoke._stop_processes(stopped)  # type: ignore[arg-type]
    assert stubborn.terminated is True
    assert stubborn.killed is True
    assert stopped == []

    already_stopped = _Process(running=False)
    stopped = [already_stopped]
    smoke._stop_processes(stopped)  # type: ignore[arg-type]
    assert already_stopped.terminated is False


def test_process_wait_times_out_after_transient_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter((0.0, 0.0, 1.0))
    monkeypatch.setattr(smoke, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(smoke, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        smoke.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )

    with pytest.raises(TimeoutError, match="timed out"):
        smoke._wait_for_database_ready(
            "http://local", _Process(), timeout_seconds=0.5  # type: ignore[arg-type]
        )


def test_seed_and_cleanup_guards_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(smoke, "build_service_app", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            api_engine=None,
            api_session_factory=None,
            worker_engine=None,
        ),
    )

    with pytest.raises(RuntimeError, match="unavailable"):
        smoke._seed_oa_trust({}, run_prefix="s134-unit", work_root=tmp_path)
    assert smoke._cleanup_oa({}, {}, run_prefix="s134-unit") == 0


def test_runtime_disposal_deduplicates_shared_engines() -> None:
    engine = SimpleNamespace(dispose=lambda: calls.append("disposed"))
    calls: list[str] = []

    smoke._dispose_runtime(SimpleNamespace(api_engine=engine, worker_engine=engine))
    smoke._dispose_runtime(SimpleNamespace(api_engine=None, worker_engine=None))

    assert calls == ["disposed"]


def test_start_service_and_summary_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_popen(command: tuple[str, ...], **kwargs: Any) -> object:
        captured.update(command=command, kwargs=kwargs)
        return object()

    monkeypatch.setattr(smoke.subprocess, "Popen", fake_popen)
    process = smoke._start_service(
        "nex-cx", {"NEX_CX_BASE_URL": "http://127.0.0.1:18104"}
    )

    assert process is not None
    assert captured["command"][-2:] == ("--port", "18104")
    assert captured["kwargs"]["stdout"] is smoke.subprocess.DEVNULL
    assert smoke._free_port() > 0
    assert "code=broken" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "broken"}
    )
    assert "hops=5/5" in smoke.summary_line(
        {
            "status": "PASS",
            "summary": {
                "passed_hop_count": 5,
                "hop_count": 5,
                "passed_denial_count": 4,
                "denial_count": 4,
                "database_service_count": 5,
                "cleanup_residue_count": 0,
            },
        }
    )


def test_run_smoke_redacts_failure_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        lambda env: (_ for _ in ()).throw(RuntimeError("private database detail")),
    )

    result = smoke.run_smoke({smoke.SMOKE_ENV: "1"})

    assert result["status"] == "FAIL"
    assert result["detail"] == "RuntimeError"
    assert "private database detail" not in str(result)


def test_main_prints_safe_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_smoke",
        lambda: {"status": "SKIPPED", "skip_reason": "protected"},
    )
    monkeypatch.setattr(smoke, "load_env_file", lambda path: {})

    assert smoke.main(["--summary"]) == 0
    assert "platform_oa_backed_trust_postgres=skip" in capsys.readouterr().out


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required",
)
def test_actual_five_database_loopback_http_trust_smoke() -> None:
    report = smoke.run_smoke()

    assert report["status"] == "PASS"
    assert report["actual_http"] is True
    assert report["actual_postgresql"] is True
    assert report["summary"] == {
        "hop_count": 5,
        "passed_hop_count": 5,
        "denial_count": 4,
        "passed_denial_count": 4,
        "restart_generation_count": 2,
        "database_service_count": 5,
        "cleanup_residue_count": 0,
        "privacy_violation_count": 0,
    }
    assert report["remote_provider_required"] is False
