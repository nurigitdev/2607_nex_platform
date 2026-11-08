from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
import run_gb2_s20qpaa_controlled_runtime_activation as smoke
from nex_cx.retrieval_answer_support_controlled_activation import (
    ACTIVATION_EVENT_TYPE,
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    ROLLED_BACK,
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


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def execute(self, statement: Any, parameters: dict[str, Any]) -> None:
        self.calls.append((statement, parameters))


class FakeBegin:
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

    def begin(self) -> FakeBegin:
        return FakeBegin(self.connection)

    def dispose(self) -> None:
        self.disposed = True


def test_controlled_activation_accepts_live_observation_restart_and_rollback() -> None:
    client = FakeGenerationClient()
    state_store, events = _state_store()

    result = smoke.run_gb2_s20qpaa_controlled_runtime_activation(
        _env(),
        state_store=state_store,
        generation_client=client,
        cases_document=_cases(),
    )

    assert result["status"] == "PASS"
    assert result["decision"] == (
        "CONTROLLED_RUNTIME_ACTIVATION_AND_ROLLBACK_ACCEPTED"
    )
    assert result["live_execution"]["sample_count"] == 4
    assert result["live_execution"]["provider_call_count"] == 4
    assert result["live_execution"]["peak_in_flight"] >= 1
    assert result["rollback"] == {
        "fault_status": "FAILED",
        "activation_state": ROLLED_BACK,
        "reason_code": "PROVIDER_ERROR",
        "restart_blocked": True,
    }
    assert result["database_profile"] == "injected"
    assert result["holdout_accessed"] is False
    assert result["user_visible_decision_change"] is False
    assert result["production_cutover_permitted"] is False
    assert client.calls == 4
    activation_events = events.list_events(event_type=ACTIVATION_EVENT_TYPE)
    assert {row["details"]["activation_state"] for row in activation_events} == {
        "ACTIVE",
        "ROLLED_BACK",
    }
    assert "rollback=verified" in smoke.summary_line(result)


def test_runner_requires_explicit_enablement_and_operator_approval() -> None:
    assert smoke.run_gb2_s20qpaa_controlled_runtime_activation({})["status"] == (
        "SKIPPED"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpaa_controlled_runtime_activation(
            {smoke.SMOKE_ENV: "1"}
        )["failure_code"]
        == "operator_approval_required"
    )


def test_runner_fails_closed_on_bad_case_count_and_redacts_details() -> None:
    state_store, _events = _state_store()
    result = smoke.run_gb2_s20qpaa_controlled_runtime_activation(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document={"cases": []},
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "controlled_runtime_activation_acceptance_failed"
    )
    assert result["failure_detail"] == {"exception": "ValueError"}
    assert result["provider_http_requests"] == 0
    assert "=fail" in smoke.summary_line(result)

    with pytest.raises(ValueError, match="leaked"):
        smoke._assert_redacted(
            {"secret": "api-secret"},
            {"NEX_MO_VLLM_API_KEY": "api-secret"},
            [],
        )


def test_runner_fails_closed_when_runtime_activation_or_observation_fails(
    monkeypatch,
) -> None:
    state_store, _events = _state_store()
    monkeypatch.setattr(
        smoke, "build_installed_controlled_answer_support_runtime", lambda **_kwargs: None
    )
    result = smoke.run_gb2_s20qpaa_controlled_runtime_activation(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"

    monkeypatch.undo()
    state_store, _events = _state_store()
    monkeypatch.setattr(
        smoke,
        "_observe",
        lambda _runtime, _case, _index: {
            "status": "FAILED",
            "provider_called": False,
        },
    )
    result = smoke.run_gb2_s20qpaa_controlled_runtime_activation(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"
    assert result["provider_http_requests"] == 0


def test_default_live_and_database_path_uses_admitted_provider_and_cleanup(
    monkeypatch,
) -> None:
    client = FakeGenerationClient()
    events = InMemoryOperationalEventStore()
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

    result = smoke.run_gb2_s20qpaa_controlled_runtime_activation(
        _env(),
        port_probe=lambda host, ports: {str(port): host == "provider" for port in ports},
        cases_document=_cases(),
    )

    assert result["status"] == "PASS"
    assert result["database_profile"] == "test"
    assert migration_calls == [("nex-cx", "db", "test")]
    assert client.calls == 4
    assert len(engine.connection.calls) == 2
    assert engine.disposed is True


def test_live_path_rejects_invalid_configuration_route_and_unreachable_provider(
    monkeypatch,
) -> None:
    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: ["bad"])
    assert smoke.run_gb2_s20qpaa_controlled_runtime_activation(
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
    result = smoke.run_gb2_s20qpaa_controlled_runtime_activation(
        _env(), cases_document=_cases()
    )
    assert result["failure_detail"] == {"exception": "ValueError"}

    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="http://provider:9116/v1/chat/completions"),
    )
    result = smoke.run_gb2_s20qpaa_controlled_runtime_activation(
        _env(),
        port_probe=lambda _host, ports: {str(port): False for port in ports},
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"


def test_helpers_cleanup_loading_percentile_and_cli(tmp_path, monkeypatch, capsys) -> None:
    assert smoke._p95([]) == 0.0
    assert smoke._p95([3.0, 1.0, 2.0]) == 3.0
    value = tmp_path / "value.json"
    value.write_text('{"ok": true}', encoding="utf-8")
    assert smoke._load(value) == {"ok": True}
    value.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError):
        smoke._load(value)

    engine = FakeEngine()
    bundle = json.loads(DEFAULT_ACTIVATION_BUNDLE_PATH.read_text(encoding="utf-8"))
    smoke._cleanup_events(engine, bundle["bundle_hash"])
    parameters = engine.connection.calls[0][1]
    assert parameters["trace_id"] == smoke.TRACE_ID
    assert parameters["active_id"] != parameters["rollback_id"]

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpaa_controlled_runtime_activation",
        lambda: {"status": "PASS", "live_execution": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpaa_controlled_runtime_activation",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpaa_controlled_runtime_activation",
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
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    return OperationalRuntimeActivationStateStore(emitter=emitter, store=events), events
