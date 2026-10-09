from __future__ import annotations

import json
from pathlib import Path

import pytest
import run_s149_single_host_live_acceptance as smoke


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_CX_TEST_DATABASE_URL": "postgresql://user:private-db@localhost/test",
        "NEX_MO_VLLM_API_KEY": "private-provider-key",
        "NEX_MO_VLLM_BASE_URL": "http://provider.example:9111",
    }


def _topology(*, status: str = "PASS") -> dict[str, object]:
    return {
        "status": status,
        "release_set_digest": "sha256:" + "a" * 64,
        "postgres_migration": {"status": "PASS", "service_count": 5},
        "services": {
            "initial_ready_count": 6,
            "rotated_ready_count": 6,
            "rollback_ready_count": 6,
        },
        "providers": {
            "status": "PASS",
            "capabilities": {
                name: {"status": "PASS"}
                for name in ("embedding", "reranking", "generation")
            },
        },
        "decision": {
            "production_contacted": False,
            "production_deployment_approved": False,
        },
    }


def _storage(*, status: str = "PASS") -> dict[str, object]:
    return {
        "status": status,
        "postgres": {"status": "PASS", "migration_service_count": 5},
        "adapters": {"status": "PASS", "postgres_payload_bytes_written": False},
        "rustfs": {
            "restart_recovery_verified": True,
            "cross_bucket_denied": {
                "cx_to_ae_denied": True,
                "ae_to_cx_denied": True,
            },
        },
        "cleanup": {"status": "PASS", "named_volume_removed": True},
        "decision": {
            "production_contacted": False,
            "production_deployment_approved": False,
        },
    }


def _providers(*, status: str = "PASS") -> dict[str, object]:
    return {
        "status": status,
        "summary": {
            "live_provider_count": 3,
            "live_model_match_count": 3,
            "runtime_ready_count": 3,
        },
        "cleanup": {"residue": 0},
    }


def _run(tmp_path: Path, **overrides: object) -> dict[str, object]:
    topology = overrides.get("topology", _topology())
    storage = overrides.get("storage", _storage())
    providers = overrides.get("providers", _providers())
    return smoke.run_s149_single_host_live_acceptance(
        _env(),
        execute=True,
        report_path=tmp_path / "report.json",
        topology_runner=lambda _env, _path: topology,  # type: ignore[return-value]
        object_storage_runner=lambda _env, _path: storage,  # type: ignore[return-value]
        provider_runner=lambda _env, _path: providers,  # type: ignore[return-value]
    )


def test_acceptance_requires_explicit_opt_in_and_test_profile(tmp_path: Path) -> None:
    skipped = smoke.run_s149_single_host_live_acceptance({}, report_path=tmp_path / "x")
    wrong = smoke.run_s149_single_host_live_acceptance(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "staging"},
        execute=True,
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in skipped["skip_reason"]
    assert wrong["failure_code"] == "profile_not_allowed"


def test_acceptance_passes_and_writes_metadata_only_evidence(tmp_path: Path) -> None:
    result = _run(tmp_path)
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 13,
        "check_count": 13,
        "test_database_count": 5,
        "runtime_service_count": 6,
        "object_storage_owner_count": 2,
        "live_provider_count": 3,
        "residue_count": 0,
    }
    assert result["external_notification"]["status"] == "EXTERNAL_NOT_ACTIVATED"
    assert result["next_slice"] == "1491"
    assert "private-db" not in serialized
    assert "private-provider-key" not in serialized
    assert "provider.example" not in serialized
    assert json.loads((tmp_path / "report.json").read_text()) == result


@pytest.mark.parametrize(
    ("boundary", "value", "failure_code"),
    [
        ("topology", _topology(status="FAIL"), "topology_acceptance_failed"),
        ("storage", _storage(status="FAIL"), "object_storage_acceptance_failed"),
        ("providers", _providers(status="FAIL"), "providers_acceptance_failed"),
    ],
)
def test_acceptance_stops_at_failed_nested_boundary(
    tmp_path: Path, boundary: str, value: object, failure_code: str
) -> None:
    result = _run(tmp_path, **{boundary: value})

    assert result["status"] == "FAIL"
    assert result["failure_code"] == failure_code
    assert result["diagnostics"]["boundary"] in failure_code


@pytest.mark.parametrize(
    ("mutation", "check"),
    [
        (lambda t, _s, _p: t.update(release_set_digest="bad"), "immutable_release_set_bound"),
        (
            lambda t, _s, _p: t["postgres_migration"].update(service_count=4),
            "five_test_database_migrations_current",
        ),
        (
            lambda t, _s, _p: t["services"].update(rollback_ready_count=5),
            "six_runtime_services_ready_across_generations",
        ),
        (
            lambda t, _s, _p: t["providers"]["capabilities"].pop("generation"),
            "compose_provider_routes_ready",
        ),
        (
            lambda _t, s, _p: s["postgres"].update(status="FAIL"),
            "rustfs_postgres_metadata_current",
        ),
        (
            lambda _t, s, _p: s["adapters"].update(postgres_payload_bytes_written=True),
            "rustfs_owner_adapters_round_trip",
        ),
        (
            lambda _t, s, _p: s["rustfs"].update(restart_recovery_verified=False),
            "rustfs_restart_recovery_verified",
        ),
        (
            lambda _t, s, _p: s["rustfs"]["cross_bucket_denied"].update(cx_to_ae_denied=False),
            "rustfs_owner_isolation_verified",
        ),
        (
            lambda _t, s, _p: s["cleanup"].update(named_volume_removed=False),
            "rustfs_zero_residue_cleanup",
        ),
        (
            lambda _t, _s, p: p["summary"].update(live_provider_count=2),
            "three_remote_provider_capabilities_live",
        ),
        (
            lambda _t, _s, p: p["summary"].update(live_model_match_count=2),
            "provider_model_identity_matched",
        ),
        (
            lambda _t, _s, p: p["cleanup"].update(residue=1),
            "provider_rehearsal_zero_residue",
        ),
        (
            lambda t, _s, _p: t["decision"].update(production_contacted=True),
            "production_resources_not_targeted",
        ),
    ],
)
def test_acceptance_fails_closed_for_live_evidence_drift(
    tmp_path: Path, mutation, check: str
) -> None:
    topology, storage, providers = _topology(), _storage(), _providers()
    mutation(topology, storage, providers)

    result = _run(
        tmp_path,
        topology=topology,
        storage=storage,
        providers=providers,
    )

    assert result["status"] == "FAIL"
    assert result["checks"][check] is False
    assert result["next_slice"] == "blocked"


def test_acceptance_converts_exception_and_rejects_secret_leak(tmp_path: Path) -> None:
    failed = smoke.run_s149_single_host_live_acceptance(
        _env(),
        execute=True,
        report_path=tmp_path / "report.json",
        topology_runner=lambda _env, _path: (_ for _ in ()).throw(
            RuntimeError("private-provider-key")
        ),
    )
    assert failed["failure_code"] == "single_host_live_acceptance_execution_failed"
    assert failed["diagnostics"] == {"exception_type": "RuntimeError"}
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"leak": "private-provider-key"}, _env())


def test_default_runner_adapters_and_helpers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        smoke,
        "run_s143_external_staging_acceptance",
        lambda env, **kwargs: {"status": "PASS", "enabled": env["NEX_S143_EXTERNAL_STAGING_ACCEPTANCE"], **kwargs},
    )
    monkeypatch.setattr(
        smoke,
        "run_s146_object_storage_acceptance",
        lambda env, **kwargs: {"status": "PASS", "enabled": env["NEX_S146_PROTECTED_ACCEPTANCE"], **kwargs},
    )
    monkeypatch.setattr(
        smoke,
        "run_s147_model_rollout_live_acceptance",
        lambda env: {"status": "PASS", "enabled": env["NEX_MO_MODEL_ROLLOUT_LIVE_ACCEPTANCE"]},
    )
    assert smoke._run_topology({}, tmp_path / "one")["enabled"] == "1"
    assert smoke._run_object_storage({}, tmp_path / "two")["enabled"] == "1"
    assert smoke._run_providers({}, tmp_path / "three")["enabled"] == "1"
    assert smoke._mapping([]) == {}
    assert smoke._nonnegative_int(True) == 0
    assert smoke._nonnegative_int(-1) == 0
    assert smoke._digest({"ok": True}).startswith("sha256:")


def test_summary_and_main(monkeypatch, capsys, tmp_path: Path) -> None:
    passing = _run(tmp_path)
    skipped = smoke.run_s149_single_host_live_acceptance({})
    assert smoke.summary_line(skipped) == "s149_single_host_live_acceptance=skipped"
    assert smoke.summary_line(passing) == (
        "s149_single_host_live_acceptance=pass checks=13/13 databases=5/5 "
        "services=6/6 providers=3/3 residue=0 next=1491"
    )
    monkeypatch.setattr(smoke, "run_s149_single_host_live_acceptance", lambda **_kwargs: passing)
    assert smoke.main(["--execute", "--summary", "--report-path", str(tmp_path / "x")]) == 0
    assert "checks=13/13" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke, "run_s149_single_host_live_acceptance", lambda **_kwargs: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
