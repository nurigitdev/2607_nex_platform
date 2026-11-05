from __future__ import annotations

import json

import run_gb2_s20qpv_extended_shadow_slo as smoke
from test_nex_cx_retrieval_answer_support_extended_shadow import _fixtures


def test_runner_records_met_slo_receipt_without_cutover(tmp_path) -> None:
    cutover, extended, design, policy, cases = _fixtures()
    target = tmp_path / "extended.json"
    slo_target = tmp_path / "slo.json"

    result = smoke.run_gb2_s20qpv_extended_shadow_slo(
        _env(),
        cutover_receipt=cutover,
        extended_receipt=extended,
        design=design,
        policy=policy,
        cases_document=cases,
        extended_receipt_path=target,
        slo_receipt_path=slo_target,
    )

    assert result["status"] == "PASS"
    assert result["background_slo_status"] == "MET"
    assert result["provider_http_requests"] == {"total": 30, "generation": 30}
    assert result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_activation_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert slo_target.stat().st_mode & 0o777 == 0o600
    assert json.loads(slo_target.read_text())["background_slo_status"] == "MET"
    assert "samples=30" in smoke.summary_line(result)
    assert "cutover=prohibited" in smoke.summary_line(result)


def test_runner_invokes_bounded_canary_and_consumes_written_receipt(tmp_path) -> None:
    cutover, extended, design, policy, cases = _fixtures()
    target = tmp_path / "extended.json"
    calls = []

    def canary(environ, **kwargs):
        calls.append((environ, kwargs))
        kwargs["receipt_path"].write_text(json.dumps(extended), encoding="utf-8")
        return {
            "status": "PASS",
            "provider_http_requests": {"total": 30, "generation": 30},
        }

    result = smoke.run_gb2_s20qpv_extended_shadow_slo(
        _env(),
        canary_runner=canary,
        cutover_receipt=cutover,
        design=design,
        policy=policy,
        cases_document=cases,
        extended_receipt_path=target,
        slo_receipt_path=tmp_path / "slo.json",
    )

    assert result["status"] == "PASS"
    assert len(calls) == 1
    assert calls[0][0][smoke.CANARY_SMOKE_ENV] == "1"
    assert calls[0][0][smoke.CANARY_APPROVED_ENV] == "1"
    assert calls[0][1]["cases_document"] == cases
    assert calls[0][1]["policy_document"] == policy


def test_runner_requires_approval_and_preserves_one_shot_evidence(tmp_path) -> None:
    assert smoke.run_gb2_s20qpv_extended_shadow_slo({})["status"] == "SKIPPED"
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpv_extended_shadow_slo({smoke.SMOKE_ENV: "1"})["failure_code"]
        == "operator_approval_required"
    )

    used = tmp_path / "used.json"
    used.write_text("{}", encoding="utf-8")
    result = smoke.run_gb2_s20qpv_extended_shadow_slo(
        _env(),
        extended_receipt_path=used,
        slo_receipt_path=tmp_path / "new.json",
    )
    assert result["failure_code"] == "extended_observation_already_consumed"

    result = smoke.run_gb2_s20qpv_extended_shadow_slo(
        _env(),
        extended_receipt={},
        extended_receipt_path=tmp_path / "new-extended.json",
        slo_receipt_path=used,
    )
    assert result["failure_code"] == "latency_slo_decision_already_recorded"


def test_runner_consumes_canary_and_contract_failures(tmp_path) -> None:
    cutover, _extended, design, policy, cases = _fixtures()

    result = smoke.run_gb2_s20qpv_extended_shadow_slo(
        _env(),
        canary_runner=lambda *_args, **_kwargs: {
            "status": "FAIL",
            "failure_code": "provider_failed",
        },
        cutover_receipt=cutover,
        design=design,
        policy=policy,
        cases_document=cases,
        extended_receipt_path=tmp_path / "extended.json",
        slo_receipt_path=tmp_path / "slo.json",
    )
    assert result["failure_code"] == "extended_shadow_observation_failed"
    assert result["failure_detail"] == {"canary_failure_code": "provider_failed"}

    design["status"] = "ACTIVE"
    result = smoke.run_gb2_s20qpv_extended_shadow_slo(
        _env(),
        cutover_receipt=cutover,
        extended_receipt={},
        design=design,
        policy=policy,
        cases_document=cases,
        extended_receipt_path=tmp_path / "other.json",
        slo_receipt_path=tmp_path / "other-slo.json",
    )
    assert result["failure_code"] == "extended_shadow_slo_failed"
    assert result["failure_detail"] == {"exception": "AnswerSupportExtendedShadowError"}
    assert "extended_shadow_slo_failed" in smoke.summary_line(result)


def test_runner_helpers_and_cli_preserve_terminal_evidence(
    tmp_path, monkeypatch, capsys
) -> None:
    value = tmp_path / "value.json"
    value.write_text('{"ok": true}', encoding="utf-8")
    assert smoke._load(value) == {"ok": True}
    value.write_text("[]", encoding="utf-8")
    try:
        smoke._load(value)
    except TypeError:
        pass
    else:
        raise AssertionError("list JSON must fail")

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpv_extended_shadow_slo",
        lambda: {
            "status": "PASS",
            "background_slo_status": "MET",
            "observed_metrics": {"sample_count": 30, "p95_latency_ms": 40_000},
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out

    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpv_extended_shadow_slo",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpv_extended_shadow_slo",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.APPROVED_ENV: "1",
        smoke.OPERATOR_ENV: "operator-one",
    }
