from __future__ import annotations

import json
from pathlib import Path

import pytest
import run_gb2_s20ql_calibration_policy_audit as smoke


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _passing_execution() -> tuple[dict, dict]:
    current = {
        "status": "PASS",
        "binding": {"embedding_model_revision": "immutable"},
        "source_collection": {"repeat_count": 5},
        "provider_request_counts": {"embedding": 360, "reranking": 200},
        "persistence": {"raw_query_persisted": False},
        "checks": {"cleanup_complete": True},
    }
    source = {"status": "PASS"}
    return current, source


def test_skip_success_summary_and_redaction(monkeypatch, tmp_path: Path) -> None:
    assert smoke.run_gb2_s20ql_calibration_policy_audit({})["status"] == "SKIPPED"
    historical = _write(tmp_path / "historical.json", {"status": "PASS"})
    audit = {
        "decision": {"status": "CORRECTIVE_DATASET_AND_POLICY_DESIGN_REQUIRED"},
        "constraint_gap": {"false_ready_excess": 1, "true_ready_deficit": 4},
    }
    monkeypatch.setattr(smoke, "_audit_from_execution", lambda **_kwargs: audit)
    result = smoke.run_gb2_s20ql_calibration_policy_audit(
        {
            smoke.SMOKE_ENV: "1",
            smoke.HISTORICAL_PATH_ENV: str(historical),
            "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-key",
        },
        executor=lambda *_args, **_kwargs: _passing_execution(),
    )
    assert result["status"] == "PASS"
    assert result["database_identity"]["database"] == "nex_cx_test"
    assert "private-key" not in json.dumps(result)
    assert "false_ready_excess=1" in smoke.summary_line(result)


def test_missing_malformed_and_failed_source_fail_closed(tmp_path: Path) -> None:
    missing = smoke.run_gb2_s20ql_calibration_policy_audit(
        {smoke.SMOKE_ENV: "1"}
    )
    assert missing["failure_code"].endswith("_REQUIRED")

    malformed = _write(tmp_path / "malformed.json", [])
    invalid = smoke.run_gb2_s20ql_calibration_policy_audit(
        {
            smoke.SMOKE_ENV: "1",
            smoke.HISTORICAL_PATH_ENV: str(malformed),
        }
    )
    assert invalid["detail"] == "TypeError"

    historical = _write(tmp_path / "historical.json", {"status": "PASS"})
    failed = smoke.run_gb2_s20ql_calibration_policy_audit(
        {
            smoke.SMOKE_ENV: "1",
            smoke.HISTORICAL_PATH_ENV: str(historical),
        },
        executor=lambda *_args, **_kwargs: ({"status": "FAIL"}, {"status": "PASS"}),
    )
    assert failed["failure_code"] == "S20QL_LIVE_SOURCE_NOT_ADMITTED"


def test_audit_from_execution_rejects_missing_runs_and_tolerances(
    monkeypatch, tmp_path: Path,
) -> None:
    dataset = _write(
        tmp_path / "dataset.json",
        {
            "dataset_schema_version": "model_calibration_dataset.v3",
            "dataset_id": "dataset",
            "cases": [{}] * 60,
        },
    )
    with pytest.raises(smoke.CalibrationPolicyAuditError, match="BASELINE_RUN"):
        smoke._audit_from_execution(
            dataset_path=dataset,
            source={"repeat_collection": {}},
            current={},
            historical={},
        )

    with pytest.raises(smoke.CalibrationPolicyAuditError, match="OBSERVATIONS"):
        smoke._audit_from_execution(
            dataset_path=dataset,
            source={"repeat_collection": {"runs": [{}]}},
            current={},
            historical={},
        )

    monkeypatch.setattr(
        smoke,
        "build_expanded_candidate_relevance_calibration_samples",
        lambda _observations: [],
    )
    with pytest.raises(smoke.CalibrationPolicyAuditError, match="TOLERANCES"):
        smoke._audit_from_execution(
            dataset_path=dataset,
            source={"repeat_collection": {"runs": [{"candidate_observations": []}]}},
            current={"provenance": {"numeric_tolerance": 0.0005}},
            historical={},
        )

    monkeypatch.setattr(
        smoke,
        "audit_calibration_dataset_and_package_policy",
        lambda *_args, **_kwargs: {"status": "AUDITED"},
    )
    audited = smoke._audit_from_execution(
        dataset_path=dataset,
        source={"repeat_collection": {"runs": [{"candidate_observations": []}]}},
        current={
            "provenance": {"numeric_tolerance": 0.0005},
            "candidate_relevance_calibration": {
                "repeatability": {"signal_tolerances": {"reranker_score": 0.0005}}
            },
        },
        historical={},
    )
    assert audited == {"status": "AUDITED"}


def test_execute_capture_helpers_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        smoke.s20qe,
        "run_gb2_s20qe_v3_calibration_collection",
        lambda *_args, **_kwargs: {"status": "PASS", "source": True},
    )
    monkeypatch.setattr(
        smoke.s20qi,
        "run_gb2_s20qi_candidate_relevance_signal_expansion",
        lambda _env, *, collector, **_kwargs: (
            collector({"enabled": "1"}) and {"status": "PASS"}
        ),
    )
    current, source = smoke._execute_live_source(
        {}, requester=None, repeatability_path=tmp_path, revision_path=tmp_path
    )
    assert current["status"] == "PASS"
    assert source["source"] is True

    monkeypatch.setattr(
        smoke.s20qi,
        "run_gb2_s20qi_candidate_relevance_signal_expansion",
        lambda *_args, **_kwargs: {"status": "FAIL"},
    )
    with pytest.raises(smoke.CalibrationPolicyAuditError, match="SOURCE_MISSING"):
        smoke._execute_live_source(
            {}, requester=None, repeatability_path=tmp_path, revision_path=tmp_path
        )

    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "private-key"},
            {"NEX_MO_REMOTE_RERANKER_API_KEY": "private-key"},
        )
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert smoke.summary_line({}).endswith("error=unknown")

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20ql_calibration_policy_audit",
        lambda env, **kwargs: (
            captured.update({"env": env, **kwargs})
            or {"status": "PASS", "audit": {"decision": {}, "constraint_gap": {}}}
        ),
    )
    output = tmp_path / "output.json"
    historical = tmp_path / "historical.json"
    assert smoke.main(["--historical", str(historical), "--output", str(output), "--summary"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "calibration_policy_audit=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20ql_calibration_policy_audit",
        lambda *_args, **_kwargs: {"status": "FAIL", "failure_code": "blocked"},
    )
    assert smoke.main([]) == 1
