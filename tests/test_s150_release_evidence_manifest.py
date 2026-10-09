from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import nex_runtime.production_release as release
from nex_runtime.production_release import (
    build_release_evidence_manifest,
    canonical_digest,
    validate_release_evidence_manifest,
)
import run_s150_release_evidence_manifest as runner


NOW = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)
REVISION = "a" * 40


def _closure() -> dict:
    return {
        "status": "PASS",
        "release_binding": {
            "release_candidate_id": "rc:s149:730196df68414600",
            "release_set_digest": f"sha256:{'1' * 64}",
            "admission_evidence_digest": f"sha256:{'2' * 64}",
            "full_regression_evidence_digest": "3" * 64,
        },
        "full_regression": {
            "status": "PASS",
            "passed_test_count": 13578,
            "failed_test_count": 0,
            "statement_coverage": 97.96,
            "branch_coverage": 96.89,
        },
        "summary": {"backlog_count": 5},
        "s150_handoff": {
            "external_notification_waiver": "REQUIRED_NOT_GRANTED",
            "production_go_eligible": False,
        },
        "production_deployment_approved": False,
    }


def test_manifest_build_and_validation_are_release_bound() -> None:
    closure = _closure()
    manifest = build_release_evidence_manifest(
        closure,
        source_revision=REVISION,
        observed_at=NOW,
    )
    result = validate_release_evidence_manifest(manifest)

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 11,
        "passed_check_count": 11,
        "dependency_count": 3,
        "backlog_count": 5,
    }
    assert manifest["dependency_evidence"][1]["digest"] == f"sha256:{'3' * 64}"
    assert manifest["manifest_digest"].startswith("sha256:")
    assert manifest["dependency_evidence"][2]["digest"] == canonical_digest(closure)


def test_manifest_validation_fails_closed_for_drift_and_privacy() -> None:
    manifest = build_release_evidence_manifest(
        _closure(),
        source_revision=REVISION,
        observed_at=NOW,
    )
    manifest["release_candidate_id"] = "wrong"
    manifest["dependency_evidence"] = "wrong"
    manifest["full_regression"] = {"status": "FAIL", "secret": "value"}
    manifest["manifest_digest"] = "wrong"
    result = validate_release_evidence_manifest(manifest)

    assert result["status"] == "FAIL"
    assert {
        "release_identity_valid",
        "dependency_inventory_exact",
        "dependency_digests_valid",
        "full_regression_passed",
        "privacy_clean",
        "manifest_digest_valid",
    }.issubset(result["failed_checks"])
    assert result["privacy_violations"] == ["$.full_regression.secret"]


def test_manifest_build_rejects_invalid_inputs() -> None:
    for closure, revision, observed_at, message in (
        ({"status": "FAIL"}, REVISION, NOW, "S149 closure must pass"),
        (_closure(), "short", NOW, "source_revision"),
        (_closure(), REVISION, datetime(2026, 10, 9), "timezone-aware"),
    ):
        try:
            build_release_evidence_manifest(
                closure,
                source_revision=revision,
                observed_at=observed_at,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:  # pragma: no cover
            raise AssertionError("ValueError was not raised")


def test_manifest_private_helpers_cover_digest_time_and_privacy_edges() -> None:
    sha = f"sha256:{'a' * 64}"
    assert release._normalized_digest(sha) == sha
    assert release._normalized_digest("b" * 64) == f"sha256:{'b' * 64}"
    assert release._normalized_digest("invalid") == "invalid"
    assert release._parse_timestamp(None) is None
    assert release._parse_timestamp("invalid") is None
    assert release._parse_timestamp("2026-10-09T05:00:00") is None
    assert release._parse_timestamp("2026-10-09T05:00:00Z") == NOW
    assert release._privacy_violations([{"api_key": "hidden"}]) == [
        "$[0].api_key"
    ]
    assert release._mapping(None) == {}


def test_runner_skip_pass_failure_and_atomic_output(tmp_path: Path) -> None:
    closure = tmp_path / "closure.json"
    output = tmp_path / "manifest.json"
    closure.write_text(json.dumps(_closure()), encoding="utf-8")

    skipped = runner.run_release_evidence_manifest(
        closure_path=closure,
        output_path=output,
        environ={},
    )
    assert skipped["status"] == "SKIPPED"
    assert not output.exists()

    passed = runner.run_release_evidence_manifest(
        closure_path=closure,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        source_revision=REVISION,
        observed_at=NOW,
    )
    assert passed["status"] == "PASS", passed
    assert output.is_file()
    assert json.loads(output.read_text())["status"] == "PASS"
    assert not output.with_suffix(".json.tmp").exists()

    missing = runner.run_release_evidence_manifest(
        closure_path=tmp_path / "missing.json",
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        source_revision=REVISION,
        observed_at=NOW,
    )
    assert missing["status"] == "FAIL"

    closure.write_text('{"status": "FAIL"}', encoding="utf-8")
    invalid = runner.run_release_evidence_manifest(
        closure_path=closure,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        source_revision=REVISION,
        observed_at=NOW,
    )
    assert invalid["status"] == "FAIL"


def test_runner_does_not_write_failed_validation(monkeypatch, tmp_path: Path) -> None:
    closure = tmp_path / "closure.json"
    output = tmp_path / "manifest.json"
    closure.write_text(json.dumps(_closure()), encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "validate_release_evidence_manifest",
        lambda manifest: {
            "status": "FAIL",
            "checks": {"forced": False},
            "failed_checks": ["forced"],
            "summary": {},
        },
    )

    result = runner.run_release_evidence_manifest(
        closure_path=closure,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        source_revision=REVISION,
        observed_at=NOW,
    )

    assert result["status"] == "FAIL"
    assert result["next_slice"] == "blocked"
    assert not output.exists()


def test_runner_helpers_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    assert runner._load_json(bad) == {}
    bad.write_text("[]", encoding="utf-8")
    assert runner._load_json(bad) == {}

    class Completed:
        returncode = 0
        stdout = REVISION + "\n"

    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: Completed())
    assert runner._git_revision(tmp_path) == REVISION
    Completed.returncode = 1
    try:
        runner._git_revision(tmp_path)
    except ValueError as exc:
        assert "unavailable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ValueError was not raised")

    assert runner.summary_line({"status": "SKIPPED"}) == "s150_release_manifest=skipped"
    assert runner.summary_line({"status": "FAIL"}) == "s150_release_manifest=fail"
    passing = {
        "status": "PASS",
        "summary": {
            "passed_check_count": 11,
            "check_count": 11,
            "dependency_count": 3,
            "backlog_count": 5,
        },
    }
    assert "checks=11/11" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_release_evidence_manifest", lambda **kwargs: passing)
    assert runner.main(["--summary"]) == 0
    assert "s150_release_manifest=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_release_evidence_manifest",
        lambda **kwargs: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
