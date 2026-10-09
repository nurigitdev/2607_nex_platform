from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from nex_runtime.production_release import (
    build_release_evidence_manifest,
    evaluate_release_evidence_admission,
)
import run_s150_evidence_freshness_admission as runner


NOW = datetime(2026, 10, 9, 6, 0, tzinfo=UTC)
REVISION = "b" * 40
RELEASE_ID = "rc:s149:730196df68414600"
RELEASE_DIGEST = f"sha256:{'1' * 64}"


def _closure() -> dict:
    return {
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


def _manifest(observed_at: datetime | None = None) -> dict:
    return build_release_evidence_manifest(
        _closure(),
        source_revision=REVISION,
        observed_at=observed_at or NOW,
    )


def test_admission_accepts_exact_fresh_manifest() -> None:
    result = evaluate_release_evidence_admission(
        _manifest(),
        expected_release_candidate_id=RELEASE_ID,
        expected_release_set_digest=RELEASE_DIGEST,
        evaluated_at=NOW + timedelta(hours=23),
    )

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["age_seconds"] == 23 * 3600
    assert result["summary"] == {
        "check_count": 6,
        "passed_check_count": 6,
        "dependency_count": 3,
        "max_age_hours": 24,
    }


def test_admission_rejects_stale_mismatch_duplicate_and_future() -> None:
    stale = _manifest(NOW - timedelta(hours=25))
    stale["release_candidate_id"] = "wrong"
    stale["release_set_digest"] = f"sha256:{'9' * 64}"
    stale["dependency_evidence"][2]["digest"] = stale["dependency_evidence"][0]["digest"]
    result = evaluate_release_evidence_admission(
        stale,
        expected_release_candidate_id=RELEASE_ID,
        expected_release_set_digest=RELEASE_DIGEST,
        evaluated_at=NOW,
    )
    assert result["status"] == "FAIL"
    assert {
        "manifest_validation_passed",
        "release_candidate_id_exact",
        "release_set_digest_exact",
        "go_live_window_24h",
        "dependency_digests_unique",
    }.issubset(result["failed_checks"])

    future = _manifest(NOW + timedelta(minutes=6))
    result = evaluate_release_evidence_admission(
        future,
        expected_release_candidate_id=RELEASE_ID,
        expected_release_set_digest=RELEASE_DIGEST,
        evaluated_at=NOW,
    )
    assert result["checks"]["go_live_window_24h"] is False


def test_admission_validates_arguments_and_missing_timestamp() -> None:
    manifest = _manifest()
    manifest["observed_at"] = "invalid"
    result = evaluate_release_evidence_admission(
        manifest,
        expected_release_candidate_id=RELEASE_ID,
        expected_release_set_digest=RELEASE_DIGEST,
        evaluated_at=NOW,
    )
    assert result["age_seconds"] is None
    assert result["checks"]["go_live_window_24h"] is False

    for evaluated_at, max_age in ((datetime(2026, 10, 9), 24), (NOW, 0), (NOW, True)):
        try:
            evaluate_release_evidence_admission(
                _manifest(),
                expected_release_candidate_id=RELEASE_ID,
                expected_release_set_digest=RELEASE_DIGEST,
                evaluated_at=evaluated_at,
                max_age_hours=max_age,
            )
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("ValueError was not raised")


def test_runner_skip_pass_fail_and_atomic_output(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    closure_path = tmp_path / "closure.json"
    output_path = tmp_path / "admission.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    closure_path.write_text(json.dumps(_closure()), encoding="utf-8")

    skipped = runner.run_evidence_freshness_admission(
        manifest_path=manifest_path,
        closure_path=closure_path,
        output_path=output_path,
        environ={},
        evaluated_at=NOW,
    )
    assert skipped["status"] == "SKIPPED"

    passed = runner.run_evidence_freshness_admission(
        manifest_path=manifest_path,
        closure_path=closure_path,
        output_path=output_path,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert passed["status"] == "PASS", passed
    assert json.loads(output_path.read_text())["status"] == "PASS"

    stale = _manifest(NOW - timedelta(hours=25))
    manifest_path.write_text(json.dumps(stale), encoding="utf-8")
    failed = runner.run_evidence_freshness_admission(
        manifest_path=manifest_path,
        closure_path=closure_path,
        output_path=output_path,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert failed["status"] == "FAIL"
    assert failed["next_slice"] == "blocked"

    missing = runner.run_evidence_freshness_admission(
        manifest_path=tmp_path / "missing.json",
        closure_path=closure_path,
        output_path=output_path,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert missing["status"] == "FAIL"

    invalid_clock = runner.run_evidence_freshness_admission(
        manifest_path=manifest_path,
        closure_path=closure_path,
        output_path=output_path,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=datetime(2026, 10, 9),
    )
    assert invalid_clock["status"] == "FAIL"
    assert invalid_clock["reason"] == "evaluated_at must be timezone-aware"


def test_runner_helpers_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    assert runner._load_json(bad) == {}
    assert runner._mapping(None) == {}
    assert runner.summary_line({"status": "SKIPPED"}) == "s150_evidence_admission=skipped"
    assert runner.summary_line({"status": "FAIL"}) == "s150_evidence_admission=fail"
    passing = {
        "status": "PASS",
        "summary": {
            "passed_check_count": 6,
            "check_count": 6,
            "dependency_count": 3,
            "max_age_hours": 24,
        },
    }
    assert "checks=6/6" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_evidence_freshness_admission", lambda **kwargs: passing)
    assert runner.main(["--summary"]) == 0
    assert "s150_evidence_admission=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_evidence_freshness_admission",
        lambda **kwargs: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
