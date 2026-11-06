from __future__ import annotations

import json
import stat
from types import SimpleNamespace
from typing import Any

import pytest
import run_gb2_s20qpan_answer_support_policy_steady_state_activation as smoke
from nex_cx.retrieval_answer_support_policy_cutover import (
    ROLLED_BACK,
    OperationalPolicyCutoverStateStore,
)
from nex_cx.retrieval_answer_support_policy_steady_state import (
    OperationalSteadyStateStateStore,
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


def test_protected_runner_activates_and_recovers_rollback() -> None:
    cutover_store, steady_store, events = _stores()
    client = FakeGenerationClient()

    result = smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
        _env(),
        cutover_state_store=cutover_store,
        steady_state_store=steady_store,
        generation_client=client,
        cases_document=_cases(),
    )

    assert result["status"] == "PASS"
    assert result["decision"] == (
        "ANSWER_SUPPORT_POLICY_STEADY_STATE_ACTIVATION_AND_ROLLBACK_ACCEPTED"
    )
    assert result["live_execution"]["sample_count"] == 4
    assert result["live_execution"]["provider_call_count"] == 4
    assert result["rollback"] == {
        "steady_state_state": ROLLED_BACK,
        "reason_code": "PROVIDER_ERROR",
        "restart_safe": True,
    }
    assert result["database_profile"] == "injected"
    assert result["test_database_residue_rows"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_algorithm_changed"] is False
    assert result["production_cutover_permitted"] is False
    assert client.calls == 4
    assert len(events.list_events()) > 0
    assert "rollback=verified" in smoke.summary_line(result)


def test_runner_requires_enablement_and_operator_approval() -> None:
    skipped = smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
        {}
    )
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")

    failed = smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
        {smoke.SMOKE_ENV: "1"}
    )
    assert failed["failure_code"] == "operator_approval_required"
    assert failed["steady_state_operations_active"] is False


def test_runner_fails_closed_on_cases_and_runtime(monkeypatch) -> None:
    cutover_store, steady_store, _events = _stores()
    result = smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
        _env(),
        cutover_state_store=cutover_store,
        steady_state_store=steady_store,
        generation_client=FakeGenerationClient(),
        cases_document={"cases": []},
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"]["stage"] == "SOURCE_ADMISSION"

    monkeypatch.setattr(
        smoke, "build_installed_answer_support_policy_steady_state", lambda **_: None
    )
    result = smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
        _env(),
        cutover_state_store=cutover_store,
        steady_state_store=steady_store,
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"
    assert "=fail" in smoke.summary_line(result)


def test_live_path_rejects_invalid_or_unreachable_provider(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: ["bad"])
    assert smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
        _env(), cases_document=_cases()
    )["status"] == "FAIL"

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
    assert smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
        _env(), cases_document=_cases()
    )["status"] == "FAIL"

    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="http://provider:9116/v1/chat/completions"),
    )
    result = smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
        _env(),
        port_probe=lambda _host, ports: {str(port): False for port in ports},
        cases_document=_cases(),
    )
    assert result["status"] == "FAIL"


def test_database_path_runs_migration_cleanup_and_residue_check(monkeypatch) -> None:
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

    result = smoke.run_gb2_s20qpan_answer_support_policy_steady_state_activation(
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


def test_helpers_and_cli(tmp_path, monkeypatch, capsys) -> None:
    authorization = smoke.load_steady_state_authorization(
        smoke.DEFAULT_AUTHORIZATION_PATH
    )
    ids = smoke._event_ids(authorization)
    assert len(ids) == 6
    assert len(set(ids.values())) == 6

    engine = FakeEngine()
    smoke._cleanup_events(engine, authorization)
    assert smoke._residue_count(engine, authorization) == 0
    assert len(engine.connection.calls) == 2

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpan_answer_support_policy_steady_state_activation",
        lambda: {"status": "PASS", "live_execution": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpan_answer_support_policy_steady_state_activation",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpan_answer_support_policy_steady_state_activation",
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


def _stores():
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    return (
        OperationalPolicyCutoverStateStore(emitter, events),
        OperationalSteadyStateStateStore(emitter, events),
        events,
    )
