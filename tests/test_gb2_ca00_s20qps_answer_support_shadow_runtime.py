from __future__ import annotations

import json
from pathlib import Path

import pytest

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_cx.retrieval_answer_support_collection import (
    validate_answer_support_request_profile,
)
from nex_cx.retrieval_answer_support_signal import (
    validate_answer_support_signal_design,
)
from run_gb2_s20qps_answer_support_shadow_runtime import (
    SMOKE_ENV,
    run_gb2_s20qps_answer_support_shadow_runtime,
    summary_line,
)
import run_gb2_s20qps_answer_support_shadow_runtime as smoke


ROOT = Path(__file__).resolve().parents[1]
REVISION = "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"


def test_protected_shadow_runtime_passes_without_holdout_or_database() -> None:
    report, shadow_design, signal_design, request_profile = _fixtures()

    result = run_gb2_s20qps_answer_support_shadow_runtime(
        {SMOKE_ENV: "1"},
        readiness_report=report,
        shadow_design=shadow_design,
        signal_design=signal_design,
        request_profile=request_profile,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "SHADOW_RUNTIME_EVALUATOR_INTEGRATED_NOT_ACTIVATED"
    assert result["outcome_statuses"] == ["OBSERVED", "SKIPPED", "FAILED"]
    assert result["provider_calls"] == 2
    assert result["database_calls"] == 0
    assert result["holdout_reexecuted"] is False
    assert result["runtime_activation_permitted"] is False
    assert result["checks"]["private_text_not_persisted"] is True
    assert "activation=not_activated" in summary_line(result)


def test_protected_shadow_runtime_is_disabled_by_default() -> None:
    result = run_gb2_s20qps_answer_support_shadow_runtime({})

    assert result["status"] == "SKIPPED"
    assert summary_line(result).endswith("=skipped")


def test_protected_shadow_runtime_rejects_design_or_manifest_drift() -> None:
    report, shadow_design, signal_design, request_profile = _fixtures()
    shadow_design["execution_boundary"]["shadow_decision_user_visible"] = True

    result = run_gb2_s20qps_answer_support_shadow_runtime(
        {SMOKE_ENV: "1"},
        readiness_report=report,
        shadow_design=shadow_design,
        signal_design=signal_design,
        request_profile=request_profile,
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "answer_support_shadow_runtime_invalid"
    assert result["provider_calls"] == 0
    assert "answer_support_shadow_runtime_invalid" in summary_line(result)

    report, shadow_design, signal_design, request_profile = _fixtures()
    report["manifest"]["candidate_profile"]["threshold"] = 0.1
    result = run_gb2_s20qps_answer_support_shadow_runtime(
        {SMOKE_ENV: "1"},
        readiness_report=report,
        shadow_design=shadow_design,
        signal_design=signal_design,
        request_profile=request_profile,
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "cx.answer_support_shadow.configuration_invalid"


def test_runner_file_helpers_and_cli_output(tmp_path, monkeypatch, capsys) -> None:
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text('{"ok": true}', encoding="utf-8")
    assert smoke._load(mapping_path) == {"ok": True}

    list_path = tmp_path / "list.json"
    list_path.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        smoke._load(list_path)
    with pytest.raises(TypeError, match="invalid"):
        smoke._mapping([], "bad mapping")

    output = tmp_path / "result.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qps_answer_support_shadow_runtime",
        lambda: {"status": "PASS"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "PASS"}

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qps_answer_support_shadow_runtime",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_runner_rejects_failed_protected_checks(monkeypatch) -> None:
    report, shadow_design, signal_design, request_profile = _fixtures()

    class NonAdmittedRuntime:
        def __init__(self, *, outcome_sink, **_kwargs) -> None:
            self.outcome_sink = outcome_sink

        def observe(self, *, primary_package, **_kwargs):
            outcome = {
                "status": "SKIPPED",
                "shadow_decision": "NOT_EVALUATED",
                "skip_reason": "FORCED",
                "user_visible": False,
                "runtime_activation_permitted": False,
            }
            self.outcome_sink.record(outcome)
            return outcome

    monkeypatch.setattr(smoke, "AnswerSupportShadowRuntime", NonAdmittedRuntime)
    result = run_gb2_s20qps_answer_support_shadow_runtime(
        {SMOKE_ENV: "1"},
        readiness_report=report,
        shadow_design=shadow_design,
        signal_design=signal_design,
        request_profile=request_profile,
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "answer_support_shadow_runtime_invalid"


def _fixtures():
    request_profile = json.loads(
        (ROOT / "scripts/smoke/data/s136_answer_support_generation_profile_v1.json").read_text(
            encoding="utf-8"
        )
    )
    signal_design = json.loads(
        (ROOT / "scripts/smoke/data/s136_answer_support_signal_v1_design.json").read_text(
            encoding="utf-8"
        )
    )
    request_hash = validate_answer_support_request_profile(request_profile)[
        "profile_hash"
    ]
    signal_hash = validate_answer_support_signal_design(signal_design)["design_hash"]
    profile = {
        "profile_schema_version": "cx_answer_support_runtime_profile.v1",
        "profile_id": "answer-support-contradiction-aware-v2",
        "profile_version": "1.0.0",
        "status": "READY_FOR_SHADOW",
        "policy_id": "cx_answer_support_contradiction_aware_ready_v2",
        "score_semantics": "WEIGHTED_BOUNDED_ORDINAL_NOT_PROBABILITY",
        "threshold": 0.46375,
        "threshold_inclusive": True,
        "provider_binding": {
            "deployment_id": "dgx-qwen3-5-9b-9116",
            "model_revision": REVISION,
            "provider_alias": "general-llm-default",
            "provider_type": "vllm",
            "request_profile_id": "s136-answer-support-generation-json-v1",
            "score_semantics_id": "bounded-ordinal-answer-support-v1",
        },
        "request_profile_hash": request_hash,
        "dataset": {
            "dataset_id": "dataset-v4",
            "dataset_semantic_sha256": "sha256:" + "a" * 64,
            "partition": "HOLDOUT",
        },
        "evidence_binding": {
            "execution_id": "execution",
            "authorization_hash": "sha256:" + "b" * 64,
            "receipt_hash": "sha256:" + "c" * 64,
            "evaluation_hash": "sha256:" + "d" * 64,
        },
        "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
        "runtime_activation_permitted": False,
    }
    profile["profile_hash"] = semantic_sha256_hash_ref(profile)
    manifest = {
        "manifest_schema_version": (
            "cx_answer_support_runtime_activation_readiness_manifest.v1"
        ),
        "status": "PASS",
        "decision": "READY_FOR_SHADOW_RUNTIME_INTEGRATION",
        "activation_status": "NOT_ACTIVATED",
        "candidate_profile": profile,
        "rollout_boundary": {
            "first_stage": "SHADOW",
            "shadow_decision_user_visible": False,
            "fail_closed_on_binding_drift": True,
        },
        "holdout_reexecution_permitted": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    manifest["manifest_hash"] = semantic_sha256_hash_ref(manifest)
    shadow_design = json.loads(
        (ROOT / "scripts/smoke/data/s136_answer_support_shadow_runtime_v1_design.json").read_text(
            encoding="utf-8"
        )
    )
    shadow_design["source_binding"].update(
        {
            "readiness_manifest_hash": manifest["manifest_hash"],
            "runtime_profile_hash": profile["profile_hash"],
            "request_profile_hash": request_hash,
            "signal_design_hash": signal_hash,
        }
    )
    return {"manifest": manifest}, shadow_design, signal_design, request_profile
