from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
from nex_ae_api.mo_generation_client import (
    AeMoGenerationConfigurationError,
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
from nex_ae_api.plan_candidate_generation import (
    LivePlanCandidateService,
    PlanCalibrationRegistry,
    PlanCandidateStageError,
)
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.semantic_candidates import SemanticCalibrationPolicy
from nex_runtime.prompts import PromptRegistryStore
from nex_runtime.semantic_hashes import canonical_json


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke" / "run_p65_s4_live_plan_candidate_smoke.py"
SPEC = importlib.util.spec_from_file_location(SCRIPT.stem, SCRIPT)
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
            checked_at="2026-10-16T12:00:00Z",
            expires_at="2026-10-16T12:00:30Z",
            cache_status="FRESH",
            source="active_preflight",
        )

    def generate_candidate(self, **kwargs):
        generation_input = __import__("json").loads(kwargs["messages"][1]["content"])
        output = canonical_json(
            {
                "schema_version": "p65.plan_candidate.v1",
                "suggested_plan_kind": "KNOWN_TEMPLATE",
                "goal": generation_input["work_intent"]["goal"],
                "logical_steps": [
                    {
                        "step_id": "S1",
                        "step_type": "LOCAL_CAPABILITY",
                        "title": "Run grounded compatibility chat",
                        "objective": "Answer using authorized context.",
                        "depends_on": [],
                        "capability_hint": "AE.CHAT.COMPATIBILITY",
                        "completion_criteria": ["A grounded answer is available."],
                    },
                    {
                        "step_id": "S2",
                        "step_type": "REPORT",
                        "title": "Project response",
                        "objective": "Return the verified response.",
                        "depends_on": ["S1"],
                        "capability_hint": None,
                        "completion_criteria": ["The response is available."],
                    },
                ],
                "completion_mapping": [
                    {"criterion_id": "C1", "terminal_step_refs": ["S2"]}
                ],
                "confidence": 0.91,
            }
        )
        return AeMoGenerationResult(
            mo_generation_id="mo-live-plan",
            model_profile="general-llm-default",
            model_ref="Qwen3.5-4B",
            deployment_id="vllm-generation-http",
            provider_type="vllm-openai-compatible",
            output_text=output,
            provider_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            provider_output_size_bytes=len(output.encode()),
            finish_reason="STOP",
            input_tokens=100,
            output_tokens=100,
            total_tokens=200,
            request_id=kwargs["request_id"],
            trace_id=kwargs["trace_id"],
            route_id="route-general-llm-default",
            provider_request_id="provider-live-plan",
            queue_ms=0,
            provider_ms=12,
            total_ms=12,
            created_at="2026-10-16T12:00:00Z",
            updated_at="2026-10-16T12:00:01Z",
        )


def _service() -> LivePlanCandidateService:
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    policy = SemanticCalibrationPolicy(
        semantic_stage="PLAN",
        policy_ref="semantic-admission://plan/general-llm-default/p65.smoke.1",
        policy_version="p65.smoke.1",
        model_profile="general-llm-default",
        model_ref="Qwen3.5-4B",
        minimum_confidence=0.7,
        golden_evidence_ref="test://p65-s4/golden",
        adversarial_evidence_ref="test://p65-s4/adversarial",
    )
    return LivePlanCandidateService(
        client=FakeClient(),
        prompt_store=store,
        calibration_registry=PlanCalibrationRegistry((policy,)),
    )


def test_live_smoke_is_skipped_by_default() -> None:
    result = smoke.run_p65_s4_live_plan_candidate_smoke({})
    assert result["status"] == "SKIPPED"
    assert result["next_slice"] == "blocked"
    assert smoke.ACTIVATION_ENV in smoke.summary_line(result)


def test_live_smoke_passes_with_redacted_evidence() -> None:
    result = smoke.run_p65_s4_live_plan_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        service=_service(),
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert len(result["checks"]) == 13
    assert result["context"]["model_ref"] == "Qwen3.5-4B"
    assert result["context"]["candidate_confidence"] == 0.91
    assert result["context"]["selected_threshold"] == 0.7
    assert "내가 접근" not in str(result)
    assert "p65_s4_live_plan_smoke=pass" in smoke.summary_line(result)


def test_live_smoke_maps_expected_and_unexpected_failures(monkeypatch) -> None:
    class FailedService:
        def generate_and_bind(self, **kwargs):
            raise PlanCandidateStageError(422, "CANDIDATE_SCHEMA_INVALID", "safe")

    failed = smoke.run_p65_s4_live_plan_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"}, service=FailedService()
    )
    assert failed["issues"][0]["error_code"] == "CANDIDATE_SCHEMA_INVALID"

    class BrokenService:
        def generate_and_bind(self, **kwargs):
            raise RuntimeError("private")

    broken = smoke.run_p65_s4_live_plan_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"}, service=BrokenService()
    )
    assert broken["issues"][0]["error_code"] == "UNEXPECTED_PLAN_FAILURE"

    monkeypatch.setattr(
        smoke,
        "_build_service",
        lambda env: (_ for _ in ()).throw(RuntimeError()),
    )
    config = smoke.run_p65_s4_live_plan_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"}
    )
    assert config["issues"][0]["error_code"] == "UNEXPECTED_CONFIGURATION_FAILURE"

    monkeypatch.setattr(
        smoke,
        "_build_service",
        lambda env: (_ for _ in ()).throw(
            AeMoGenerationConfigurationError("CONFIG_INVALID", "private")
        ),
    )
    expected = smoke.run_p65_s4_live_plan_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"}
    )
    assert expected["issues"][0]["error_code"] == "CONFIG_INVALID"
    assert "private" not in str(expected)


def test_build_service_uses_default_client_and_environment_calibration(
    monkeypatch,
) -> None:
    client = FakeClient()
    calibration = object()
    monkeypatch.setattr(
        smoke,
        "build_default_ae_mo_generation_client",
        lambda environ: client,
    )
    monkeypatch.setattr(
        smoke.PlanCalibrationRegistry,
        "from_environment",
        lambda environ: calibration,
    )

    service = smoke._build_service({"PROFILE": "test"})

    assert service.client is client
    assert service.calibration_registry is calibration


def test_live_smoke_writes_only_below_tmp(tmp_path: Path) -> None:
    evidence = smoke.run_p65_s4_live_plan_candidate_smoke({})
    target = tmp_path / "p65-s4.json"
    smoke.write_evidence(target, evidence)
    assert target.exists()

    with pytest.raises(ValueError):
        smoke.write_evidence(ROOT / "p65-s4.json", evidence)


def test_main_returns_success_for_default_skip(capsys) -> None:
    assert smoke.main(["--summary"]) == 0
    assert "p65_s4_live_plan_smoke=skipped" in capsys.readouterr().out


def test_main_writes_default_skip_evidence(tmp_path: Path, capsys) -> None:
    output = tmp_path / "main-evidence.json"

    assert smoke.main(["--output", str(output)]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out
    assert output.exists()
