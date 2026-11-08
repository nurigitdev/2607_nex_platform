from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import run_gb2_s20qpt_shadow_canary_operations as smoke
from nex_cx.retrieval_answer_support_collection import (
    validate_answer_support_request_profile,
)
from nex_cx.retrieval_answer_support_signal import (
    validate_answer_support_signal_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_gb2_s20qpt_shadow_canary_operations import (
    APPROVED_ENV,
    OPERATOR_ENV,
    SMOKE_ENV,
    run_gb2_s20qpt_shadow_canary_operations,
    summary_line,
)

ROOT = Path(__file__).resolve().parents[1]
REVISION = "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"
ENDPOINT = "http://provider.test:9116/v1/chat/completions"
NOW = datetime(2026, 11, 5, 1, 0, tzinfo=UTC)


def test_protected_live_canary_passes_bounded_operator_approved_run(tmp_path) -> None:
    fixtures = _fixtures()
    calls = []

    def requester(method: str, url: str, **kwargs):
        calls.append((method, url))
        messages = kwargs["json"]["messages"]
        request = json.loads(messages[1]["content"])
        items = [
            {
                "candidate_id": row["candidate_id"],
                "classification": "SUPPORTING_EVIDENCE",
                "answer_support_score": 0.9,
                "contradiction_score": 0.05,
            }
            for row in request["candidates"]
        ]
        return httpx.Response(
            200,
            json={
                "id": "completion-one",
                "model": "Qwen3.5-9B",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"items": items}),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                },
            },
            request=httpx.Request(method, url),
        )

    receipt = tmp_path / "receipt.json"
    result = run_gb2_s20qpt_shadow_canary_operations(
        _env(),
        requester=requester,
        clock=lambda: NOW,
        receipt_path=receipt,
        **fixtures,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "SHADOW_CANARY_ACCEPTED_OPERATOR_REVIEW_REQUIRED"
    assert result["provider_http_requests"] == {"total": 6, "generation": 6}
    assert result["canary_snapshot"]["status"] == "COMPLETED"
    assert result["canary_snapshot"]["failed_count"] == 0
    assert result["canary_snapshot"]["latency_sample_count"] == 6
    assert result["runtime_activation_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert len(calls) == 6
    assert all(url == ENDPOINT for _, url in calls)
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert json.loads(receipt.read_text())["status"] == "PASS"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "provider.test" not in serialized
    assert "secret-key" not in serialized
    assert "cutover=operator_review_required" in summary_line(result)


def test_canary_requires_enablement_approval_configuration_and_one_shot(
    tmp_path,
) -> None:
    assert run_gb2_s20qpt_shadow_canary_operations({})["status"] == "SKIPPED"
    assert summary_line({"status": "SKIPPED"}).endswith("=skipped")

    result = run_gb2_s20qpt_shadow_canary_operations({SMOKE_ENV: "1"})
    assert result["failure_code"] == "operator_approval_required"

    result = run_gb2_s20qpt_shadow_canary_operations(
        {SMOKE_ENV: "1", APPROVED_ENV: "1", OPERATOR_ENV: "operator"},
        artifact_evidence=_artifact(),
    )
    assert result["failure_code"] == "configuration_invalid"

    receipt = tmp_path / "used.json"
    receipt.write_text("{}", encoding="utf-8")
    result = run_gb2_s20qpt_shadow_canary_operations(
        _env(),
        artifact_evidence=_artifact(),
        receipt_path=receipt,
    )
    assert result["failure_code"] == "canary_authorization_already_consumed"
    assert "already_consumed" in summary_line(result)


def test_canary_failure_is_redacted_and_preserves_fallback(tmp_path) -> None:
    fixtures = _fixtures()

    def requester(method: str, url: str, **_kwargs):
        return httpx.Response(
            503,
            json={"error": "private upstream detail"},
            request=httpx.Request(method, url),
        )

    result = run_gb2_s20qpt_shadow_canary_operations(
        _env(),
        requester=requester,
        clock=lambda: NOW,
        receipt_path=tmp_path / "receipt.json",
        **fixtures,
    )

    assert result["status"] == "FAIL"
    assert result["runtime_activation_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert "private upstream detail" not in json.dumps(result)


def test_runner_rejects_design_and_case_drift(tmp_path) -> None:
    fixtures = _fixtures()
    fixtures["canary_design"] = dict(fixtures["canary_design"])
    fixtures["canary_design"]["status"] = "ACTIVE"
    result = run_gb2_s20qpt_shadow_canary_operations(
        _env(),
        requester=lambda *_args, **_kwargs: None,
        clock=lambda: NOW,
        receipt_path=tmp_path / "design.json",
        **fixtures,
    )
    assert result["failure_code"] == "shadow_canary_execution_failed"
    assert result["provider_http_requests"]["total"] == 0

    fixtures = _fixtures()
    fixtures["cases_document"] = dict(fixtures["cases_document"])
    fixtures["cases_document"]["cases"] = []
    result = run_gb2_s20qpt_shadow_canary_operations(
        _env(),
        requester=lambda *_args, **_kwargs: None,
        clock=lambda: NOW,
        receipt_path=tmp_path / "cases.json",
        **fixtures,
    )
    assert result["status"] == "FAIL"


def test_runner_helpers_and_cli(tmp_path, monkeypatch, capsys) -> None:
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
        "run_gb2_s20qpt_shadow_canary_operations",
        lambda: {"status": "PASS"},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpt_shadow_canary_operations",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1

    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpt_shadow_canary_operations",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"


def test_runner_guard_helpers_reject_drift_and_leakage(tmp_path, monkeypatch) -> None:
    cases = _load("scripts/smoke/data/s136_answer_support_shadow_canary_v1_cases.json")
    invalid_cases = dict(cases)
    invalid_cases["cases"] = [
        *cases["cases"][:-1],
        {**cases["cases"][-1], "purpose": "search"},
    ]
    try:
        smoke._validate_cases(invalid_cases, maximum_calls=6)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid purpose must fail")

    binding = _fixtures()["readiness_report"]["manifest"]["candidate_profile"][
        "provider_binding"
    ]
    for environment, revision in (
        (_env(), "hf:" + "0" * 40),
        ({**_env(), "NEX_MO_VLLM_MODEL_REVISION": "other"}, REVISION),
        ({**_env(), "NEX_MO_VLLM_DEPLOYMENT_ID": "other"}, REVISION),
    ):
        try:
            smoke._bind_effective_provider(environment, binding, revision)
        except ValueError:
            pass
        else:
            raise AssertionError("provider drift must fail")

    counts = {"total": 0, "generation": 0}
    guarded = smoke._budgeted_requester(
        lambda *_args, **_kwargs: "ok",
        environ=_env(),
        counts=counts,
        maximum_requests=1,
    )
    try:
        guarded("POST", "http://wrong.test")
    except ValueError:
        pass
    else:
        raise AssertionError("wrong route must fail")
    assert guarded("POST", ENDPOINT) == "ok"
    try:
        guarded("POST", ENDPOINT)
    except ValueError:
        pass
    else:
        raise AssertionError("request budget must fail")

    monkeypatch.setattr(smoke, "ARTIFACT_PATH", tmp_path / "missing.json")
    issues = smoke._configuration_issues(
        {
            "NEX_MO_VLLM_BASE_URL": "http://provider.test:9116",
            "NEX_MO_VLLM_API_KEY": "key",
            "NEX_MO_VLLM_MODEL": "model",
        }
    )
    assert smoke.ARTIFACT_ENV in issues
    try:
        smoke._mapping([], "bad")
    except TypeError:
        pass
    else:
        raise AssertionError("non-mapping must fail")
    try:
        smoke._assert_redacted(
            {"leak": "secret-key"},
            _env(),
            cases=[],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("protected value must fail")
    assert "calls=None" in smoke.summary_line({"status": "PASS"})


def _env() -> dict[str, str]:
    return {
        SMOKE_ENV: "1",
        APPROVED_ENV: "1",
        OPERATOR_ENV: "operator-one",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": ENDPOINT,
        "NEX_MO_VLLM_API_KEY": "secret-key",
        "NEX_MO_VLLM_MODEL": "Qwen3.5-9B",
        "NEX_MO_VLLM_MODEL_REVISION": REVISION,
        "NEX_MO_VLLM_DEPLOYMENT_ID": "dgx-qwen3-5-9b-9116",
    }


def _artifact() -> dict:
    return {
        "artifact_content_persisted": False,
        "artifact_revision": REVISION,
        "metadata_file_count": 16,
        "metadata_manifest_digest": "sha256:" + "e" * 64,
        "metadata_target_count": 16,
        "model_path_persisted": False,
        "revision_source": "HUGGINGFACE_LOCAL_METADATA",
        "schema_version": "model_artifact_revision.v1",
        "status": "PASS",
        "weight_artifact_count": 4,
    }


def _fixtures() -> dict:
    request_profile = _load(
        "scripts/smoke/data/s136_answer_support_generation_profile_v1.json"
    )
    signal_design = _load(
        "scripts/smoke/data/s136_answer_support_signal_v1_design.json"
    )
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
        "request_profile_hash": validate_answer_support_request_profile(
            request_profile
        )["profile_hash"],
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
    shadow_design = _load(
        "scripts/smoke/data/s136_answer_support_shadow_runtime_v1_design.json"
    )
    shadow_design["source_binding"] = {
        "readiness_manifest_hash": manifest["manifest_hash"],
        "runtime_profile_hash": profile["profile_hash"],
        "request_profile_hash": profile["request_profile_hash"],
        "signal_design_hash": validate_answer_support_signal_design(signal_design)[
            "design_hash"
        ],
    }
    canary_design = _load(
        "scripts/smoke/data/s136_answer_support_shadow_canary_v1_design.json"
    )
    canary_design["source_binding"] = {
        "shadow_runtime_design_hash": semantic_sha256_hash_ref(shadow_design),
        "readiness_manifest_hash": manifest["manifest_hash"],
        "runtime_profile_hash": profile["profile_hash"],
        "request_profile_hash": profile["request_profile_hash"],
        "signal_design_hash": validate_answer_support_signal_design(signal_design)[
            "design_hash"
        ],
    }
    return {
        "readiness_report": {"manifest": manifest},
        "artifact_evidence": _artifact(),
        "cases_document": _load(
            "scripts/smoke/data/s136_answer_support_shadow_canary_v1_cases.json"
        ),
        "shadow_design": shadow_design,
        "canary_design": canary_design,
        "policy_document": _load(
            "scripts/smoke/data/s136_answer_support_shadow_canary_v1_policy.json"
        ),
        "signal_design": signal_design,
        "request_profile": request_profile,
    }


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))
