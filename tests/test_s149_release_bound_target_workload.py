from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from nex_runtime.preproduction_live_workload import (
    PROTECTED_LIVE_OPERATION_COUNTS,
    PROTECTED_LIVE_PROVIDER_CALL_CAPS,
    build_protected_live_load_plan,
    build_protected_live_soak_profile,
)
from nex_runtime.preproduction_load import LoadRequest
from nex_runtime.preproduction_workload import admit_workload_profile
import run_s149_release_bound_target_workload as smoke


RC = "rc:s149:0123456789abcdef"
RELEASE_DIGEST = "sha256:" + "a" * 64


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_OA_TEST_DATABASE_URL": "postgresql://oa:private@localhost/oa_test",
        "NEX_AE_TEST_DATABASE_URL": "postgresql://ae:private@localhost/ae_test",
        "NEX_CX_TEST_DATABASE_URL": "postgresql://cx:private@localhost/cx_test",
        "NEX_MO_TEST_DATABASE_URL": "postgresql://mo:private@localhost/mo_test",
        "NEX_AG_TEST_DATABASE_URL": "postgresql://ag:private@localhost/ag_test",
        "NEX_MO_VLLM_API_KEY": "private-provider-key",
        "NEX_MO_VLLM_BASE_URL": "http://private-provider.example:9111",
    }


def _predecessor() -> dict[str, object]:
    return {
        "evidence_schema_version": "s149_single_host_live_acceptance.v1",
        "status": "PASS",
        "release_binding": {
            "release_candidate_id": RC,
            "release_set_digest": RELEASE_DIGEST,
        },
    }


def _write_predecessor(path: Path, value: object | None = None) -> None:
    path.write_text(json.dumps(_predecessor() if value is None else value))


def _sentinel(_env: object, phase: str) -> dict[str, object]:
    return {
        "status": "PASS",
        "phase": phase,
        "authenticated_ingestion_evidence_digest": "sha256:" + "b" * 64,
        "grounded_provider_evidence_digest": "sha256:" + "c" * 64,
    }


def _workload(
    _env: object, _admitted: object, _plan: object
) -> dict[str, object]:
    return {
        "status": "PASS",
        "elapsed_seconds": 1_800.1,
        "planned_seconds": 1_799.75,
        "measurement_window_reached": True,
        "load_result": {
            "status": "PASS",
            "metrics": {
                "request_count": 7_200,
                "success_count": 7_200,
                "error_count": 0,
                "error_rate": 0.0,
                "p95_latency_ms": 10.0,
                "throughput_rps": 4.0,
                "max_saturation_ratio": 0.4,
                "peak_active": 4,
                "duplicate_side_effect_count": 0,
                "isolation_violation_count": 0,
            },
            "outcome_counts": {
                "DENIED": 0,
                "ERROR": 0,
                "SUCCESS": 7_200,
                "TIMEOUT": 0,
            },
        },
        "statistics": {
            "operation_counts": dict(PROTECTED_LIVE_OPERATION_COUNTS),
            "operation_outcome_counts": {
                operation: {
                    "SUCCESS": count,
                    "ERROR": 0,
                    "TIMEOUT": 0,
                    "DENIED": 0,
                }
                for operation, count in PROTECTED_LIVE_OPERATION_COUNTS.items()
            },
            "database_call_counts": {
                "nex-oa": 1_920,
                "nex-ae-api": 1_200,
                "nex-cx": 1_200,
                "nex-mo": 480,
                "nex-ag": 1_920,
            },
            "provider_call_counts": dict(PROTECTED_LIVE_PROVIDER_CALL_CAPS),
        },
        "cleanup": {"status": "PASS", "deleted_row_count": 720, "residue_count": 0},
    }


def _run(tmp_path: Path, **kwargs: object) -> dict[str, object]:
    predecessor = tmp_path / "predecessor.json"
    _write_predecessor(predecessor)
    return smoke.run_s149_release_bound_target_workload(
        _env(),
        execute=True,
        predecessor_report=predecessor,
        report_path=tmp_path / "report.json",
        sentinel_runner=kwargs.get("sentinel_runner", _sentinel),  # type: ignore[arg-type]
        load_executor=kwargs.get("load_executor", _workload),  # type: ignore[arg-type]
    )


def _sqlite_engines():
    engines = {
        service_id: create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        for service_id in smoke.DATABASE_TARGETS
    }
    schemas = {
        "nex-oa": "CREATE TABLE oa_subjects (subject_id TEXT)",
        "nex-ae-api": "CREATE TABLE ae_artifacts (artifact_id TEXT)",
        "nex-cx": (
            "CREATE TABLE service_operational_events ("
            "event_id TEXT PRIMARY KEY, service_id TEXT, event_type TEXT, "
            "severity TEXT, request_id TEXT, message TEXT);"
            "CREATE TABLE cx_ingest_runs (run_id TEXT)"
        ),
        "nex-mo": "CREATE TABLE mo_provider_telemetry (provider_id TEXT)",
        "nex-ag": "CREATE TABLE ag_alerts (alert_id TEXT)",
    }
    for service_id, engine in engines.items():
        with engine.begin() as connection:
            for statement in schemas[service_id].split(";"):
                if statement.strip():
                    connection.execute(text(statement))
    return engines


def test_acceptance_requires_opt_in_and_test_profile(tmp_path: Path) -> None:
    skipped = smoke.run_s149_release_bound_target_workload({})
    wrong = smoke.run_s149_release_bound_target_workload(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "staging"},
        execute=True,
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in skipped["skip_reason"]
    assert wrong["failure_code"] == "profile_not_allowed"


def test_acceptance_passes_and_writes_redacted_metadata(tmp_path: Path) -> None:
    result = _run(tmp_path)
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["release_binding"]["release_candidate_id"] == RC
    assert result["profile"]["provider_call_caps"] == PROTECTED_LIVE_PROVIDER_CALL_CAPS
    assert result["execution_scope"]["production_capacity_claimed"] is False
    assert result["next_slice"] == "1492"
    assert "private-provider-key" not in serialized
    assert "postgresql://oa:private" not in serialized
    assert "provider.example" not in serialized
    assert json.loads((tmp_path / "report.json").read_text()) == result


def test_pre_workload_sentinel_failure_stops_before_load(tmp_path: Path) -> None:
    called = False

    def load(*_args):
        nonlocal called
        called = True
        return _workload(*_args)

    result = _run(
        tmp_path,
        sentinel_runner=lambda _env, phase: {"status": "FAIL", "phase": phase},
        load_executor=load,
    )

    assert result["failure_code"] == "pre_workload_sentinel_failed"
    assert called is False


def test_invalid_generated_plan_stops_before_sentinel(monkeypatch, tmp_path: Path) -> None:
    predecessor = tmp_path / "predecessor.json"
    _write_predecessor(predecessor)
    monkeypatch.setattr(
        smoke,
        "protected_live_plan_summary",
        lambda _plan: {"status": "FAIL"},
    )

    result = smoke.run_s149_release_bound_target_workload(
        _env(),
        execute=True,
        predecessor_report=predecessor,
        report_path=tmp_path / "report.json",
        sentinel_runner=lambda *_args: pytest.fail("sentinel must not run"),
        load_executor=_workload,
    )

    assert result["failure_code"] == "protected_live_plan_invalid"


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    [
        (lambda value: value.update(status="FAIL"), "target_workload_passed"),
        (
            lambda value: value["load_result"]["metrics"].update(request_count=7_199),
            "target_request_count_exact",
        ),
        (
            lambda value: value["statistics"].update(operation_counts={}),
            "operation_mix_exact",
        ),
        (
            lambda value: value["statistics"].update(provider_call_counts={}),
            "provider_call_caps_respected",
        ),
        (
            lambda value: value["statistics"]["operation_outcome_counts"][
                "grounded_generation"
            ].update(SUCCESS=0, ERROR=30),
            "provider_operations_all_succeeded",
        ),
        (
            lambda value: value.update(measurement_window_reached=False),
            "measurement_window_reached",
        ),
        (
            lambda value: value["load_result"]["metrics"].update(
                isolation_violation_count=1
            ),
            "zero_isolation_violations",
        ),
        (
            lambda value: value["load_result"]["metrics"].update(
                duplicate_side_effect_count=1
            ),
            "zero_duplicate_side_effects",
        ),
        (
            lambda value: value["cleanup"].update(residue_count=1),
            "zero_rehearsal_residue",
        ),
    ],
)
def test_acceptance_fails_closed_for_workload_drift(
    tmp_path: Path, mutation, failed_check: str
) -> None:
    workload = deepcopy(_workload(None, None, None))
    mutation(workload)

    result = _run(tmp_path, load_executor=lambda *_args: workload)

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False
    assert result["next_slice"] == "blocked"


def test_post_workload_sentinel_failure_is_not_admitted(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        sentinel_runner=lambda _env, phase: {
            "status": "PASS" if phase == "pre" else "FAIL",
            "phase": phase,
        },
    )

    assert result["checks"]["post_workload_journeys_passed"] is False
    assert result["status"] == "FAIL"


@pytest.mark.parametrize(
    "predecessor",
    [
        {"status": "FAIL", "release_binding": {}},
        {
            "status": "PASS",
            "release_binding": {
                "release_candidate_id": "wrong",
                "release_set_digest": RELEASE_DIGEST,
            },
        },
        {
            "status": "PASS",
            "release_binding": {
                "release_candidate_id": RC,
                "release_set_digest": "bad",
            },
        },
    ],
)
def test_invalid_predecessor_fails_closed(tmp_path: Path, predecessor: object) -> None:
    path = tmp_path / "predecessor.json"
    _write_predecessor(path, predecessor)

    result = smoke.run_s149_release_bound_target_workload(
        _env(),
        execute=True,
        predecessor_report=path,
        report_path=tmp_path / "report.json",
        sentinel_runner=_sentinel,
        load_executor=_workload,
    )

    assert result["failure_code"] == "release_bound_target_workload_execution_failed"
    assert result["diagnostics"] == {"exception_type": "ValueError"}


def test_runtime_executes_each_boundary_and_cleans_residue() -> None:
    engines = _sqlite_engines()
    calls: list[str] = []

    def embedding(*_args, **_kwargs):
        calls.append("embedding")
        return {"status": "ok"}

    def reranking(*_args, **_kwargs):
        calls.append("reranking")
        return {"status": "ok"}

    def generation(payload, **_kwargs):
        assert payload["reasoning_mode"] == "disabled"
        calls.append("generation")
        return {"status": "ok"}

    runtime = smoke.ProtectedLiveOperationRuntime(
        engines,
        {},
        embedding_executor=embedding,
        reranker_executor=reranking,
        generation_executor=generation,
        run_token="test-token",
    )
    outcomes = [
        runtime(LoadRequest(f"load:{index:024x}", operation, 0.0))
        for index, operation in enumerate(PROTECTED_LIVE_OPERATION_COUNTS, start=1)
    ]
    statistics = runtime.statistics()
    cleanup = runtime.cleanup()
    runtime.close()

    assert all(item.status == "SUCCESS" for item in outcomes)
    assert outcomes[list(PROTECTED_LIVE_OPERATION_COUNTS).index("document_ingestion")].side_effect_digest
    assert calls == ["embedding", "reranking", "generation"]
    assert statistics["operation_counts"] == {
        operation: 1 for operation in PROTECTED_LIVE_OPERATION_COUNTS
    }
    assert statistics["provider_call_counts"] == {
        "embedding": 1,
        "reranking": 1,
        "generation": 1,
    }
    assert statistics["operation_outcome_counts"]["grounded_generation"] == {
        "SUCCESS": 1,
        "ERROR": 0,
        "TIMEOUT": 0,
        "DENIED": 0,
    }
    assert cleanup == {"status": "PASS", "deleted_row_count": 1, "residue_count": 0}


def test_runtime_redacts_boundary_exceptions_and_unknown_operation() -> None:
    engines = _sqlite_engines()
    runtime = smoke.ProtectedLiveOperationRuntime(
        engines,
        {},
        embedding_executor=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("private")
        ),
    )

    provider = runtime(LoadRequest("load:" + "a" * 24, "hybrid_retrieval", 0.0))
    unknown = runtime(LoadRequest("load:" + "b" * 24, "unknown", 0.0))
    runtime.close()

    assert (provider.status, provider.reason_code) == ("ERROR", "provider_error")
    assert (unknown.status, unknown.reason_code) == ("ERROR", "database_error")


def test_actual_load_adapter_and_engine_guard(monkeypatch) -> None:
    engines = _sqlite_engines()
    profile = build_protected_live_soak_profile(RC)
    admitted = admit_workload_profile(profile, expected_release_candidate_id=RC)
    plan = (LoadRequest("load:" + "c" * 24, "auth_trust", 0.0),)

    result = smoke._run_actual_load(
        {},
        admitted,
        plan,
        engine_builder=lambda service_id, _database_env, _env: engines[service_id],
    )

    assert result["status"] == "PASS"
    assert result["measurement_window_reached"] is True
    assert result["statistics"]["operation_counts"] == {"auth_trust": 1}
    with pytest.raises(ValueError, match="missing protected database"):
        smoke._build_service_engine("nex-oa", "NEX_OA_TEST_DATABASE_URL", {})

    settings = object()
    expected_engine = object()
    monkeypatch.setattr(smoke, "database_pool_settings", lambda *_args, **_kwargs: settings)
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda database_url, **kwargs: (
            expected_engine
            if database_url == "sqlite:///test.db" and kwargs["pool_settings"] is settings
            else None
        ),
    )
    assert (
        smoke._build_service_engine(
            "nex-oa",
            "NEX_OA_TEST_DATABASE_URL",
            {"NEX_OA_TEST_DATABASE_URL": "sqlite:///test.db"},
        )
        is expected_engine
    )


def test_default_sentinel_adapters_and_redaction(monkeypatch) -> None:
    monkeypatch.setattr(smoke.ingestion, "run_smoke", lambda _env: {"status": "PASS"})
    monkeypatch.setattr(
        smoke.live_providers,
        "run_platform_release_candidate_live_providers",
        lambda _env: {"status": "PASS"},
    )
    passing = smoke._run_journey_sentinel({}, "pre")
    monkeypatch.setattr(smoke.ingestion, "run_smoke", lambda _env: {"status": "FAIL"})
    ingestion_failure = smoke._run_journey_sentinel({}, "pre")
    monkeypatch.setattr(smoke.ingestion, "run_smoke", lambda _env: {"status": "PASS"})
    monkeypatch.setattr(
        smoke.live_providers,
        "run_platform_release_candidate_live_providers",
        lambda _env: {"status": "FAIL"},
    )
    provider_failure = smoke._run_journey_sentinel({}, "post")

    assert passing["status"] == "PASS"
    assert ingestion_failure["failure_code"] == "authenticated_ingestion_sentinel_failed"
    assert provider_failure["failure_code"] == "grounded_provider_sentinel_failed"
    assert smoke._pool_saturation(next(iter(_sqlite_engines().values()))) == 0.0
    half_pool = type(
        "Engine",
        (),
        {"pool": type("Pool", (), {"size": lambda _self: 2, "checkedout": lambda _self: 1})()},
    )()
    full_pool = type(
        "Engine",
        (),
        {"pool": type("Pool", (), {"size": lambda _self: 2, "checkedout": lambda _self: 3})()},
    )()
    assert smoke._pool_saturation(half_pool) == 0.5
    assert smoke._pool_saturation(full_pool) == 1.0
    assert smoke._mapping([]) == {}
    assert smoke._int_mapping({"ok": 1, "bool": True, "negative": -1}) == {"ok": 1}
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted(
            {"leak": "private-provider-key"}, _env()
        )


def test_summary_and_main(monkeypatch, capsys, tmp_path: Path) -> None:
    passing = _run(tmp_path)
    skipped = smoke.run_s149_release_bound_target_workload({})

    assert smoke.summary_line(skipped) == "s149_release_bound_target_workload=skipped"
    assert smoke.summary_line(passing) == (
        "s149_release_bound_target_workload=pass checks=13/13 "
        "requests=7200/7200 residue=0 next=1492"
    )
    monkeypatch.setattr(
        smoke,
        "run_s149_release_bound_target_workload",
        lambda **_kwargs: passing,
    )
    assert smoke.main(["--summary", "--report-path", str(tmp_path / "x")]) == 0
    assert "s149_release_bound_target_workload=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_s149_release_bound_target_workload",
        lambda **_kwargs: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
