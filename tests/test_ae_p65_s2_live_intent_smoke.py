from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
from nex_ae_api.intent_candidate_generation import (
    IntentCandidateStageError,
    LiveIntentCandidateService,
)
from nex_ae_api.mo_generation_client import (
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.semantic_candidates import (
    SemanticCalibrationPolicy,
    SemanticCalibrationRegistry,
)
from nex_runtime.prompts import PromptRegistryStore
from nex_runtime.semantic_hashes import canonical_json


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke" / "run_p65_s2_live_intent_candidate_smoke.py"
SPEC = importlib.util.spec_from_file_location("p65_s2_live_intent_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class FakeClient:
    def check_required_mode_readiness(self, **kwargs):
        return AeMoGenerationReadiness(
            provider_mode="live",
            readiness_status="READY",
            model_profile="general-llm-default",
            model_ref="Qwen3.5-4B",
            deployment_id="vllm-generation-http",
            route_id="route-general-llm-default",
            checked_at="2026-10-16T11:00:00Z",
            expires_at="2026-10-16T11:00:30Z",
            cache_status="FRESH",
            source="active_preflight",
        )

    def generate_candidate(self, **kwargs):
        output = canonical_json(
            {
                "schema_version": "p65.intent_candidate.v1",
                "intent_label": "analyze_project_budget",
                "suggested_execution_mode": "GROUNDED_ANSWER",
                "entity_selectors": [],
                "parameter_candidates": [],
                "clarification": {
                    "required": False,
                    "reasons": [],
                    "questions": [],
                },
                "confidence": 0.91,
            }
        )
        return AeMoGenerationResult(
            mo_generation_id="mo-live",
            model_profile="general-llm-default",
            model_ref="Qwen3.5-4B",
            deployment_id="vllm-generation-http",
            provider_type="vllm-openai-compatible",
            output_text=output,
            provider_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            provider_output_size_bytes=len(output.encode()),
            finish_reason="STOP",
            input_tokens=50,
            output_tokens=40,
            total_tokens=90,
            request_id=kwargs["request_id"],
            trace_id=kwargs["trace_id"],
            route_id="route-general-llm-default",
            provider_request_id="provider-live",
            queue_ms=0,
            provider_ms=10,
            total_ms=10,
            created_at="2026-10-16T11:00:00Z",
            updated_at="2026-10-16T11:00:01Z",
        )


def _service() -> LiveIntentCandidateService:
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    policy = SemanticCalibrationPolicy(
        semantic_stage="INTENT",
        policy_ref="semantic-admission://intent/general-llm-default/p65.smoke.1",
        policy_version="p65.smoke.1",
        model_profile="general-llm-default",
        model_ref="Qwen3.5-4B",
        minimum_confidence=0.7,
        golden_evidence_ref="test://p65-s2/golden",
        adversarial_evidence_ref="test://p65-s2/adversarial",
    )
    return LiveIntentCandidateService(
        client=FakeClient(),
        prompt_store=store,
        calibration_registry=SemanticCalibrationRegistry((policy,)),
    )


def test_live_smoke_is_skipped_by_default() -> None:
    result = smoke.run_p65_s2_live_intent_candidate_smoke({})
    assert result["status"] == "SKIPPED"
    assert result["next_slice"] == "blocked"
    assert "NEX_AE_P65_S2_LIVE_SMOKE" in smoke.summary_line(result)


def test_live_smoke_passes_with_redacted_evidence() -> None:
    result = smoke.run_p65_s2_live_intent_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        service=_service(),
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert len(result["checks"]) == 10
    assert result["intent"]["model_ref"] == "Qwen3.5-4B"
    assert result["intent"]["candidate_confidence"] == 0.91
    assert result["intent"]["selected_threshold"] == 0.7
    assert "내가 접근" not in str(result)
    assert "p65_s2_live_intent_smoke=pass" in smoke.summary_line(result)


def test_live_smoke_maps_expected_and_unexpected_failures(monkeypatch) -> None:
    class FailedService:
        def generate_and_resolve(self, **kwargs):
            raise IntentCandidateStageError(422, "CANDIDATE_SCHEMA_INVALID", "safe")

    failed = smoke.run_p65_s2_live_intent_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        service=FailedService(),
    )
    assert failed["issues"][0]["error_code"] == "CANDIDATE_SCHEMA_INVALID"

    class BrokenService:
        def generate_and_resolve(self, **kwargs):
            raise RuntimeError("private")

    broken = smoke.run_p65_s2_live_intent_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        service=BrokenService(),
    )
    assert broken["issues"][0]["error_code"] == "UNEXPECTED_INTENT_FAILURE"

    monkeypatch.setattr(smoke, "_build_service", lambda env: (_ for _ in ()).throw(RuntimeError()))
    config = smoke.run_p65_s2_live_intent_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"}
    )
    assert config["issues"][0]["error_code"] == "UNEXPECTED_CONFIGURATION_FAILURE"


def test_live_smoke_writes_only_below_tmp(tmp_path: Path) -> None:
    evidence = smoke.run_p65_s2_live_intent_candidate_smoke({})
    target = tmp_path / "p65-s2.json"
    smoke.write_evidence(target, evidence)
    assert target.exists()

    with pytest.raises(ValueError):
        smoke.write_evidence(ROOT / "p65-s2.json", evidence)


def test_main_returns_success_for_default_skip(capsys) -> None:
    assert smoke.main(["--summary"]) == 0
    assert "p65_s2_live_intent_smoke=skipped" in capsys.readouterr().out
