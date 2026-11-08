from __future__ import annotations

import json

import run_gb2_s20qph_answer_support_signal_contract as smoke


def _design() -> dict:
    return json.loads(smoke.DESIGN_PATH.read_text(encoding="utf-8"))


def test_skip_profile_and_design_guards(tmp_path) -> None:
    assert smoke.run_gb2_s20qph_answer_support_signal_contract({})["status"] == "SKIPPED"
    assert smoke.run_gb2_s20qph_answer_support_signal_contract(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    result = smoke.run_gb2_s20qph_answer_support_signal_contract(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DESIGN_ENV: str(tmp_path / "missing.json"),
        }
    )
    assert result["failure_code"] == "design_missing"


def test_contract_smoke_passes_without_provider_db_or_holdout() -> None:
    result = smoke.run_gb2_s20qph_answer_support_signal_contract(
        {smoke.SMOKE_ENV: "1"}, design=_design()
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "CONTRACT_FROZEN_FOR_LIVE_COLLECTION_DESIGN"
    assert result["provider_calls"] == 0
    assert result["database_calls"] == 0
    assert result["holdout_opened"] is False
    assert result["forbidden_persisted_keys"] == []
    assert result["classification_counts"]["CONTRADICTORY_EVIDENCE"] == 1
    assert "provider=neutral" in smoke.summary_line(result)


def test_contract_smoke_maps_invalid_design_to_fail_closed() -> None:
    design = _design()
    design["safety"]["runtime_activation_permitted"] = True
    result = smoke.run_gb2_s20qph_answer_support_signal_contract(
        {smoke.SMOKE_ENV: "1"}, design=design
    )
    assert result["failure_code"] == "contract_invalid"
    assert "safety" in result["failure_detail"]


def test_nested_key_scan_json_loader_and_failure_summary(tmp_path) -> None:
    assert smoke._nested_keys({"outer": [{"text": "secret"}]}) == {"outer", "text"}
    missing = tmp_path / "missing.json"
    assert smoke._load_json(missing) is None
    sequence = tmp_path / "sequence.json"
    sequence.write_text("[]", encoding="utf-8")
    assert smoke._load_json(sequence) is None
    mapping = tmp_path / "mapping.json"
    mapping.write_text('{"status":"PASS"}', encoding="utf-8")
    assert smoke._load_json(mapping) == {"status": "PASS"}
    assert "checks=bad" in smoke.summary_line(
        {"status": "FAIL", "failed_checks": ["bad"]}
    )
    assert "unknown" in smoke.summary_line({"status": "FAIL"})


def test_main_writes_pass_skip_and_failure_results(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qph_answer_support_signal_contract",
        lambda: {"status": "PASS"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text(encoding="utf-8")
    assert "=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qph_answer_support_signal_contract",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qph_answer_support_signal_contract",
        lambda: {"status": "FAIL", "failure_code": "broken"},
    )
    assert smoke.main(["--output", str(output)]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
