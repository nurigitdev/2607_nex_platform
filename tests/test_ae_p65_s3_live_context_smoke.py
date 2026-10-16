from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
from nex_ae_api.context_candidate_generation import (
    ContextCandidateStageError,
    LiveContextCandidateService,
)
from nex_ae_api.mo_generation_client import (
    AeMoGenerationConfigurationError,
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
SCRIPT = ROOT / "scripts" / "smoke" / "run_p65_s3_live_context_candidate_smoke.py"
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
        output = canonical_json(
            {
                "schema_version": "p65.context_candidate_set.v1",
                "entity_candidates": [
                    {
                        "candidate_key": "E1",
                        "entity_type": "DOCUMENT",
                        "selector_kind": "NAME",
                        "selector_value": "프로젝트 예산 현황",
                        "confidence": 0.91,
                    }
                ],
                "retrieval_hints": [
                    {
                        "query_terms": ["예산", "집행", "잔액"],
                        "resource_types": ["DOCUMENT"],
                        "confidence": 0.92,
                    }
                ],
                "resource_selectors": [],
                "parameter_candidates": [],
                "confidence": 0.91,
            }
        )
        return AeMoGenerationResult(
            mo_generation_id="mo-live-context",
            model_profile="general-llm-default",
            model_ref="Qwen3.5-4B",
            deployment_id="vllm-generation-http",
            provider_type="vllm-openai-compatible",
            output_text=output,
            provider_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            provider_output_size_bytes=len(output.encode()),
            finish_reason="STOP",
            input_tokens=80,
            output_tokens=70,
            total_tokens=150,
            request_id=kwargs["request_id"],
            trace_id=kwargs["trace_id"],
            route_id="route-general-llm-default",
            provider_request_id="provider-live-context",
            queue_ms=0,
            provider_ms=12,
            total_ms=12,
            created_at="2026-10-16T12:00:00Z",
            updated_at="2026-10-16T12:00:01Z",
        )


def _service() -> LiveContextCandidateService:
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    policy = SemanticCalibrationPolicy(
        semantic_stage="CONTEXT",
        policy_ref="semantic-admission://context/general-llm-default/p65.smoke.1",
        policy_version="p65.smoke.1",
        model_profile="general-llm-default",
        model_ref="Qwen3.5-4B",
        minimum_confidence=0.7,
        golden_evidence_ref="test://p65-s3/golden",
        adversarial_evidence_ref="test://p65-s3/adversarial",
    )
    return LiveContextCandidateService(
        client=FakeClient(),
        prompt_store=store,
        calibration_registry=SemanticCalibrationRegistry((policy,)),
    )


def test_live_smoke_is_skipped_by_default() -> None:
    result = smoke.run_p65_s3_live_context_candidate_smoke({})
    assert result["status"] == "SKIPPED"
    assert result["next_slice"] == "blocked"
    assert smoke.ACTIVATION_ENV in smoke.summary_line(result)


def test_live_smoke_passes_with_redacted_evidence() -> None:
    result = smoke.run_p65_s3_live_context_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        service=_service(),
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert len(result["checks"]) == 11
    assert result["context"]["model_ref"] == "Qwen3.5-4B"
    assert result["context"]["candidate_confidence"] == 0.91
    assert result["context"]["selected_threshold"] == 0.7
    assert "내가 접근" not in str(result)
    assert "p65_s3_live_context_smoke=pass" in smoke.summary_line(result)


def test_live_smoke_maps_expected_and_unexpected_failures(monkeypatch) -> None:
    class FailedService:
        def generate_and_resolve(self, **kwargs):
            raise ContextCandidateStageError(422, "CANDIDATE_SCHEMA_INVALID", "safe")

    failed = smoke.run_p65_s3_live_context_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        service=FailedService(),
    )
    assert failed["issues"][0]["error_code"] == "CANDIDATE_SCHEMA_INVALID"

    class BrokenService:
        def generate_and_resolve(self, **kwargs):
            raise RuntimeError("private")

    broken = smoke.run_p65_s3_live_context_candidate_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        service=BrokenService(),
    )
    assert broken["issues"][0]["error_code"] == "UNEXPECTED_CONTEXT_FAILURE"

    monkeypatch.setattr(
        smoke,
        "_build_service",
        lambda env: (_ for _ in ()).throw(RuntimeError()),
    )
    config = smoke.run_p65_s3_live_context_candidate_smoke(
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
    expected = smoke.run_p65_s3_live_context_candidate_smoke(
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
        smoke.ContextCalibrationRegistry,
        "from_environment",
        lambda environ: calibration,
    )

    service = smoke._build_service({"PROFILE": "test"})

    assert service.client is client
    assert service.calibration_registry is calibration


def test_live_smoke_writes_only_below_tmp(tmp_path: Path) -> None:
    evidence = smoke.run_p65_s3_live_context_candidate_smoke({})
    target = tmp_path / "p65-s3.json"
    smoke.write_evidence(target, evidence)
    assert target.exists()

    with pytest.raises(ValueError):
        smoke.write_evidence(ROOT / "p65-s3.json", evidence)


def test_main_returns_success_for_default_skip(capsys) -> None:
    assert smoke.main(["--summary"]) == 0
    assert "p65_s3_live_context_smoke=skipped" in capsys.readouterr().out


def test_main_writes_default_skip_evidence(tmp_path: Path, capsys) -> None:
    output = tmp_path / "main-evidence.json"

    assert smoke.main(["--output", str(output)]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out
    assert output.exists()
