from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from nex_runtime.production_release import build_release_evidence_manifest
import run_s150_immediate_preflight as runner


NOW = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
RELEASE_ID = "rc:s149:730196df68414600"
RELEASE_DIGEST = f"sha256:{'1' * 64}"


def _manifest() -> dict:
    closure = {
        "status": "PASS",
        "release_binding": {
            "release_candidate_id": RELEASE_ID,
            "release_set_digest": RELEASE_DIGEST,
            "admission_evidence_digest": f"sha256:{'2' * 64}",
            "full_regression_evidence_digest": "3" * 64,
        },
        "full_regression": {
            "status": "PASS",
            "passed_test_count": 100,
            "failed_test_count": 0,
            "statement_coverage": 98.0,
            "branch_coverage": 97.0,
        },
        "summary": {"backlog_count": 5},
        "s150_handoff": {
            "external_notification_waiver": "REQUIRED_NOT_GRANTED",
            "production_go_eligible": False,
        },
        "production_deployment_approved": False,
    }
    return build_release_evidence_manifest(
        closure,
        source_revision="a" * 40,
        observed_at=NOW,
    )


def _live(status: str = "PASS") -> dict:
    checks = {
        "five_test_database_migrations_current": True,
        "six_runtime_services_ready_across_generations": True,
        "rustfs_restart_recovery_verified": True,
        "three_remote_provider_capabilities_live": True,
        "generation_reasoning_disabled": True,
    }
    return {
        "status": status,
        "failure_code": None if status == "PASS" else "live_failed",
        "release_binding": {
            "release_candidate_id": RELEASE_ID,
            "release_set_digest": RELEASE_DIGEST,
        },
        "checks": checks,
        "summary": {
            "test_database_count": 5,
            "live_provider_count": 3,
            "residue_count": 0,
        },
    }


def _observability(status: str = "PASS") -> dict:
    return {
        "status": status,
        "failure_code": None if status == "PASS" else "observability_failed",
        "checks": {
            "actual_postgresql_backend": True,
            "test_database_selected": True,
            "migration_recorded": True,
        },
        "cleanup": {"residue": 0},
    }


def _incident(status: str = "PASS") -> dict:
    return {
        "status": status,
        "failure_code": None if status == "PASS" else "incident_failed",
        "checks": {"local_delivery_real": True, "mock_not_live_delivery": True},
        "external_activation": "EXTERNAL_NOT_ACTIVATED",
    }


def _run(
    tmp_path: Path,
    *,
    manifest: dict | None = None,
    live: dict | None = None,
    observability: dict | None = None,
    incident: dict | None = None,
    times: list[datetime] | None = None,
) -> dict:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest or _manifest()), encoding="utf-8")
    values = iter(times or [NOW, NOW + timedelta(minutes=1)])
    return runner.run_immediate_preflight(
        {runner.ACTIVATION_ENV: "1", runner.PROFILE_ENV: "test"},
        execute=True,
        manifest_path=manifest_path,
        output_path=tmp_path / "preflight.json",
        clock=lambda: next(values),
        live_runner=lambda _env, _path: live or _live(),
        observability_runner=lambda _env: observability or _observability(),
        incident_runner=lambda: incident or _incident(),
    )


def test_preflight_requires_opt_in_profile_and_valid_manifest(tmp_path: Path) -> None:
    skipped = runner.run_immediate_preflight({}, output_path=tmp_path / "skip.json")
    wrong = runner.run_immediate_preflight(
        {runner.ACTIVATION_ENV: "1", runner.PROFILE_ENV: "production"},
        execute=True,
        output_path=tmp_path / "wrong.json",
    )
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    bad_manifest = runner.run_immediate_preflight(
        {runner.ACTIVATION_ENV: "1"},
        execute=True,
        manifest_path=invalid,
        output_path=tmp_path / "bad.json",
    )

    assert skipped["status"] == "SKIPPED"
    assert wrong["failure_code"] == "profile_not_allowed"
    assert bad_manifest["failure_code"] == "release_manifest_unavailable_or_invalid"


def test_preflight_passes_and_writes_metadata_only_evidence(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 8,
        "check_count": 8,
        "test_database_count": 5,
        "live_provider_count": 3,
        "external_notification_status": "EXTERNAL_NOT_ACTIVATED",
        "duration_seconds": 60.0,
    }
    assert result["freshness_class"] == "IMMEDIATE_PREFLIGHT_4H"
    assert result["next_slice"] == "1501"
    assert json.loads((tmp_path / "preflight.json").read_text()) == result


@pytest.mark.parametrize(
    ("boundary", "value", "failure_code"),
    [
        ("live", _live("FAIL"), "single_host_live_preflight_failed"),
        (
            "observability",
            _observability("FAIL"),
            "observability_preflight_failed",
        ),
        ("incident", _incident("FAIL"), "incident_preflight_failed"),
    ],
)
def test_preflight_stops_at_failed_nested_boundary(
    tmp_path: Path, boundary: str, value: dict, failure_code: str
) -> None:
    result = _run(tmp_path, **{boundary: value})

    assert result["status"] == "FAIL"
    assert result["failure_code"] == failure_code
    assert result["diagnostics"]["boundary"] in failure_code


@pytest.mark.parametrize(
    ("mutation", "check"),
    [
        (
            lambda _m, l, _o, _i: l["release_binding"].update(
                release_candidate_id="wrong"
            ),
            "exact_release_candidate_bound",
        ),
        (
            lambda _m, l, _o, _i: l["summary"].update(test_database_count=4),
            "trust_database_storage_provider_live",
        ),
        (
            lambda _m, l, _o, _i: l["checks"].update(
                generation_reasoning_disabled=False
            ),
            "generation_reasoning_disabled",
        ),
        (
            lambda _m, _l, o, _i: o["checks"].update(
                actual_postgresql_backend=False
            ),
            "observability_postgres_live",
        ),
        (
            lambda _m, _l, _o, i: i.update(external_activation="LIVE"),
            "incident_route_rehearsed",
        ),
        (
            lambda _m, l, _o, _i: l["summary"].update(residue_count=1),
            "zero_residue",
        ),
    ],
)
def test_preflight_fails_closed_for_evidence_drift(
    tmp_path: Path, mutation, check: str
) -> None:
    manifest, live, observability, incident = (
        _manifest(),
        _live(),
        _observability(),
        _incident(),
    )
    mutation(manifest, live, observability, incident)
    result = _run(
        tmp_path,
        manifest=manifest,
        live=live,
        observability=observability,
        incident=incident,
    )

    assert result["status"] == "FAIL"
    assert result["checks"][check] is False
    assert result["next_slice"] == "blocked"


def test_preflight_rejects_invalid_clock_and_window(tmp_path: Path) -> None:
    naive = datetime(2026, 10, 9, 9, 0)
    started_bad = _run(tmp_path, times=[naive])
    completed_bad = _run(tmp_path, times=[NOW, naive])
    too_long = _run(tmp_path, times=[NOW, NOW + timedelta(hours=5)])

    assert started_bad["failure_code"] == "preflight_clock_must_be_timezone_aware"
    assert completed_bad["failure_code"] == "preflight_clock_must_be_timezone_aware"
    assert too_long["checks"]["preflight_completed_within_window"] is False


def test_preflight_exception_redaction_adapters_and_helpers(
    monkeypatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    secret = "private-provider-value"
    failed = runner.run_immediate_preflight(
        {
            runner.ACTIVATION_ENV: "1",
            "NEX_MO_VLLM_API_KEY": secret,
        },
        execute=True,
        manifest_path=manifest,
        output_path=tmp_path / "output.json",
        clock=lambda: NOW,
        live_runner=lambda _env, _path: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    assert failed["failure_code"] == "immediate_preflight_execution_failed"
    assert secret not in json.dumps(failed)
    with pytest.raises(ValueError, match="protected value"):
        runner._assert_redacted({"leak": secret}, {"NEX_MO_VLLM_API_KEY": secret})

    monkeypatch.setattr(runner, "run_s149_single_host_live_acceptance", lambda env, **kwargs: {"status": "PASS", "enabled": env["NEX_S149_SINGLE_HOST_LIVE_ACCEPTANCE"], **kwargs})
    monkeypatch.setattr(runner, "run_observability_postgres_smoke", lambda env: {"status": "PASS", "enabled": env["NEX_AG_OBSERVABILITY_POSTGRES_SMOKE"]})
    assert runner._run_live({}, tmp_path / "live.json")["enabled"] == "1"
    assert runner._run_observability({})["enabled"] == "1"
    assert runner._mapping(None) == {}

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert runner._load_json(bad) == {}
    bad.write_text("bad", encoding="utf-8")
    assert runner._load_json(bad) == {}


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_check_count": 8,
            "check_count": 8,
            "test_database_count": 5,
            "live_provider_count": 3,
        },
    }
    assert runner.summary_line({"status": "SKIPPED"}) == "s150_immediate_preflight=skipped"
    assert runner.summary_line({"status": "FAIL"}) == "s150_immediate_preflight=fail"
    assert "checks=8/8" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_immediate_preflight", lambda **_kwargs: passing)
    assert runner.main(["--summary"]) == 0
    assert "s150_immediate_preflight=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        runner, "run_immediate_preflight", lambda **_kwargs: {"status": "FAIL"}
    )
    assert runner.main([]) == 1
