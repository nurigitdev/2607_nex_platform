from __future__ import annotations

import json
from threading import RLock
from types import SimpleNamespace
from typing import Any

import pytest
import run_gb2_s20qpab_limited_shadow_operations as smoke
from nex_cx.retrieval_answer_support_controlled_activation import (
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    OperationalRuntimeActivationStateStore,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter


class FakeGenerationClient:
    def __init__(self) -> None:
        self.calls = 0

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        del request_id, trace_id
        self.calls += 1
        request = json.loads(payload["messages"][1]["content"])
        return {
            "alias": "general-llm-default",
            "model_revision": "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            "deployment_id": "dgx-qwen3-5-9b-9116",
            "provider_type": "vllm",
            "output": {
                "type": "text",
                "text": json.dumps(
                    {
                        "items": [
                            {
                                "candidate_id": row["candidate_id"],
                                "classification": "SUPPORTING_EVIDENCE",
                                "answer_support_score": 0.9,
                                "contradiction_score": 0.05,
                            }
                            for row in request["candidates"]
                        ]
                    }
                ),
            },
            "finish_reason": "STOP",
            "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        }


class LockedOperationalEventStore(InMemoryOperationalEventStore):
    def __init__(self) -> None:
        super().__init__()
        self._lock = RLock()

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            return super().append(event)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            return super().get_event(event_id)

    def list_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        with self._lock:
            return super().list_events(**kwargs)


class FakeScalarResult:
    def scalar_one(self) -> int:
        return 0


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def execute(
        self, statement: Any, parameters: dict[str, Any]
    ) -> FakeScalarResult:
        self.calls.append((statement, parameters))
        return FakeScalarResult()


class FakeContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *args: object) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.disposed = False

    def begin(self) -> FakeContext:
        return FakeContext(self.connection)

    def connect(self) -> FakeContext:
        return FakeContext(self.connection)

    def dispose(self) -> None:
        self.disposed = True


def test_limited_operations_accepts_exact_window_and_restart_cap() -> None:
    client = FakeGenerationClient()
    state_store, events = _state_store()

    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(),
        state_store=state_store,
        generation_client=client,
        cases_document=_cases(),
    )

    assert result["status"] == "PASS", result
    assert result["decision"] == "LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED"
    assert result["live_execution"]["sample_count"] == 12
    assert result["live_execution"]["provider_call_count"] == 12
    assert result["live_execution"]["wave_count"] == 3
    assert result["window"]["sample_cap_reached"] is True
    assert result["operations_status"] == "REVIEW_REQUIRED"
    assert result["database_profile"] == "injected"
    assert result["holdout_accessed"] is False
    assert result["production_cutover_permitted"] is False
    assert client.calls == 12
    assert len(events.list_events(service_id="nex-cx")) > 12
    assert "restart_cap=verified" in smoke.summary_line(result)


def test_runner_requires_enablement_and_operator_approval() -> None:
    assert smoke.run_gb2_s20qpab_limited_shadow_operations({})["status"] == (
        "SKIPPED"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        {smoke.SMOKE_ENV: "1"}
    )
    assert result["failure_code"] == "operator_approval_required"


def test_runner_rejects_incomplete_cases_and_redacts_evidence() -> None:
    state_store, _events = _state_store()
    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document={"cases": []},
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {"exception": "ValueError"}
    assert result["provider_http_requests"] == 0
    assert "=fail" in smoke.summary_line(result)
    with pytest.raises(ValueError, match="leaked"):
        smoke._assert_redacted(
            {"secret": "api-secret"},
            {"NEX_MO_VLLM_API_KEY": "api-secret"},
            [],
        )


def test_runner_fails_closed_when_installed_runtime_is_missing(monkeypatch) -> None:
    state_store, _events = _state_store()
    monkeypatch.setattr(
        smoke, "build_installed_controlled_answer_support_runtime", lambda **_kwargs: None
    )
    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"


def test_runner_rejects_bundle_drift_and_incomplete_window(monkeypatch) -> None:
    state_store, _events = _state_store()
    policy = smoke.load_limited_operations_policy(smoke.DEFAULT_POLICY_PATH)
    drift = {**policy, "activation_bundle_hash": "sha256:" + "0" * 64}
    monkeypatch.setattr(smoke, "load_limited_operations_policy", lambda _path: drift)
    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"

    monkeypatch.setattr(
        smoke,
        "load_limited_operations_policy",
        lambda _path: policy,
    )
    monkeypatch.setattr(smoke, "_capacity_cases", lambda _document: [{}] * 11)
    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"


def test_runner_fails_closed_when_restart_runtime_is_missing(monkeypatch) -> None:
    state_store, _events = _state_store()
    original = smoke.build_installed_limited_shadow_operations_runtime
    calls = 0

    def build_limited(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return None
        return original(**kwargs)

    monkeypatch.setattr(
        smoke, "build_installed_limited_shadow_operations_runtime", build_limited
    )
    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"
    assert result["provider_http_requests"] == 12


def test_default_live_and_database_path_uses_admitted_provider_and_cleanup(
    monkeypatch,
) -> None:
    client = FakeGenerationClient()
    events = LockedOperationalEventStore()
    engine = FakeEngine()
    migration_calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: [])
    monkeypatch.setattr(smoke, "admit_model_artifact_revision_evidence", lambda _doc: {})
    monkeypatch.setattr(smoke, "_bind_provider", lambda *_args: None)
    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="http://provider:9116/v1/chat/completions"),
    )
    monkeypatch.setattr(
        smoke.remote_provider,
        "execute_remote_generation_request",
        lambda payload, **_kwargs: client.create_generation(
            payload, request_id="live", trace_id="a" * 32
        ),
    )
    monkeypatch.setattr(smoke, "service_database_url", lambda *_args, **_kwargs: "db")
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service, *, database_url, profile: migration_calls.append(
            (service, database_url, profile)
        ),
    )
    monkeypatch.setattr(smoke, "database_pool_settings", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(smoke, "build_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperationalEventStore", lambda _factory: events)

    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(),
        port_probe=lambda host, ports: {str(port): host == "provider" for port in ports},
        cases_document=_cases(),
    )

    assert result["status"] == "PASS", result
    assert result["database_profile"] == "test"
    assert result["test_database_residue_rows"] == 0
    assert migration_calls == [("nex-cx", "db", "test")]
    assert client.calls == 12
    assert len(engine.connection.calls) >= 4
    assert engine.disposed is True


def test_live_path_rejects_bad_configuration_route_and_connectivity(
    monkeypatch,
) -> None:
    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: ["bad"])
    assert smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(), cases_document=_cases()
    )["status"] == "FAIL"

    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: [])
    monkeypatch.setattr(smoke, "admit_model_artifact_revision_evidence", lambda _doc: {})
    monkeypatch.setattr(smoke, "_bind_provider", lambda *_args: None)
    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="http://provider/v1/chat/completions"),
    )
    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(), cases_document=_cases()
    )
    assert result["failure_detail"] == {"exception": "ValueError"}

    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="http://provider:9116/v1/chat/completions"),
    )
    result = smoke.run_gb2_s20qpab_limited_shadow_operations(
        _env(),
        port_probe=lambda _host, ports: {str(port): False for port in ports},
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"


def test_helpers_cleanup_loading_count_and_cli(tmp_path, monkeypatch, capsys) -> None:
    value = tmp_path / "value.json"
    value.write_text('{"ok": true}', encoding="utf-8")
    assert smoke._load(value) == {"ok": True}
    value.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError):
        smoke._load(value)

    engine = FakeEngine()
    bundle = json.loads(DEFAULT_ACTIVATION_BUNDLE_PATH.read_text(encoding="utf-8"))
    smoke._cleanup_events(engine, bundle["bundle_hash"])
    assert smoke._count_events(engine) == 0
    assert engine.connection.calls[0][1]["trace_id"] == smoke.TRACE_ID

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpab_limited_shadow_operations",
        lambda: {"status": "PASS", "live_execution": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpab_limited_shadow_operations",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpab_limited_shadow_operations",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.APPROVED_ENV: "1",
        smoke.OPERATOR_ENV: "operator-one",
    }


def _cases() -> dict[str, Any]:
    return json.loads(smoke.CASES_PATH.read_text(encoding="utf-8"))


def _state_store() -> tuple[
    OperationalRuntimeActivationStateStore, InMemoryOperationalEventStore
]:
    events = LockedOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    return OperationalRuntimeActivationStateStore(emitter=emitter, store=events), events
