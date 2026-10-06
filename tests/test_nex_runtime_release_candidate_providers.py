from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

import run_platform_release_candidate_live_providers as runner
from nex_runtime.release_candidate_providers import (
    RELEASE_CANDIDATE_PROVIDER_SCHEMA_VERSION,
    build_release_candidate_live_provider_evidence,
)


def passing_provider() -> dict[str, object]:
    providers = {
        capability: {
            "model_revision": f"replaceable-{capability}-revision",
            "status": "PASS",
        }
        for capability in ("embedding", "reranking", "generation")
    }
    return {
        "status": "PASS",
        "activation": {"enabled": True},
        "stage_status": {
            "embedding": "PASS",
            "reranking": "PASS",
            "generation": "PASS",
        },
        "provider_evidence": {
            "providers": providers,
            "telemetry": [
                {"capability": capability, "failure_count": 0}
                for capability in providers
            ],
        },
    }


def passing_retrieval() -> dict[str, object]:
    return {
        "status": "PASS",
        "database_identity": {"database": "nex_cx_test", "role": "nex_cx_user"},
        "checks": {"hybrid_ready": True, "cleanup_complete": True},
        "calibration": {
            "status": "PASSED",
            "sample_count": 20,
            "positive_count": 10,
            "negative_count": 10,
            "profile_hash": "a" * 64,
            "selected_threshold": 0.72,
        },
    }


def passing_grounded() -> dict[str, object]:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "live_provider_required": True,
        "checks": {"grounded": True, "cleanup_residue_free": True},
        "summary": {"provider_capability_count": 3, "database_count": 2},
        "post_journey_residue": {"ae": 0, "cx": 0, "files": 0},
    }


def test_builds_model_independent_metadata_only_live_provider_gate() -> None:
    result = build_release_candidate_live_provider_evidence(
        passing_provider(),
        passing_retrieval(),
        passing_grounded(),
        observed_at=datetime(2026, 10, 6, 2, 3, 4, tzinfo=UTC),
    )

    assert result["schema_version"] == RELEASE_CANDIDATE_PROVIDER_SCHEMA_VERSION
    assert result["status"] == "PASS"
    assert result["failure_code"] is None
    gate = result["gate_evidence"]
    assert gate["gate_id"] == "live_provider_matrix"
    assert gate["actual_execution"] is True
    assert gate["private_payload_included"] is False
    assert gate["observed_at"] == "2026-10-06T02:03:04Z"
    assert gate["metrics"]["provider_capability_count"] == 3
    assert gate["metrics"]["failed_provider_count"] == 0
    assert gate["metrics"]["calibration_sample_count"] == 20
    assert gate["model_binding"]["model_identity_controls_acceptance"] is False
    assert len(gate["model_binding"]["binding_sha256"]) == 64
    serialized = json.dumps(result)
    assert "replaceable-embedding-revision" not in serialized
    assert len(gate["evidence_digest"]) == 64


@pytest.mark.parametrize(
    ("source", "mutation", "check"),
    (
        ("provider", lambda value: value.update(status="FAIL"), "provider_source_passed"),
        (
            "provider",
            lambda value: value["provider_evidence"]["providers"].pop("generation"),
            "three_capabilities_observed",
        ),
        (
            "provider",
            lambda value: value["stage_status"].update(reranking="FAIL"),
            "provider_stages_passed",
        ),
        (
            "provider",
            lambda value: value["provider_evidence"]["telemetry"][0].update(
                failure_count=1
            ),
            "provider_telemetry_failure_free",
        ),
        (
            "provider",
            lambda value: value["provider_evidence"]["providers"]["embedding"].update(
                model_revision=""
            ),
            "model_bindings_observed_not_pinned",
        ),
        ("retrieval", lambda value: value.update(status="FAIL"), "retrieval_source_passed"),
        (
            "retrieval",
            lambda value: value.update(database_identity={}),
            "actual_cx_test_database",
        ),
        (
            "retrieval",
            lambda value: value.update(checks={"hybrid_ready": False}),
            "retrieval_checks_passed",
        ),
        (
            "retrieval",
            lambda value: value["calibration"].update(sample_count=19),
            "multisignal_calibration_passed",
        ),
        ("grounded", lambda value: value.update(status="FAIL"), "grounded_source_passed"),
        (
            "grounded",
            lambda value: value.update(checks={"grounded": False}),
            "grounded_checks_passed",
        ),
        (
            "grounded",
            lambda value: value["summary"].update(provider_capability_count=2),
            "grounded_three_capabilities",
        ),
        (
            "grounded",
            lambda value: value["post_journey_residue"].update(files=1),
            "grounded_residue_free",
        ),
        (
            "provider",
            lambda value: value.update(activation={"enabled": False}),
            "protected_execution_observed",
        ),
    ),
)
def test_gate_fails_closed_for_incomplete_source_evidence(
    source: str,
    mutation,
    check: str,
) -> None:
    sources = {
        "provider": passing_provider(),
        "retrieval": passing_retrieval(),
        "grounded": passing_grounded(),
    }
    mutation(sources[source])

    result = build_release_candidate_live_provider_evidence(
        sources["provider"], sources["retrieval"], sources["grounded"]
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "release_candidate_live_provider_failed"
    assert result["checks"][check] is False


def test_invalid_shapes_are_bounded_and_naive_time_is_normalized() -> None:
    result = build_release_candidate_live_provider_evidence(
        {"status": "PASS", "provider_evidence": {"telemetry": {}}},
        {"checks": [], "calibration": {"sample_count": True}},
        {"post_journey_residue": [], "actual_postgres": True},
        observed_at=datetime(2026, 10, 6, 2, 3, 4),
    )
    assert result["status"] == "FAIL"
    assert result["gate_evidence"]["observed_at"].endswith("Z")
    assert result["gate_evidence"]["metrics"]["calibration_sample_count"] == 0


def test_runner_is_opt_in_and_enables_all_existing_protected_sources() -> None:
    skipped = runner.run_platform_release_candidate_live_providers({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_live_provider_execution"] is False
    assert runner.summary_line(skipped).endswith("next=1397")

    captured: list[dict[str, str]] = []

    def provider_source(env):
        captured.append(dict(env))
        return passing_provider()

    result = runner.run_platform_release_candidate_live_providers(
        {runner.ENABLE_ENV: "1"},
        provider_runner=provider_source,
        retrieval_runner=lambda env: passing_retrieval(),
        grounded_runner=lambda env: passing_grounded(),
    )

    assert captured[0][runner.provider.LIVE_SMOKE_ENV] == "1"
    assert captured[0][runner.retrieval.SMOKE_ENV] == "1"
    assert captured[0][runner.grounded.SMOKE_ENV] == "1"
    assert result["status"] == "PASS"
    assert result["source_projection"] == {
        "provider_status": "PASS",
        "retrieval_status": "PASS",
        "grounded_status": "PASS",
    }
    assert result["next_slice"] == "1398"
    assert runner.summary_line(result) == (
        "platform_release_candidate_live_providers=pass providers=3 failed=0 "
        "calibration=20 residue=0 next=1398"
    )


def test_runner_bounds_exception_and_main_exit(monkeypatch, capsys) -> None:
    result = runner.run_platform_release_candidate_live_providers(
        {runner.ENABLE_ENV: "1"},
        provider_runner=lambda env: (_ for _ in ()).throw(
            RuntimeError("live-secret-value")
        ),
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "release_candidate_live_provider_execution_failed"
    assert "live-secret-value" not in json.dumps(result)
    assert result["source_projection"]["retrieval_status"] == "NOT_RUN"

    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_live_providers",
        lambda: {"status": "SKIPPED"},
    )
    assert runner.main(["--summary"]) == 0
    assert "=skip" in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_live_providers",
        lambda: {"status": "FAIL", "gate_evidence": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
