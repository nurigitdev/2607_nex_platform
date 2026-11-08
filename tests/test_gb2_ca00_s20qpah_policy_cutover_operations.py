from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_gb2_s20qpah_policy_cutover_operations as runner
from nex_cx.retrieval_answer_support_policy_cutover_operations import (
    DEFAULT_POLICY_PATH,
)
from nex_runtime import InMemoryOperationalEventStore
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_gb2_s20qpah_policy_cutover_operations import (
    APPROVED_ENV,
    OPERATOR_ENV,
    SMOKE_ENV,
    TRACE_ID,
    _assert_redacted,
    _cleanup_events,
    _failure,
    _LiveGenerationClient,
    _load,
    _residue_count,
    main,
    run_gb2_s20qpah_policy_cutover_operations,
    summary_line,
)
from sqlalchemy import create_engine, text
from test_nex_cx_retrieval_answer_support_policy_cutover import (
    FakeGenerationClient,
)


def test_disabled_and_missing_operator_approval_are_safe() -> None:
    skipped = run_gb2_s20qpah_policy_cutover_operations({})
    assert skipped["status"] == "SKIPPED"
    assert summary_line(skipped).endswith("skipped")

    rejected = run_gb2_s20qpah_policy_cutover_operations({SMOKE_ENV: "1"})
    assert rejected["status"] == "FAIL"
    assert rejected["failure_code"] == "operator_approval_required"
    assert rejected["provider_http_requests"] == 0


def test_injected_provider_and_event_store_complete_bounded_operations() -> None:
    result = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_ACCEPTED"
    assert result["operations_status"] == "REVIEW_REQUIRED"
    assert result["live_execution"]["sample_count"] == 12
    assert result["live_execution"]["provider_call_count"] == 12
    assert result["live_execution"]["peak_in_flight"] <= 4
    assert result["restart_safe"] is True
    assert result["holdout_accessed"] is False
    assert result["production_cutover_permitted"] is False
    assert all(result["checks"].values())
    assert summary_line(result).startswith("gb2_s20qpah_policy_cutover_operations=pass")
    assert "approved evidence directly" not in json.dumps(result)


def test_low_confidence_distribution_is_accepted_when_complete() -> None:
    result = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(ready=False),
        event_store=InMemoryOperationalEventStore(),
    )

    assert result["status"] == "PASS"
    assert result["live_execution"]["ready_count"] == 0
    assert result["live_execution"]["low_confidence_count"] == 12


def test_provider_failure_rejects_operations_without_leaking_details() -> None:
    result = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(error=RuntimeError("secret provider")),
        event_store=InMemoryOperationalEventStore(),
    )

    assert result["status"] == "FAIL"
    assert result["decision"] == "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_REJECTED"
    assert result["failed_checks"]
    assert "secret provider" not in json.dumps(result)
    assert summary_line(result).startswith("gb2_s20qpah_policy_cutover_operations=fail")


def test_policy_binding_drift_fails_before_provider_execution(tmp_path: Path) -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    policy["authorization_hash"] = "sha256:" + "0" * 64
    policy.pop("policy_hash")
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
    path = tmp_path / "drift.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    client = FakeGenerationClient()

    result = run_gb2_s20qpah_policy_cutover_operations(
        {
            **_enabled_env(),
            "NEX_CX_ANSWER_SUPPORT_POLICY_OPERATIONS_PATH": str(path),
        },
        generation_client=client,
        event_store=InMemoryOperationalEventStore(),
    )

    assert result["status"] == "FAIL"
    assert result["failure_detail"]["stage"] == "SOURCE_ADMISSION"
    assert result["provider_http_requests"] == 0
    assert client.calls == 0


def test_live_provider_admission_and_client_adapter(monkeypatch) -> None:
    fake = FakeGenerationClient()
    monkeypatch.setattr(runner, "_configuration_issues", lambda _env: [])
    monkeypatch.setattr(
        runner, "admit_model_artifact_revision_evidence", lambda _value: {}
    )
    monkeypatch.setattr(runner, "_bind_provider", lambda *_args: None)
    monkeypatch.setattr(
        runner.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="http://provider.local:9116"),
    )

    def execute(payload, *, request_id, trace_id, **_kwargs):
        return fake.create_generation(payload, request_id=request_id, trace_id=trace_id)

    monkeypatch.setattr(
        runner.remote_provider, "execute_remote_generation_request", execute
    )
    result = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        port_probe=lambda _host, ports: {str(ports[0]): True},
        event_store=InMemoryOperationalEventStore(),
    )

    assert result["status"] == "PASS"
    assert fake.calls == 12
    assert _LiveGenerationClient({}, None).requester is None


@pytest.mark.parametrize("failure", ["configuration", "route", "reachability"])
def test_live_provider_admission_fails_before_execution(
    monkeypatch, failure: str
) -> None:
    monkeypatch.setattr(
        runner,
        "_configuration_issues",
        lambda _env: ["missing"] if failure == "configuration" else [],
    )
    monkeypatch.setattr(
        runner, "admit_model_artifact_revision_evidence", lambda _value: {}
    )
    monkeypatch.setattr(runner, "_bind_provider", lambda *_args: None)
    monkeypatch.setattr(
        runner.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(
            url=("invalid" if failure == "route" else "http://provider.local:9116")
        ),
    )
    result = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        port_probe=lambda _host, ports: {str(ports[0]): failure != "reachability"},
        event_store=InMemoryOperationalEventStore(),
    )

    assert result["status"] == "FAIL"
    assert result["failure_detail"]["stage"] == "PROVIDER_ADMISSION"
    assert result["provider_http_requests"] == 0


def test_database_admission_path_and_cleanup_branch(monkeypatch) -> None:
    class Engine:
        disposed = False

        def dispose(self):
            self.disposed = True

    engine = Engine()
    store = InMemoryOperationalEventStore()
    cleanup_calls = []
    monkeypatch.setattr(runner, "service_database_url", lambda *_a, **_k: "test-db")
    monkeypatch.setattr(runner, "run_service_migrations", lambda *_a, **_k: None)
    monkeypatch.setattr(runner, "build_engine", lambda *_a, **_k: engine)
    monkeypatch.setattr(runner, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        runner, "SqlAlchemyOperationalEventStore", lambda _factory: store
    )
    monkeypatch.setattr(
        runner,
        "_cleanup_events",
        lambda *_a, **_k: cleanup_calls.append("cleanup"),
    )
    monkeypatch.setattr(runner, "_residue_count", lambda *_a, **_k: 0)

    result = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(), generation_client=FakeGenerationClient()
    )

    assert result["status"] == "PASS"
    assert result["database_profile"] == "test"
    assert len(cleanup_calls) == 3
    assert engine.disposed is True


def test_activation_and_restart_construction_failures_are_stage_safe(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runner, "build_installed_answer_support_policy_cutover", lambda **_kwargs: None
    )
    activation = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
    )
    assert activation["failure_detail"]["stage"] == "CUTOVER_OPERATIONS_ACTIVATION"

    monkeypatch.undo()
    real_builder = runner.build_installed_answer_support_policy_cutover
    calls = 0

    def first_only(**kwargs):
        nonlocal calls
        calls += 1
        return real_builder(**kwargs) if calls == 1 else None

    monkeypatch.setattr(
        runner, "build_installed_answer_support_policy_cutover", first_only
    )
    restart = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
    )
    assert restart["failure_detail"]["stage"] == "RESTART_RECOVERY"


def test_malformed_cases_and_store_failure_are_stage_safe() -> None:
    malformed = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
        cases_document={"cases": []},
    )
    assert malformed["status"] == "FAIL"
    assert malformed["failure_detail"]["stage"] == "SOURCE_ADMISSION"

    class FailingStore(InMemoryOperationalEventStore):
        def append(self, event):
            raise RuntimeError("database password")

    unavailable = run_gb2_s20qpah_policy_cutover_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=FailingStore(),
    )
    assert unavailable["status"] == "FAIL"
    assert "database password" not in json.dumps(unavailable)


def test_failure_helper_and_main_output(monkeypatch, tmp_path: Path, capsys) -> None:
    failure = _failure("forced", detail={"stage": "TEST"})
    assert failure["failure_detail"] == {"stage": "TEST"}

    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        "run_gb2_s20qpah_policy_cutover_operations.run_gb2_s20qpah_policy_cutover_operations",
        lambda: {"status": "PASS", "live_execution": {}},
    )
    assert main(["--output", str(output), "--summary"]) == 0
    assert "policy_cutover_operations=pass" in capsys.readouterr().out
    assert output.exists()

    previous = deepcopy(json.loads(output.read_text(encoding="utf-8")))
    monkeypatch.setattr(
        "run_gb2_s20qpah_policy_cutover_operations.run_gb2_s20qpah_policy_cutover_operations",
        lambda: {"status": "SKIPPED"},
    )
    assert main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == previous

    monkeypatch.setattr(
        "run_gb2_s20qpah_policy_cutover_operations.run_gb2_s20qpah_policy_cutover_operations",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert main(["--output", str(output)]) == 1


def test_cleanup_residue_redaction_and_load_helpers(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE service_operational_events (
                    event_id TEXT PRIMARY KEY,
                    service_id TEXT,
                    event_type TEXT,
                    trace_id TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO service_operational_events
                    (event_id, service_id, event_type, trace_id)
                VALUES
                    ('other', 'nex-cx', 'other', 'other'),
                    ('trace', 'nex-cx', :decision_type, :trace_id)
                """
            ),
            {"decision_type": runner.DECISION_EVENT_TYPE, "trace_id": TRACE_ID},
        )
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    assert (
        _residue_count(
            engine,
            authorization_hash=policy["authorization_hash"],
            window_id=policy["window_id"],
        )
        == 1
    )
    _cleanup_events(
        engine,
        authorization_hash=policy["authorization_hash"],
        window_id=policy["window_id"],
    )
    assert (
        _residue_count(
            engine,
            authorization_hash=policy["authorization_hash"],
            window_id=policy["window_id"],
        )
        == 0
    )

    with pytest.raises(ValueError):
        _assert_redacted(
            {"leak": "secret-key"},
            {"NEX_MO_VLLM_API_KEY": "secret-key"},
            [],
        )
    invalid = tmp_path / "list.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError):
        _load(invalid)


def _enabled_env() -> dict[str, str]:
    return {
        SMOKE_ENV: "1",
        APPROVED_ENV: "1",
        OPERATOR_ENV: "test-operator",
    }
