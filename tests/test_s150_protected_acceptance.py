from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from nex_runtime.production_release import build_release_evidence_manifest
import run_s150_protected_acceptance as runner
import run_s150_release_decision as decision_runner


NOW = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
RELEASE_ID = "rc:s149:730196df68414600"
RELEASE_DIGEST = f"sha256:{'1' * 64}"


def _source() -> dict:
    return {
        "status": "PASS",
        "release_candidate_id": RELEASE_ID,
        "release_set_digest": RELEASE_DIGEST,
        "production_deployment_approved": False,
    }


def _sources(*, go: bool = False) -> dict[str, dict]:
    manifest = build_release_evidence_manifest(
        {
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
        },
        source_revision="a" * 40,
        observed_at=NOW,
    )
    return {
        "manifest": manifest,
        "admission": {
            **_source(),
            "checks": {
                "go_live_window_24h": True,
                "release_candidate_id_exact": True,
                "release_set_digest_exact": True,
                "production_deployment_separate": True,
            },
        },
        "risk_governance": {
            **_source(),
            "gate_results": {"no_open_p0": True, "p1_waivers_valid": go},
        },
        "approval_governance": {
            **_source(),
            "gate_results": {
                "approval_roles_complete": go,
                "production_deployment_separate": True,
            },
            "implicit_deployment_performed": False,
        },
        "immediate_preflight": {
            **_source(),
            "observed_at": (NOW - timedelta(minutes=5)).isoformat(),
            "expires_at": (NOW + timedelta(hours=3)).isoformat(),
            "checks": {
                "preflight_completed_within_window": True,
                "zero_residue": True,
                "production_deployment_separate": True,
            },
        },
        "rollback_rehearsal": {
            **_source(),
            "checks": {
                "artifact_configuration_digest_exact": True,
                "privacy_clean": True,
                "rollback_drill_passed": True,
                "zero_residue": True,
                "production_deployment_separate": True,
            },
            "implicit_deployment_performed": False,
        },
    }


def _write_sources(tmp_path: Path, sources: dict[str, dict]) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, payload in sources.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    return paths


def _prepare(
    tmp_path: Path,
    *,
    go: bool = False,
) -> tuple[dict[str, dict], dict[str, Path], Path]:
    sources = _sources(go=go)
    paths = _write_sources(tmp_path, sources)
    decision_path = tmp_path / "decision.json"
    decision = decision_runner.run_release_decision(
        {decision_runner.ACTIVATION_ENV: "1"},
        source_paths=paths,
        output_path=decision_path,
        evaluated_at=NOW,
    )
    assert decision["status"] == "PASS"
    return sources, paths, decision_path


def _run(
    tmp_path: Path,
    *,
    go: bool = False,
    mutate_sources=None,
    mutate_decision=None,
) -> dict:
    sources, paths, decision_path = _prepare(tmp_path, go=go)
    if mutate_sources:
        mutate_sources(sources)
        paths = _write_sources(tmp_path, sources)
    if mutate_decision:
        decision = json.loads(decision_path.read_text())
        mutate_decision(decision)
        decision_path.write_text(json.dumps(decision), encoding="utf-8")
    return runner.run_protected_acceptance(
        {runner.ACTIVATION_ENV: "1", runner.PROFILE_ENV: "test"},
        execute=True,
        source_paths=paths,
        decision_path=decision_path,
        output_path=tmp_path / "acceptance.json",
        evaluated_at=NOW,
    )


@pytest.mark.parametrize(("go", "decision"), [(False, "NO_GO"), (True, "GO")])
def test_protected_acceptance_accepts_both_exact_decisions(
    tmp_path: Path, go: bool, decision: str
) -> None:
    result = _run(tmp_path, go=go)

    assert result["status"] == "PASS", result
    assert result["release_decision"] == decision
    assert all(result["checks"].values())
    assert result["summary"]["distributed_backlog_count"] == 5
    assert result["go_live_authorized"] is go
    assert result["production_deployment_approved"] is False


@pytest.mark.parametrize(
    ("source_mutation", "decision_mutation", "failed_check"),
    [
        (
            lambda s: s["admission"].update(diagnostic="changed"),
            None,
            "source_digests_exact",
        ),
        (
            None,
            lambda d: d["gate_results"].update(no_open_p0=False),
            "decision_replay_exact",
        ),
        (
            None,
            lambda d: d.update(gate_order=list(reversed(d["gate_order"]))),
            "mandatory_gate_inventory_exact",
        ),
        (
            None,
            lambda d: d.update(decision="GO", go_authorized=True),
            "decision_state_consistent",
        ),
        (
            lambda s: s["manifest"].update(single_host_backlog_count=4),
            None,
            "single_host_backlog_preserved",
        ),
        (
            None,
            lambda d: d.update(production_deployment_approved=True),
            "production_deployment_separate",
        ),
    ],
)
def test_protected_acceptance_fails_closed_for_drift(
    tmp_path: Path, source_mutation, decision_mutation, failed_check: str
) -> None:
    result = _run(
        tmp_path,
        mutate_sources=source_mutation,
        mutate_decision=decision_mutation,
    )

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False
    assert result["go_live_authorized"] is False
    assert result["next_slice"] == "blocked"


def test_protected_acceptance_rejects_skip_profile_inventory_and_missing(
    tmp_path: Path,
) -> None:
    assert runner.run_protected_acceptance({})["status"] == "SKIPPED"
    wrong = runner.run_protected_acceptance(
        {runner.ACTIVATION_ENV: "1", runner.PROFILE_ENV: "production"},
        execute=True,
    )
    assert wrong["failure_code"] == "profile_not_allowed"
    invalid = runner.run_protected_acceptance(
        {runner.ACTIVATION_ENV: "1"},
        execute=True,
        source_paths={"manifest": tmp_path / "manifest.json"},
    )
    assert invalid["failure_code"] == "protected_acceptance_source_inventory_invalid"
    missing = runner.run_protected_acceptance(
        {runner.ACTIVATION_ENV: "1"},
        execute=True,
        source_paths={name: tmp_path / name for name in runner.SOURCE_PATHS},
        decision_path=tmp_path / "decision.json",
    )
    assert missing["failure_code"] == "protected_acceptance_evidence_unavailable"


def test_protected_acceptance_rejects_naive_clock_and_covers_cli(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _, paths, decision_path = _prepare(tmp_path)
    failed = runner.run_protected_acceptance(
        {runner.ACTIVATION_ENV: "1"},
        execute=True,
        source_paths=paths,
        decision_path=decision_path,
        evaluated_at=datetime(2026, 10, 9, 9, 0),
    )
    assert failed["failure_code"] == "protected_acceptance_execution_failed"

    passing = {
        "status": "PASS",
        "release_decision": "NO_GO",
        "summary": {
            "passed_check_count": 10,
            "check_count": 10,
            "passed_gate_count": 8,
            "gate_count": 10,
            "distributed_backlog_count": 5,
        },
    }
    assert "decision=NO_GO" in runner.summary_line(passing)
    assert runner.summary_line({"status": "FAIL"}).endswith("fail")
    assert runner.summary_line({"status": "SKIPPED"}).endswith("skipped")
    monkeypatch.setattr(runner, "run_protected_acceptance", lambda **_kw: passing)
    assert runner.main(["--execute", "--summary"]) == 0
    assert "gates=8/10" in capsys.readouterr().out
