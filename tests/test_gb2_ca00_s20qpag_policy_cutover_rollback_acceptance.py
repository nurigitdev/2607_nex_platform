from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
import run_gb2_s20qpag_policy_cutover_rollback_acceptance as smoke
from nex_cx.retrieval_answer_support_policy_cutover import (
    CUTOVER_EVENT_TYPE,
    ROLLED_BACK,
    OperationalPolicyCutoverStateStore,
)
from nex_runtime import InMemoryOperationalEventStore, OperationalEventEmitter
from test_nex_cx_retrieval_answer_support_policy_cutover import FakeGenerationClient


class FakeResult:
    def scalar_one(self) -> int:
        return 0


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def execute(self, statement: Any, parameters: dict[str, Any]) -> FakeResult:
        self.calls.append((statement, parameters))
        return FakeResult()


class FakeContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *_args: object) -> None:
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


def test_protected_runner_accepts_cutover_and_restart_safe_rollback() -> None:
    state_store, events = _state_store()
    client = FakeGenerationClient()

    result = smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance(
        _env(),
        state_store=state_store,
        generation_client=client,
        cases_document=_cases(),
    )

    assert result["status"] == "PASS"
    assert result["decision"] == ("ANSWER_SUPPORT_POLICY_CUTOVER_AND_ROLLBACK_ACCEPTED")
    assert result["live_execution"]["sample_count"] == 4
    assert result["live_execution"]["provider_call_count"] == 4
    assert result["rollback"] == {
        "cutover_state": ROLLED_BACK,
        "reason_code": "PROVIDER_ERROR",
        "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
        "restart_safe": True,
    }
    assert result["database_profile"] == "injected"
    assert result["test_database_residue_rows"] == 0
    assert result["holdout_accessed"] is False
    assert result["user_visible_policy_change"] is True
    assert result["production_cutover_permitted"] is False
    assert client.calls == 4
    assert {
        row["details"]["cutover_state"]
        for row in events.list_events(event_type=CUTOVER_EVENT_TYPE)
    } == {"ACTIVE", "ROLLED_BACK"}
    assert "rollback=verified" in smoke.summary_line(result)


def test_runner_requires_enablement_and_explicit_operator_approval() -> None:
    assert (
        smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance({})["status"]
        == "SKIPPED"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    result = smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance(
        {smoke.SMOKE_ENV: "1"}
    )
    assert result["failure_code"] == "operator_approval_required"


def test_runner_fails_closed_on_case_or_runtime_error(monkeypatch) -> None:
    state_store, _events = _state_store()
    result = smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document={"cases": []},
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {
        "exception": "ValueError",
        "stage": "SOURCE_ADMISSION",
    }

    monkeypatch.setattr(
        smoke, "build_installed_answer_support_policy_cutover", lambda **_kwargs: None
    )
    result = smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance(
        _env(),
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"
    assert "=fail" in smoke.summary_line(result)


def test_live_path_rejects_invalid_route_or_unreachable_provider(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: ["bad"])
    assert (
        smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance(
            _env(), cases_document=_cases()
        )["status"]
        == "FAIL"
    )

    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: [])
    monkeypatch.setattr(
        smoke, "admit_model_artifact_revision_evidence", lambda _value: {}
    )
    monkeypatch.setattr(smoke, "_bind_provider", lambda *_args: None)
    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="http://provider/v1/chat/completions"),
    )
    assert (
        smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance(
            _env(), cases_document=_cases()
        )["status"]
        == "FAIL"
    )

    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="http://provider:9116/v1/chat/completions"),
    )
    result = smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance(
        _env(),
        port_probe=lambda _host, ports: {str(port): False for port in ports},
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"


def test_default_live_database_path_runs_migration_cleanup_and_residue_check(
    monkeypatch,
) -> None:
    engine = FakeEngine()
    events = InMemoryOperationalEventStore()
    client = FakeGenerationClient()
    migrations: list[tuple[str, str, str]] = []
    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: [])
    monkeypatch.setattr(
        smoke, "admit_model_artifact_revision_evidence", lambda _value: {}
    )
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
            payload, request_id="live", trace_id="b" * 32
        ),
    )
    monkeypatch.setattr(smoke, "service_database_url", lambda *_args, **_kwargs: "db")
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda service, *, database_url, profile: migrations.append(
            (service, database_url, profile)
        ),
    )
    monkeypatch.setattr(smoke, "database_pool_settings", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(smoke, "build_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        smoke, "SqlAlchemyOperationalEventStore", lambda _factory: events
    )

    result = smoke.run_gb2_s20qpag_policy_cutover_rollback_acceptance(
        _env(),
        port_probe=lambda host, ports: {
            str(port): host == "provider" for port in ports
        },
        cases_document=_cases(),
    )

    assert result["status"] == "PASS"
    assert result["database_profile"] == "test"
    assert migrations == [("nex-cx", "db", "test")]
    assert client.calls == 4
    assert len(engine.connection.calls) >= 3
    assert engine.disposed is True


def test_helpers_redaction_loading_percentile_and_cli(
    tmp_path, monkeypatch, capsys
) -> None:
    assert smoke._p95([]) == 0.0
    assert smoke._p95([3.0, 1.0, 2.0]) == 3.0
    value = tmp_path / "value.json"
    value.write_text('{"ok": true}', encoding="utf-8")
    assert smoke._load(value) == {"ok": True}
    value.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError):
        smoke._load(value)
    with pytest.raises(ValueError, match="leaked"):
        smoke._assert_redacted(
            {"secret": "api-secret"},
            {"NEX_MO_VLLM_API_KEY": "api-secret"},
            [],
        )

    engine = FakeEngine()
    authorization_hash = "sha256:" + "a" * 64
    smoke._cleanup_events(engine, authorization_hash)
    assert smoke._residue_count(engine, authorization_hash) == 0
    assert (
        engine.connection.calls[0][1]["active_id"]
        != (engine.connection.calls[0][1]["rollback_id"])
    )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpag_policy_cutover_rollback_acceptance",
        lambda: {"status": "PASS", "live_execution": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpag_policy_cutover_rollback_acceptance",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpag_policy_cutover_rollback_acceptance",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.APPROVED_ENV: "1",
        smoke.OPERATOR_ENV: "operator-one",
    }


def _cases() -> dict[str, object]:
    return json.loads(smoke.CASES_PATH.read_text(encoding="utf-8"))


def _state_store() -> tuple[
    OperationalPolicyCutoverStateStore, InMemoryOperationalEventStore
]:
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    return OperationalPolicyCutoverStateStore(emitter, events), events
