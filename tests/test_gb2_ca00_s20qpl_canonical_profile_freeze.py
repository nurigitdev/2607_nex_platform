from __future__ import annotations

import json

import run_gb2_s20qpl_canonical_profile_freeze as smoke


def _source() -> dict:
    return json.loads(smoke.SOURCE_PATH.read_text(encoding="utf-8"))


def _design() -> dict:
    return json.loads(smoke.DESIGN_PATH.read_text(encoding="utf-8"))


def _freeze() -> dict:
    return {
        "status": "CANONICAL_PROFILE_FROZEN_FRESH_CALIBRATION_REQUIRED",
        "canonical_profile": {
            "profile_id": "answer-support-contradiction-aware-v2",
            "threshold": None,
        },
        "evidence_plan": {
            "existing_evidence_role": "DIAGNOSTIC_ONLY_NOT_THRESHOLD_ADMISSIBLE"
        },
        "holdout_access_permitted": False,
        "runtime_activation_permitted": False,
    }


def test_skip_profile_and_failure_guards() -> None:
    assert smoke.run_gb2_s20qpl_canonical_profile_freeze({})["status"] == "SKIPPED"
    assert smoke.run_gb2_s20qpl_canonical_profile_freeze(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    assert smoke.run_gb2_s20qpl_canonical_profile_freeze(
        {smoke.SMOKE_ENV: "1", smoke.SOURCE_ENV: "/missing"}
    )["failure_code"] == "canonical_profile_freeze_failed"


def test_runner_passes_and_reports_failed_checks() -> None:
    result = smoke.run_gb2_s20qpl_canonical_profile_freeze(
        {smoke.SMOKE_ENV: "1"},
        source=_source(),
        design=_design(),
        freezer=lambda *_args, **_kwargs: _freeze(),
    )
    assert result["status"] == "PASS"
    assert result["new_provider_calls"] == 0
    assert "threshold=unset" in smoke.summary_line(result)

    source = _source()
    source["status"] = "FAIL"
    result = smoke.run_gb2_s20qpl_canonical_profile_freeze(
        {smoke.SMOKE_ENV: "1"},
        source=source,
        design=_design(),
        freezer=lambda *_args, **_kwargs: _freeze(),
    )
    assert result["status"] == "FAIL"
    assert result["failed_checks"] == ["p_k_evidence_passed"]


def test_source_loading_summary_and_main(tmp_path, monkeypatch, capsys) -> None:
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(_source()), encoding="utf-8")
    result = smoke.run_gb2_s20qpl_canonical_profile_freeze(
        {smoke.SMOKE_ENV: "1", smoke.SOURCE_ENV: str(source_path)},
        freezer=lambda *_args, **_kwargs: _freeze(),
    )
    assert result["status"] == "PASS"
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    try:
        smoke._load(invalid)
    except TypeError as exc:
        assert "object" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("non-object JSON must be rejected")
    try:
        smoke._mapping([], "audit")
    except TypeError as exc:
        assert "audit" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("non-mapping audit must be rejected")
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "bad"}
    )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpl_canonical_profile_freeze",
        lambda: {"status": "PASS", "freeze": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text()
    assert "=pass" in capsys.readouterr().out
