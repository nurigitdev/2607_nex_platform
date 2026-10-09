from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from nex_runtime.production_release import (
    RELEASE_GATE_NAMES,
    build_release_evidence_manifest,
)
import run_s150_release_decision as runner


NOW = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
RELEASE_ID = "rc:s149:730196df68414600"
RELEASE_DIGEST = f"sha256:{'1' * 64}"


def _manifest() -> dict:
    return build_release_evidence_manifest(
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


def _source(status: str = "PASS") -> dict:
    return {
        "status": status,
        "release_candidate_id": RELEASE_ID,
        "release_set_digest": RELEASE_DIGEST,
        "production_deployment_approved": False,
    }


def _sources(*, go: bool = True) -> dict[str, dict]:
    admission = {
        **_source(),
        "checks": {
            "go_live_window_24h": True,
            "release_candidate_id_exact": True,
            "release_set_digest_exact": True,
            "production_deployment_separate": True,
        },
    }
    risk = {
        **_source(),
        "gate_results": {"no_open_p0": True, "p1_waivers_valid": go},
    }
    approval = {
        **_source(),
        "gate_results": {
            "approval_roles_complete": go,
            "production_deployment_separate": True,
        },
        "implicit_deployment_performed": False,
    }
    preflight = {
        **_source(),
        "observed_at": (NOW - timedelta(minutes=5)).isoformat(),
        "expires_at": (NOW + timedelta(hours=3)).isoformat(),
        "checks": {
            "preflight_completed_within_window": True,
            "zero_residue": True,
            "production_deployment_separate": True,
        },
    }
    rollback = {
        **_source(),
        "checks": {
            "artifact_configuration_digest_exact": True,
            "privacy_clean": True,
            "rollback_drill_passed": True,
            "zero_residue": True,
            "production_deployment_separate": True,
        },
        "implicit_deployment_performed": False,
    }
    return {
        "manifest": _manifest(),
        "admission": admission,
        "risk_governance": risk,
        "approval_governance": approval,
        "immediate_preflight": preflight,
        "rollback_rehearsal": rollback,
    }


def _write_sources(tmp_path: Path, sources: dict[str, dict]) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, payload in sources.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result[name] = path
    return result


def _run(tmp_path: Path, sources: dict[str, dict]) -> dict:
    return runner.run_release_decision(
        {runner.ACTIVATION_ENV: "1"},
        source_paths=_write_sources(tmp_path, sources),
        output_path=tmp_path / "decision.json",
        evaluated_at=NOW,
    )


def test_release_decision_supports_exact_go_and_no_go_states(tmp_path: Path) -> None:
    go = _run(tmp_path / "go", _sources(go=True))
    no_go = _run(tmp_path / "no-go", _sources(go=False))

    assert go["status"] == "PASS"
    assert go["decision"] == "GO"
    assert go["go_authorized"] is True
    assert list(go["gate_results"]) == list(RELEASE_GATE_NAMES)
    assert no_go["status"] == "PASS"
    assert no_go["decision"] == "NO_GO"
    assert no_go["failed_gates"] == [
        "p1_waivers_valid",
        "approval_roles_complete",
    ]
    assert no_go["production_deployment_approved"] is False


@pytest.mark.parametrize(
    ("mutation", "failed_gate"),
    [
        (
            lambda s: s["admission"].update(status="FAIL"),
            "all_dependency_evidence_passed",
        ),
        (
            lambda s: s["immediate_preflight"].update(
                expires_at=(NOW - timedelta(seconds=1)).isoformat()
            ),
            "evidence_fresh",
        ),
        (
            lambda s: s["immediate_preflight"].update(
                release_set_digest=f"sha256:{'9' * 64}"
            ),
            "artifact_configuration_digest_exact",
        ),
        (
            lambda s: s["risk_governance"]["gate_results"].update(
                no_open_p0=False
            ),
            "no_open_p0",
        ),
        (
            lambda s: s["risk_governance"]["gate_results"].update(
                p1_waivers_valid=False
            ),
            "p1_waivers_valid",
        ),
        (lambda s: s["approval_governance"].update(api_key="forbidden"), "privacy_clean"),
        (
            lambda s: s["rollback_rehearsal"]["checks"].update(
                rollback_drill_passed=False
            ),
            "rollback_drill_passed",
        ),
        (
            lambda s: s["rollback_rehearsal"]["checks"].update(zero_residue=False),
            "zero_residue",
        ),
        (
            lambda s: s["approval_governance"]["gate_results"].update(
                approval_roles_complete=False
            ),
            "approval_roles_complete",
        ),
        (
            lambda s: s["approval_governance"].update(
                production_deployment_approved=True
            ),
            "production_deployment_separate",
        ),
    ],
)
def test_each_mandatory_gate_fails_closed(
    tmp_path: Path, mutation, failed_gate: str
) -> None:
    sources = deepcopy(_sources(go=True))
    mutation(sources)

    result = _run(tmp_path, sources)

    assert result["status"] == "PASS"
    assert result["decision"] == "NO_GO"
    assert result["gate_results"][failed_gate] is False
    assert failed_gate in result["failed_gates"]


def test_runner_requires_opt_in_exact_inventory_and_all_sources(tmp_path: Path) -> None:
    assert runner.run_release_decision({})["status"] == "SKIPPED"
    invalid = runner.run_release_decision(
        {runner.ACTIVATION_ENV: "1"},
        source_paths={"manifest": tmp_path / "manifest.json"},
    )
    assert invalid["failure_code"] == "release_decision_source_inventory_invalid"
    missing = runner.run_release_decision(
        {runner.ACTIVATION_ENV: "1"},
        source_paths={name: tmp_path / name for name in runner.SOURCE_PATHS},
    )
    assert missing["failure_code"] == "release_decision_source_evidence_unavailable"


def test_runner_rejects_naive_clock_and_covers_helpers(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    paths = _write_sources(tmp_path, _sources())
    failed = runner.run_release_decision(
        {runner.ACTIVATION_ENV: "1"},
        source_paths=paths,
        evaluated_at=datetime(2026, 10, 9, 9, 0),
    )
    assert failed["failure_code"] == "release_decision_evaluation_failed"
    assert failed["decision"] == "NO_GO"

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert runner._load_json(bad) == {}
    passing = {
        "status": "PASS",
        "decision": "NO_GO",
        "summary": {
            "passed_gate_count": 8,
            "gate_count": 10,
            "failed_gate_count": 2,
        },
    }
    assert "decision=NO_GO" in runner.summary_line(passing)
    assert runner.summary_line({"status": "FAIL"}).endswith("fail")
    assert runner.summary_line({"status": "SKIPPED"}).endswith("skipped")
    monkeypatch.setattr(runner, "run_release_decision", lambda **_kw: passing)
    assert runner.main(["--summary"]) == 0
    assert "gates=8/10" in capsys.readouterr().out
