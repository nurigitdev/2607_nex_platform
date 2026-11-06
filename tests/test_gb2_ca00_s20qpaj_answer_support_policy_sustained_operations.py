from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_gb2_s20qpaj_answer_support_policy_sustained_operations as runner
from nex_cx.retrieval_answer_support_policy_sustained_operations import (
    DEFAULT_POLICY_PATH,
)
from nex_runtime import InMemoryOperationalEventStore
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_gb2_s20qpaj_answer_support_policy_sustained_operations import (
    APPROVED_ENV,
    OPERATOR_ENV,
    SMOKE_ENV,
    TRACE_ID,
    _assert_redacted,
    _cleanup_events,
    _failure,
    _LiveGenerationClient,
    _load,
    _require_exact_bindings,
    _residue_count,
    main,
    run_gb2_s20qpaj_answer_support_policy_sustained_operations,
    summary_line,
)
from sqlalchemy import create_engine, text
from test_nex_cx_retrieval_answer_support_policy_cutover import (
    FakeGenerationClient,
)


def test_disabled_and_missing_operator_approval_are_safe() -> None:
    skipped = run_gb2_s20qpaj_answer_support_policy_sustained_operations({})
    assert skipped["status"] == "SKIPPED"
    assert summary_line(skipped).endswith("skipped")

    rejected = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        {SMOKE_ENV: "1"}
    )
    assert rejected["status"] == "FAIL"
    assert rejected["failure_code"] == "operator_approval_required"
    assert rejected["provider_http_requests"] == 0


def test_injected_provider_and_event_store_complete_sustained_cadence() -> None:
    result = _run_injected()

    assert result["status"] == "PASS"
    assert result["decision"] == "ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS_ACCEPTED"
    assert result["operations_status"] == "OPERATOR_REVIEW_DUE"
    assert result["health_status"] == "ATTENTION"
    assert result["live_execution"]["sample_count"] == 12
    assert result["live_execution"]["provider_call_count"] == 12
    assert result["live_execution"]["peak_in_flight"] <= 4
    assert result["restart_safe"] is True
    assert result["runtime_stopped_at_review_cadence"] is False
    assert result["rollback_contract_preserved"] is True
    assert result["holdout_accessed"] is False
    assert result["production_cutover_permitted"] is False
    assert all(result["checks"].values())
    assert summary_line(result).startswith("gb2_s20qpaj_policy_sustained_operations=pass")
    assert "approved evidence directly" not in json.dumps(result)


def test_low_confidence_distribution_is_accepted_when_complete() -> None:
    result = _run_injected(generation_client=FakeGenerationClient(ready=False))
    assert result["status"] == "PASS"
    assert result["live_execution"]["ready_count"] == 0
    assert result["live_execution"]["low_confidence_count"] == 12


def test_provider_failure_rejects_operations_without_leaking_details() -> None:
    result = _run_injected(
        generation_client=FakeGenerationClient(error=RuntimeError("secret provider"))
    )
    assert result["status"] == "FAIL"
    assert result["decision"] == "ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS_REJECTED"
    assert result["failed_checks"]
    assert "secret provider" not in json.dumps(result)
    assert summary_line(result).startswith("gb2_s20qpaj_policy_sustained_operations=fail")


def test_exact_review_receipt_and_report_are_immutable_inputs() -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    authorization = {
        "authorization_hash": policy["authorization_hash"],
        "activation_bundle_hash": policy["activation_bundle_hash"],
        "selected_policy_hash": policy["selected_policy_hash"],
    }
    activation = {
        "bundle_hash": policy["activation_bundle_hash"],
        "selected_policy": {"policy_hash": policy["selected_policy_hash"]},
    }
    _require_exact_bindings(
        policy, authorization, activation, _review_report(), _review_receipt()
    )

    drift = _review_receipt()
    drift["runtime_changed"] = True
    with pytest.raises(ValueError):
        _require_exact_bindings(
            policy, authorization, activation, _review_report(), drift
        )


def test_policy_binding_drift_fails_before_provider_execution(tmp_path: Path) -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    policy["authorization_hash"] = "sha256:" + "0" * 64
    policy.pop("policy_hash")
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
    path = tmp_path / "drift.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    client = FakeGenerationClient()

    result = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        {
            **_enabled_env(),
            "NEX_CX_ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS_PATH": str(path),
        },
        generation_client=client,
        event_store=InMemoryOperationalEventStore(),
        review_report=_review_report(),
        review_receipt=_review_receipt(),
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
    result = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        _enabled_env(),
        port_probe=lambda _host, ports: {str(ports[0]): True},
        event_store=InMemoryOperationalEventStore(),
        review_report=_review_report(),
        review_receipt=_review_receipt(),
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
    result = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        _enabled_env(),
        port_probe=lambda _host, ports: {str(ports[0]): failure != "reachability"},
        event_store=InMemoryOperationalEventStore(),
        review_report=_review_report(),
        review_receipt=_review_receipt(),
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
        runner, "_cleanup_events", lambda *_a, **_k: cleanup_calls.append("cleanup")
    )
    monkeypatch.setattr(runner, "_residue_count", lambda *_a, **_k: 0)

    result = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        review_report=_review_report(),
        review_receipt=_review_receipt(),
    )
    assert result["status"] == "PASS"
    assert result["database_profile"] == "test"
    assert len(cleanup_calls) == 3
    assert engine.disposed is True


def test_activation_and_restart_construction_failures_are_stage_safe(monkeypatch) -> None:
    monkeypatch.setattr(
        runner, "build_installed_answer_support_policy_cutover", lambda **_kwargs: None
    )
    activation = _run_injected()
    assert activation["failure_detail"]["stage"] == "SUSTAINED_OPERATIONS_ACTIVATION"

    monkeypatch.undo()
    real_builder = runner.build_installed_answer_support_policy_cutover
    calls = 0

    def first_only(**kwargs):
        nonlocal calls
        calls += 1
        return real_builder(**kwargs) if calls == 1 else None

    monkeypatch.setattr(runner, "build_installed_answer_support_policy_cutover", first_only)
    restart = _run_injected()
    assert restart["failure_detail"]["stage"] == "RESTART_RECOVERY"


def test_malformed_cases_review_drift_and_store_failure_are_stage_safe() -> None:
    malformed = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
        cases_document={"cases": []},
        review_report=_review_report(),
        review_receipt=_review_receipt(),
    )
    assert malformed["failure_detail"]["stage"] == "SOURCE_ADMISSION"

    too_few_cases = _load(runner.CASES_PATH)
    too_few_cases["cases"] = too_few_cases["cases"][:3]
    insufficient = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
        cases_document=too_few_cases,
        review_report=_review_report(),
        review_receipt=_review_receipt(),
    )
    assert insufficient["failure_detail"]["stage"] == "SOURCE_ADMISSION"

    drift = _review_report()
    drift["runtime_change_permitted"] = True
    rejected = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
        review_report=drift,
        review_receipt=_review_receipt(),
    )
    assert rejected["failure_detail"]["stage"] == "SOURCE_ADMISSION"

    class FailingStore(InMemoryOperationalEventStore):
        def append(self, event):
            raise RuntimeError("database password")

    unavailable = run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        _enabled_env(),
        generation_client=FakeGenerationClient(),
        event_store=FailingStore(),
        review_report=_review_report(),
        review_receipt=_review_receipt(),
    )
    assert unavailable["status"] == "FAIL"
    assert "database password" not in json.dumps(unavailable)


def test_failure_helper_and_main_output(monkeypatch, tmp_path: Path, capsys) -> None:
    failure = _failure("forced", detail={"stage": "TEST"})
    assert failure["failure_detail"] == {"stage": "TEST"}

    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        runner,
        "run_gb2_s20qpaj_answer_support_policy_sustained_operations",
        lambda: {"status": "PASS", "live_execution": {}},
    )
    assert main(["--output", str(output), "--summary"]) == 0
    assert "policy_sustained_operations=pass" in capsys.readouterr().out

    previous = deepcopy(json.loads(output.read_text(encoding="utf-8")))
    monkeypatch.setattr(
        runner,
        "run_gb2_s20qpaj_answer_support_policy_sustained_operations",
        lambda: {"status": "SKIPPED"},
    )
    assert main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == previous

    monkeypatch.setattr(
        runner,
        "run_gb2_s20qpaj_answer_support_policy_sustained_operations",
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
            window_id=policy["sustained_window_id"],
        )
        == 1
    )
    _cleanup_events(
        engine,
        authorization_hash=policy["authorization_hash"],
        window_id=policy["sustained_window_id"],
    )
    assert (
        _residue_count(
            engine,
            authorization_hash=policy["authorization_hash"],
            window_id=policy["sustained_window_id"],
        )
        == 0
    )

    with pytest.raises(ValueError):
        _assert_redacted(
            {"leak": "secret-key"}, {"NEX_MO_VLLM_API_KEY": "secret-key"}, []
        )
    invalid = tmp_path / "list.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError):
        _load(invalid)


def _run_injected(generation_client=None):
    return run_gb2_s20qpaj_answer_support_policy_sustained_operations(
        _enabled_env(),
        generation_client=generation_client or FakeGenerationClient(),
        event_store=InMemoryOperationalEventStore(),
        review_report=_review_report(),
        review_receipt=_review_receipt(),
    )


def _enabled_env() -> dict[str, str]:
    return {
        SMOKE_ENV: "1",
        APPROVED_ENV: "1",
        OPERATOR_ENV: "test-operator",
    }


def _review_receipt() -> dict:
    return {
        "approved_scope": "CONTROLLED_ANSWER_SUPPORT_POLICY_OPERATIONS_CONTINUATION_ONLY",
        "controlled_continuation_approved": True,
        "decided_at": "2026-11-06T04:21:12.160220Z",
        "decision": "CONTINUE_CONTROLLED_ANSWER_SUPPORT_POLICY_OPERATIONS_APPROVED",
        "decision_status": "APPROVED_CONTINUATION_NOT_PRODUCTION",
        "design_hash": "sha256:e01cd96bf3dd1ab6021f4a3435697218f89bcb4704ea7d0496ffe554ec738228",
        "manifest_hash": "sha256:98ea9425b80c67ea213add6bbca6f161ce549779cf2e9f0af11f4b8b57affbf3",
        "next_boundary": "ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS",
        "operator_decision_hash": "sha256:5a4285d0b75fe10676ae00a43ab8c41016bcb8db61ec911e8ba947b467b87843",
        "production_cutover_permitted": False,
        "receipt_hash": "sha256:36c97a3f3033d8963edea0931f05378799e2dfd273bb12cb65599ccaf5899ade",
        "receipt_schema_version": "cx_answer_support_policy_cutover_operations_operator_review_receipt.v1",
        "rollback_contract_preserved": True,
        "runtime_changed": False,
        "source_evidence_hash": "sha256:0c1ba91b7cf5b537db9f0b3cd24beef651372c2ef8f59aa1422a3048fac14827",
        "source_report_document_hash": "sha256:eb5ab8ca7bf990cd53612094da1c15535c42fe21471240f8c52692d643cdd2ec",
        "status": "PASS",
    }


def _review_report() -> dict:
    return {
        "activation_bundle_hash": "sha256:6d5c631c9e18418ae2787d4053d06cdf87cc49a3cbc67aea6258b11f29893a06",
        "approved_scope": "CONTROLLED_ANSWER_SUPPORT_POLICY_OPERATIONS_CONTINUATION_ONLY",
        "authorization_hash": "sha256:fe45b9267af3e81095b957c0488ee86dba7f88114b3fff99708ccc812108fc00",
        "checks": {
            name: True
            for name in (
                "bounded_c4_profile_verified",
                "bounded_window_complete",
                "controlled_continuation_scope_verified",
                "e2e_p95_slo_verified",
                "exact_operations_policy_binding_verified",
                "permission_and_evidence_preservation_verified",
                "production_cutover_prohibited",
                "provider_p95_slo_verified",
                "restart_recovery_verified",
                "rollback_contract_preserved",
                "runtime_unchanged",
                "source_report_integrity_verified",
                "test_database_zero_residue_verified",
                "zero_provider_failure_or_fallback_verified",
            )
        },
        "controlled_continuation_permitted": True,
        "current_policy": "ANSWER_SUPPORT_POLICY_CUTOVER_ACTIVE",
        "database_calls": 0,
        "decision": "CONTINUE_CONTROLLED_ANSWER_SUPPORT_POLICY_OPERATIONS_APPROVED",
        "decision_receipt_hash": "sha256:36c97a3f3033d8963edea0931f05378799e2dfd273bb12cb65599ccaf5899ade",
        "decision_status": "APPROVED_CONTINUATION_NOT_PRODUCTION",
        "design_hash": "sha256:e01cd96bf3dd1ab6021f4a3435697218f89bcb4704ea7d0496ffe554ec738228",
        "evidence_schema_version": "gb2_s20qpai_policy_cutover_operations_operator_review.v1",
        "failed_checks": [],
        "holdout_accessed": False,
        "manifest_hash": "sha256:98ea9425b80c67ea213add6bbca6f161ce549779cf2e9f0af11f4b8b57affbf3",
        "manifest_schema_version": "cx_answer_support_policy_cutover_operations_review_manifest.v1",
        "next_boundary": "ANSWER_SUPPORT_POLICY_SUSTAINED_OPERATIONS",
        "observed_metrics": {
            "e2e_p95_latency_ms": 11422.5,
            "elapsed_seconds": 33.589883,
            "feedback_p95_latency_ms": 1.149283,
            "low_confidence_count": 3,
            "peak_in_flight": 4,
            "provider_call_count": 12,
            "provider_p95_latency_ms": 11340.367061,
            "ready_count": 9,
            "sample_count": 12,
        },
        "operations_policy_hash": "sha256:7f6dd67840bf1de1ba0d5b9f2d6c5d66afffba6e0ebc5bdb71620d2c7259e439",
        "operator_decision_hash": "sha256:5a4285d0b75fe10676ae00a43ab8c41016bcb8db61ec911e8ba947b467b87843",
        "production_cutover_permitted": False,
        "provider_calls": 0,
        "reason_codes": [
            "BOUNDED_OPERATIONS_WINDOW_COMPLETE",
            "ZERO_PROVIDER_FAILURES_OR_FALLBACKS",
            "PROVIDER_AND_E2E_SLOS_MET",
            "RESTART_RECOVERY_VERIFIED",
            "PERMISSION_AND_EVIDENCE_PRESERVED",
            "ROLLBACK_CONTRACT_REMAINS_AUTHORITATIVE",
            "SEPARATE_PRODUCTION_RELEASE_DECISION_REQUIRED",
        ],
        "rollback_contract_preserved": True,
        "runtime_change_permitted": False,
        "selected_policy_hash": "sha256:c81f7a0bf3d3d72d7bbc5de1f564ada3b415f2206689c1939fcb925f172168cb",
        "slice_id": "GB2-CA00-S20Q-P-AI",
        "source_evidence_hash": "sha256:0c1ba91b7cf5b537db9f0b3cd24beef651372c2ef8f59aa1422a3048fac14827",
        "source_report_document_hash": "sha256:eb5ab8ca7bf990cd53612094da1c15535c42fe21471240f8c52692d643cdd2ec",
        "status": "PASS",
    }
