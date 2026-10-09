from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from nex_runtime.production_release import build_release_evidence_manifest
import run_s150_cutover_rollback_rehearsal as runner


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


def _preflight() -> dict:
    return {
        "status": "PASS",
        "release_candidate_id": RELEASE_ID,
        "release_set_digest": RELEASE_DIGEST,
        "observed_at": (NOW - timedelta(minutes=5)).isoformat(),
        "expires_at": (NOW + timedelta(hours=3)).isoformat(),
        "checks": {"zero_residue": True, "provider_live": True},
        "production_deployment_approved": False,
    }


def _under_load() -> dict:
    return {
        "status": "PASS",
        "release_binding": {
            "release_candidate_id": RELEASE_ID,
            "release_set_digest": RELEASE_DIGEST,
            "fault_plan_digest": "4" * 64,
        },
        "checks": {
            "rollback_under_load_passed": True,
            "eight_client_faults_recovered": True,
            "zero_data_loss_isolation_and_residue": True,
        },
        "cleanup": {
            "client_fault_residue_count": 0,
            "provider_residue_count": 0,
            "shadow_residue_count": 0,
            "storage_status": "PASS",
        },
        "execution_scope": {"production_deployment_approved": False},
    }


def _write_sources(
    tmp_path: Path,
    *,
    manifest: dict | None = None,
    preflight: dict | None = None,
    under_load: dict | None = None,
) -> tuple[Path, Path, Path]:
    paths = (
        tmp_path / "manifest.json",
        tmp_path / "preflight.json",
        tmp_path / "under-load.json",
    )
    for path, payload in zip(
        paths,
        (manifest or _manifest(), preflight or _preflight(), under_load or _under_load()),
        strict=True,
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")
    return paths


def _run(
    tmp_path: Path,
    *,
    manifest: dict | None = None,
    preflight: dict | None = None,
    under_load: dict | None = None,
) -> dict:
    paths = _write_sources(
        tmp_path,
        manifest=manifest,
        preflight=preflight,
        under_load=under_load,
    )
    return runner.run_cutover_rollback_rehearsal(
        {runner.ACTIVATION_ENV: "1"},
        manifest_path=paths[0],
        preflight_path=paths[1],
        under_load_path=paths[2],
        output_path=tmp_path / "result.json",
        evaluated_at=NOW,
    )


def test_rehearsal_requires_opt_in_and_source_evidence(tmp_path: Path) -> None:
    skipped = runner.run_cutover_rollback_rehearsal({})
    missing = runner.run_cutover_rollback_rehearsal(
        {runner.ACTIVATION_ENV: "1"},
        manifest_path=tmp_path / "missing.json",
        preflight_path=tmp_path / "missing-preflight.json",
        under_load_path=tmp_path / "missing-load.json",
    )

    assert skipped["status"] == "SKIPPED"
    assert missing["failure_code"] == "required_rehearsal_evidence_unavailable"


def test_rehearsal_passes_exact_candidate_without_deploying(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 11,
        "passed_check_count": 11,
        "cutover_phase_count": 6,
        "rollback_component_count": 6,
        "recovery_ms": 120_000,
        "residue_count": 0,
    }
    assert result["cutover_execution_performed"] is False
    assert result["production_deployment_approved"] is False
    assert json.loads((tmp_path / "result.json").read_text()) == result


@pytest.mark.parametrize(
    ("source", "mutation", "failed_check"),
    [
        (
            "preflight",
            lambda value: value.update(expires_at=(NOW - timedelta(seconds=1)).isoformat()),
            "immediate_preflight_fresh",
        ),
        (
            "preflight",
            lambda value: value.update(release_candidate_id="rc:s149:ffffffffffffffff"),
            "exact_release_candidate_bound",
        ),
        (
            "under_load",
            lambda value: value.update(status="FAIL"),
            "under_load_recovery_passed",
        ),
        (
            "under_load",
            lambda value: value["cleanup"].update(provider_residue_count=1),
            "zero_residue",
        ),
    ],
)
def test_rehearsal_fails_closed_for_evidence_drift(
    tmp_path: Path, source: str, mutation, failed_check: str
) -> None:
    preflight = deepcopy(_preflight())
    under_load = deepcopy(_under_load())
    mutation(preflight if source == "preflight" else under_load)

    result = _run(tmp_path, preflight=preflight, under_load=under_load)

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False
    assert result["next_slice"] == "blocked"
    assert not (tmp_path / "result.json").exists()


def test_rehearsal_redacts_execution_errors(tmp_path: Path) -> None:
    under_load = _under_load()
    under_load["release_binding"]["fault_plan_digest"] = "invalid"

    result = _run(tmp_path, under_load=under_load)

    assert result["failure_code"] == "cutover_rollback_rehearsal_execution_failed"
    assert result["diagnostics"] == {"exception_type": "RollbackPlanError"}
    assert result["production_deployment_approved"] is False


def test_rehearsal_helpers_summary_and_cli(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_check_count": 11,
            "check_count": 11,
            "cutover_phase_count": 6,
            "rollback_component_count": 6,
            "recovery_ms": 120_000,
            "residue_count": 0,
        },
    }
    assert "checks=11/11" in runner.summary_line(passing)
    assert runner.summary_line({"status": "FAIL"}).endswith("fail")
    assert runner.summary_line({"status": "SKIPPED"}).endswith("skipped")
    monkeypatch.setattr(runner, "run_cutover_rollback_rehearsal", lambda **_kw: passing)

    assert runner.main(["--summary"]) == 0
    assert "next=1502" in capsys.readouterr().out


def test_rehearsal_rejects_naive_evaluation_time(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)
    result = runner.run_cutover_rollback_rehearsal(
        {runner.ACTIVATION_ENV: "1"},
        manifest_path=paths[0],
        preflight_path=paths[1],
        under_load_path=paths[2],
        evaluated_at=datetime(2026, 10, 9, 9, 0),
    )

    assert result["failure_code"] == "cutover_rollback_rehearsal_execution_failed"
