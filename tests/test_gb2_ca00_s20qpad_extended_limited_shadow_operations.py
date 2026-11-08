from __future__ import annotations

import json

import pytest
import run_gb2_s20qpad_extended_limited_shadow_operations as smoke
from test_gb2_ca00_s20qpab_limited_shadow_operations import (
    FakeGenerationClient,
    _cases,
    _state_store,
)
from test_nex_cx_retrieval_answer_support_extended_limited_operations import (
    _decision_receipt,
)


def test_extended_operations_accept_exact_thirty_sample_window() -> None:
    client = FakeGenerationClient()
    state_store, events = _state_store()

    result = smoke.run_gb2_s20qpad_extended_limited_shadow_operations(
        _env(),
        state_store=state_store,
        generation_client=client,
        cases_document=_cases(),
        decision_receipt=_decision_receipt(),
    )

    assert result["status"] == "PASS", result
    assert result["decision"] == (
        "EXTENDED_LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED"
    )
    assert result["live_execution"]["sample_count"] == 30
    assert result["live_execution"]["provider_call_count"] == 30
    assert result["live_execution"]["wave_count"] == 8
    assert result["window"]["sample_cap_reached"] is True
    assert result["operations_status"] == "REVIEW_REQUIRED"
    assert result["checks"]["fresh_window_marker_verified"] is True
    assert result["checks"]["post_cap_request_provider_blocked"] is True
    assert "thirteenth_request_provider_blocked" not in result["checks"]
    assert result["checks"]["provider_p95_slo_preserved"] is True
    assert result["checks"]["e2e_p95_slo_preserved"] is True
    assert result["source_operator_decision"]["decision_receipt_hash"] == (
        _decision_receipt()["receipt_hash"]
    )
    assert result["next_boundary"] == (
        "EXTENDED_LIMITED_SHADOW_OPERATOR_REVIEW_DECISION"
    )
    assert result["holdout_accessed"] is False
    assert result["production_cutover_permitted"] is False
    assert client.calls == 30
    assert len(events.list_events(service_id="nex-cx")) > 30
    assert "samples=30" in smoke.summary_line(result)


def test_runner_requires_enablement_and_explicit_operator_approval() -> None:
    assert smoke.run_gb2_s20qpad_extended_limited_shadow_operations({})[
        "status"
    ] == "SKIPPED"
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    result = smoke.run_gb2_s20qpad_extended_limited_shadow_operations(
        {smoke.SMOKE_ENV: "1"}
    )
    assert result["failure_code"] == "operator_approval_required"


def test_runner_rejects_receipt_drift_before_provider_access() -> None:
    receipt = _decision_receipt()
    receipt["continuation_executed"] = True
    client = FakeGenerationClient()
    result = smoke.run_gb2_s20qpad_extended_limited_shadow_operations(
        _env(),
        generation_client=client,
        cases_document=_cases(),
        decision_receipt=receipt,
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "extended_limited_shadow_authorization_failed"
    assert result["failure_detail"] == {
        "exception": "LimitedShadowOperationsError"
    }
    assert result["provider_http_requests"] == 0
    assert client.calls == 0
    assert "=fail" in smoke.summary_line(result)


def test_runner_loads_receipt_path_and_rejects_incomplete_cases(tmp_path) -> None:
    receipt_path = tmp_path / "decision.json"
    receipt_path.write_text(json.dumps(_decision_receipt()), encoding="utf-8")
    state_store, _events = _state_store()
    result = smoke.run_gb2_s20qpad_extended_limited_shadow_operations(
        {**_env(), smoke.DECISION_RECEIPT_ENV: str(receipt_path)},
        state_store=state_store,
        generation_client=FakeGenerationClient(),
        cases_document={"cases": []},
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "extended_limited_shadow_runtime_operations_acceptance_failed"
    )


def test_runner_redaction_helpers_and_cli(tmp_path, monkeypatch, capsys) -> None:
    assert smoke._case_rows({}) == []
    with pytest.raises(ValueError, match="leaked"):
        smoke._assert_redacted(
            {"value": "private text"},
            {},
            [{"candidates": [{"text": "private text"}]}],
        )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpad_extended_limited_shadow_operations",
        lambda: {"status": "PASS", "live_execution": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpad_extended_limited_shadow_operations",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpad_extended_limited_shadow_operations",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.APPROVED_ENV: "1",
        smoke.OPERATOR_ENV: "operator-one",
    }
