from __future__ import annotations

import json
import os

import pytest
import run_s147_model_rollout_live_acceptance as smoke


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.DATABASE_ENV: (
            "postgresql+psycopg://nex_mo_user:private-db-secret@127.0.0.1/"
            "nex_mo_test"
        ),
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.example:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-provider-key",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.example:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "private-provider-key",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.example:9111",
        "NEX_MO_VLLM_API_KEY": "private-provider-key",
        "NEX_MO_DGX_SSH_TARGET": "operator@dgx.example",
    }


def _live(*, status: str = "PASS") -> dict[str, object]:
    return {
        "status": status,
        "failure_code": None if status == "PASS" else "upstream_failed",
        "summary": {
            "provider_success_count": 3,
            "model_match_count": 3,
            "runtime_ready_capability_count": 3,
        },
    }


def _persistence() -> dict[str, object]:
    return {
        "database_identity": {
            "database_name": "nex_mo_test",
            "database_user": "nex_mo_user",
        },
        "migration_current": True,
        "rollout_count": 3,
        "event_count": 6,
        "validating_count": 3,
        "restart_read_count": 3,
        "api_status": 200,
        "api_item_count": 3,
        "promotion_mutation_count": 0,
        "aliases_unchanged": True,
        "cleanup": {
            "deleted_event_rows": 6,
            "deleted_rollout_rows": 3,
            "deleted_catalog_rows": 3,
            "residue": 0,
        },
    }


def _run(
    persistence: dict[str, object] | None = None,
    *,
    live: dict[str, object] | None = None,
) -> dict[str, object]:
    return smoke.run_s147_model_rollout_live_acceptance(
        _env(),
        live_runner=lambda _env: live or _live(),
        persistence_exercise=lambda _url, _env: persistence or _persistence(),
    )


def test_acceptance_is_explicitly_protected_and_test_only() -> None:
    skipped = smoke.run_s147_model_rollout_live_acceptance({})
    wrong_profile = smoke.run_s147_model_rollout_live_acceptance(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "staging"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in skipped["skip_reason"]
    assert wrong_profile["status"] == "FAIL"
    assert wrong_profile["failure_code"] == "profile_not_allowed"


def test_acceptance_requires_nested_live_provider_success() -> None:
    result = _run(live=_live(status="FAIL"))

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "live_provider_acceptance_failed"
    assert result["diagnostics"] == {"nested_failure_code": "upstream_failed"}


def test_acceptance_passes_with_redacted_non_disruptive_evidence() -> None:
    result = _run()
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 12,
        "check_count": 12,
        "live_provider_count": 3,
        "live_model_match_count": 3,
        "runtime_ready_count": 3,
        "rollout_count": 3,
        "event_count": 6,
        "restart_read_count": 3,
        "api_status": 200,
        "api_item_count": 3,
        "generation_reasoning_mode": "disabled",
    }
    assert result["candidate_admission"] == {
        "status": "CALIBRATION_REQUIRED",
        "promotion_eligible": False,
        "reason": (
            "protected smoke has no candidate artifact provenance or ACTIVE calibration"
        ),
        "live_mutation_performed": False,
    }
    assert result["next_slice"] == "1472"
    assert "private-db-secret" not in serialized
    assert "private-provider-key" not in serialized
    assert "operator@dgx.example" not in serialized


@pytest.mark.parametrize(
    ("field", "value", "check"),
    [
        ("migration_current", False, "rollout_migration_current"),
        ("rollout_count", 2, "all_capability_rehearsals_persisted"),
        ("event_count", 5, "atomic_transition_events_persisted"),
        ("restart_read_count", 2, "restart_readback_complete"),
        ("api_status", 503, "protected_api_readback_complete"),
        ("validating_count", 2, "rollouts_stop_before_unproven_canary"),
        ("aliases_unchanged", False, "live_aliases_unchanged"),
    ],
)
def test_acceptance_fails_closed_for_persistence_drift(
    field: str,
    value: object,
    check: str,
) -> None:
    persistence = _persistence()
    persistence[field] = value

    result = _run(persistence)

    assert result["status"] == "FAIL"
    assert result["checks"][check] is False
    assert result["next_slice"] == "blocked"


def test_acceptance_fails_closed_for_live_and_cleanup_drift() -> None:
    live = _live()
    live["summary"] = {
        "provider_success_count": 2,
        "model_match_count": 2,
        "runtime_ready_capability_count": 2,
    }
    persistence = _persistence()
    persistence["promotion_mutation_count"] = 1
    persistence["cleanup"] = {"residue": 1}

    result = _run(persistence, live=live)

    assert result["status"] == "FAIL"
    assert result["checks"]["all_live_provider_requests_succeeded"] is False
    assert result["checks"]["all_live_models_matched"] is False
    assert result["checks"]["all_live_runtime_models_healthy"] is False
    assert result["checks"]["rollouts_stop_before_unproven_canary"] is False
    assert result["checks"]["targeted_cleanup_complete"] is False


def test_acceptance_converts_execution_exception_to_safe_failure() -> None:
    result = smoke.run_s147_model_rollout_live_acceptance(
        _env(),
        live_runner=lambda _env: (_ for _ in ()).throw(
            RuntimeError("private-provider-key")
        ),
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "model_rollout_live_acceptance_execution_failed"
    assert result["diagnostics"] == {"exception_type": "RuntimeError"}


def test_acceptance_preserves_safe_domain_error_code() -> None:
    class DomainError(RuntimeError):
        error_code = "MO_ROLLOUT_CONFLICT"

    result = smoke.run_s147_model_rollout_live_acceptance(
        _env(),
        live_runner=lambda _env: _live(),
        persistence_exercise=lambda _url, _env: (_ for _ in ()).throw(
            DomainError("private detail")
        ),
    )

    assert result["diagnostics"] == {
        "exception_type": "DomainError",
        "error_code": "MO_ROLLOUT_CONFLICT",
    }


def test_acceptance_helpers_and_redaction(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_mo_operations_live_acceptance",
        lambda env: {"status": "PASS", "seen": env[smoke.ACTIVATION_ENV]},
    )
    assert smoke._run_live_operations(_env())["status"] == "PASS"
    assert smoke._response_formats("embedding") == ("vector",)
    assert smoke._response_formats("reranking") == ("score",)
    assert smoke._response_formats("generation") == ("text", "json_object")
    assert smoke._count(3) == 3
    assert smoke._count(-1) == 0
    assert smoke._count("3") == 0
    assert smoke._mapping({"ok": True}) == {"ok": True}
    assert smoke._mapping([]) == {}
    assert smoke._digest({"a": 1}).startswith("sha256:")
    now = smoke._utc_now()
    assert now.endswith("Z")
    assert smoke._utc_after(now).endswith("Z")
    smoke.assert_evidence_redacted({"safe": True}, _env())
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"leak": "private-provider-key"}, _env())
    malformed = _env()
    malformed[smoke.DATABASE_ENV] = "not-a-url"
    smoke.assert_evidence_redacted({"safe": True}, malformed)


def test_acceptance_summary_and_main(monkeypatch, capsys) -> None:
    skipped = smoke.run_s147_model_rollout_live_acceptance({})
    passing = _run()
    assert smoke.summary_line(skipped).startswith(
        "s147_model_rollout_live_acceptance=skipped"
    )
    assert smoke.summary_line(passing) == (
        "s147_model_rollout_live_acceptance=pass checks=12/12 providers=3/3 "
        "runtime=3/3 rollouts=3/3 events=6/6 cleanup=0 next=1472"
    )
    monkeypatch.setattr(
        smoke,
        "run_s147_model_rollout_live_acceptance",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "checks=12/12" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_s147_model_rollout_live_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


@pytest.mark.skipif(
    os.getenv(smoke.ACTIVATION_ENV) != "1",
    reason=f"set {smoke.ACTIVATION_ENV}=1 for protected PostgreSQL/DGX acceptance",
)
def test_protected_acceptance_uses_actual_postgres_and_dgx() -> None:
    result = smoke.run_s147_model_rollout_live_acceptance()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
