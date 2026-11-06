from __future__ import annotations

import json
import stat
from types import SimpleNamespace
from typing import Any

import run_gb2_s20qpao_answer_support_policy_steady_state_operations as smoke
from nex_runtime import InMemoryOperationalEventStore
from test_gb2_ca00_s20qpan_answer_support_policy_steady_state_activation import (
    FakeEngine,
)
from test_nex_cx_retrieval_answer_support_policy_cutover import FakeGenerationClient


def test_protected_runner_observes_cadence_restart_and_rollback() -> None:
    events = InMemoryOperationalEventStore()
    client = FakeGenerationClient()

    result = smoke.run_gb2_s20qpao_answer_support_policy_steady_state_operations(
        _env(),
        generation_client=client,
        event_store=events,
        cases_document=_cases(),
        activation_report=_activation(),
    )

    assert result["status"] == "PASS"
    assert result["decision"] == (
        "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_ACCEPTED"
    )
    assert result["live_execution"]["sample_count"] == 12
    assert result["live_execution"]["provider_call_count"] == 12
    assert result["operations_status"] == "OPERATOR_REVIEW_DUE"
    assert result["rollback_projection"] == "ROLLED_BACK"
    assert result["restart_safe"] is True
    assert result["database_profile"] == "injected"
    assert result["test_database_residue_rows"] == 0
    assert result["holdout_accessed"] is False
    assert result["production_cutover_permitted"] is False
    assert client.calls == 12
    assert len(events.list_events()) > 0
    assert "rollback=verified" in smoke.summary_line(result)


def test_runner_requires_enablement_operator_and_exact_activation() -> None:
    skipped = smoke.run_gb2_s20qpao_answer_support_policy_steady_state_operations(
        {}
    )
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")

    failed = smoke.run_gb2_s20qpao_answer_support_policy_steady_state_operations(
        {smoke.SMOKE_ENV: "1"}
    )
    assert failed["failure_code"] == "operator_approval_required"

    activation = _activation()
    activation["evidence_hash"] = "sha256:" + "0" * 64
    drift = smoke.run_gb2_s20qpao_answer_support_policy_steady_state_operations(
        _env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
        cases_document=_cases(),
        activation_report=activation,
    )
    assert drift["status"] == "FAIL"
    assert drift["failure_detail"]["stage"] == "SOURCE_ADMISSION"
    assert "=fail" in smoke.summary_line(drift)


def test_runner_rejects_incomplete_cases_and_live_provider(monkeypatch) -> None:
    incomplete = smoke.run_gb2_s20qpao_answer_support_policy_steady_state_operations(
        _env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
        cases_document={"cases": []},
        activation_report=_activation(),
    )
    assert incomplete["status"] == "FAIL"

    monkeypatch.setattr(smoke, "_configuration_issues", lambda _env: ["bad"])
    invalid = smoke.run_gb2_s20qpao_answer_support_policy_steady_state_operations(
        _env(),
        event_store=InMemoryOperationalEventStore(),
        cases_document=_cases(),
        activation_report=_activation(),
    )
    assert invalid["status"] == "FAIL"

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
    unreachable = smoke.run_gb2_s20qpao_answer_support_policy_steady_state_operations(
        _env(),
        port_probe=lambda _host, ports: {str(port): False for port in ports},
        event_store=InMemoryOperationalEventStore(),
        cases_document=_cases(),
        activation_report=_activation(),
    )
    assert unreachable["status"] == "FAIL"


def test_database_path_runs_migration_cleanup_and_residue_check(monkeypatch) -> None:
    engine = FakeEngine()
    events = InMemoryOperationalEventStore()
    migrations: list[tuple[str, str, str]] = []
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

    result = smoke.run_gb2_s20qpao_answer_support_policy_steady_state_operations(
        _env(),
        generation_client=FakeGenerationClient(),
        cases_document=_cases(),
        activation_report=_activation(),
    )

    assert result["status"] == "PASS"
    assert result["database_profile"] == "test"
    assert migrations == [("nex-cx", "db", "test")]
    assert len(engine.connection.calls) >= 3
    assert engine.disposed is True


def test_helpers_redaction_cleanup_and_cli(tmp_path, monkeypatch, capsys) -> None:
    policy = smoke.load_policy_steady_state_operations_policy(
        smoke.DEFAULT_POLICY_PATH
    )
    ids = smoke._event_ids(policy)
    assert len(ids) == 7
    assert len(set(ids.values())) == 7

    engine = FakeEngine()
    smoke._cleanup_events(engine, policy)
    assert smoke._residue_count(engine, policy) == 0
    assert len(engine.connection.calls) == 2

    leaked = {"secret": "private-key"}
    try:
        smoke._assert_redacted(
            leaked,
            {"NEX_MO_VLLM_API_KEY": "private-key"},
            [],
        )
    except ValueError as exc:
        assert "leaked" in str(exc)
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("secret leak was not rejected")

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpao_answer_support_policy_steady_state_operations",
        lambda: {"status": "PASS", "live_execution": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpao_answer_support_policy_steady_state_operations",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpao_answer_support_policy_steady_state_operations",
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


def _activation() -> dict[str, Any]:
    policy = smoke.load_policy_steady_state_operations_policy(
        smoke.DEFAULT_POLICY_PATH
    )
    source = policy["source_activation"]
    return {
        "evidence_schema_version": source["evidence_schema_version"],
        "status": source["status"],
        "decision": source["decision"],
        "evidence_hash": source["evidence_hash"],
        "steady_state_authorization_hash": policy[
            "steady_state_authorization_hash"
        ],
        "operator_decision_receipt_hash": source[
            "operator_decision_receipt_hash"
        ],
        "operations_profile_hash": policy["operations_profile_hash"],
        "selected_policy_hash": policy["selected_policy_hash"],
        "database_profile": source["database_profile"],
        "test_database_residue_rows": source["test_database_residue_rows"],
        "rollback": {"reason_code": source["rollback_reason"]},
        "next_boundary": source["next_boundary"],
    }
