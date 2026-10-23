#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-ae-api"))

from nex_ae_api.intent_candidate_generation import (  # noqa: E402
    IntentCalibrationRegistry,
    IntentCandidateStageError,
    LiveIntentCandidateService,
)
from nex_ae_api.mo_generation_client import (  # noqa: E402
    AeMoGenerationClientError,
    AeMoGenerationConfigurationError,
    build_default_ae_mo_generation_client,
)
from nex_ae_api.prompts import (  # noqa: E402
    AE_INTENT_RESOLUTION_BINDING,
    seed_ae_prompt_registry,
)
from nex_runtime.prompts import PromptRegistryStore  # noqa: E402

ACTIVATION_ENV = "NEX_AE_P65_S2_LIVE_SMOKE"
EVIDENCE_SCHEMA_VERSION = "ae_p65_s2_live_intent_evidence.v1"
GOLDEN_PROMPT = (
    "내가 접근할 수 있는 프로젝트 예산 자료를 확인해서 총 예산, "
    "집행액, 잔액을 한국어로 요약해줘."
)


def run_p65_s2_live_intent_candidate_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    service: LiveIntentCandidateService | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return _evidence(
            status="SKIPPED",
            stages={"activation": "SKIPPED"},
            checks={},
            intent=None,
            issues=[{"stage": "activation", "error_code": "live_smoke_not_enabled"}],
        )

    try:
        selected_service = service or _build_service(env)
    except (AeMoGenerationConfigurationError, IntentCandidateStageError) as exc:
        return _failure("configuration", exc.error_code)
    except Exception:
        return _failure("configuration", "UNEXPECTED_CONFIGURATION_FAILURE")

    execution_id = str(uuid4())
    work_intent_id = str(uuid4())
    trace_id = uuid4().hex
    request_id = f"p65-s2-live-{uuid4().hex}"
    received_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        result = selected_service.generate_and_resolve(
            user_prompt=GOLDEN_PROMPT,
            execution_id=execution_id,
            source_ref="p65-s2:golden-interaction",
            actor_ref="p65-s2:protected-smoke-subject",
            received_at=received_at,
            request_id=request_id,
            trace_id=trace_id,
            planning_mode="required",
            retrieval_enabled=True,
            authorized_resource_context_available=True,
            work_intent_id=work_intent_id,
        )
    except (AeMoGenerationClientError, IntentCandidateStageError) as exc:
        return _failure("intent_generation", exc.error_code)
    except Exception:
        return _failure("intent_generation", "UNEXPECTED_INTENT_FAILURE")

    decision = result.intent_decision or {}
    work_intent = result.work_intent or {}
    candidate = result.candidate
    checks = {
        "intent_candidate_schema_valid": (
            candidate.get("schema_version") == "p65.intent_candidate.v1"
        ),
        "deterministic_decision_observed": (
            decision.get("decision_source") == "LLM_CANDIDATE_VALIDATED"
        ),
        "work_intent_created_by_resolver": (
            work_intent.get("work_intent_id") == work_intent_id
            and work_intent.get("execution_id") == execution_id
        ),
        "candidate_has_no_work_intent_authority": (
            "tenant_id" not in candidate
            and "owner_subject_id" not in candidate
            and "project_ref" not in candidate
        ),
        "exact_prompt_binding_captured": (
            result.prompt_provenance.get("prompt_binding_key")
            == AE_INTENT_RESOLUTION_BINDING
            and result.prompt_provenance.get("prompt_template_version") == "v2"
        ),
        "model_specific_calibration_selected": (
            result.admission_policy_ref is not None
            and result.selected_threshold is not None
            and float(candidate.get("confidence", -1)) >= result.selected_threshold
        ),
        "bare_provider_digest_recorded": (
            len(result.provider_output_sha256) == 64
            and all(
                character in "0123456789abcdef"
                for character in result.provider_output_sha256
            )
        ),
        "candidate_hash_recorded": (
            result.candidate_hash.startswith("sha256:")
            and len(result.candidate_hash) == 71
        ),
        "required_mode_continues_only_after_admission": result.directive == "CONTINUE",
        "raw_candidate_suggestions_not_authoritative": (
            work_intent.get("entity_selectors") == []
            and work_intent.get("parameter_candidates") == []
        ),
    }
    passed = all(checks.values())
    return _evidence(
        status="PASS" if passed else "FAIL",
        stages={
            "activation": "PASS",
            "configuration": "PASS",
            "prompt_resolution": "PASS",
            "intent_generation": "PASS",
            "deterministic_admission": "PASS" if passed else "FAIL",
        },
        checks=checks,
        intent={
            "directive": result.directive,
            "candidate_schema_version": candidate.get("schema_version"),
            "candidate_hash": result.candidate_hash,
            "provider_output_sha256": result.provider_output_sha256,
            "candidate_confidence": candidate.get("confidence"),
            "selected_threshold": result.selected_threshold,
            "admission_policy_ref": result.admission_policy_ref,
            "prompt_binding_key": result.prompt_provenance.get("prompt_binding_key"),
            "prompt_template_version": result.prompt_provenance.get(
                "prompt_template_version"
            ),
            "model_profile": result.model_provenance.get("model_profile"),
            "model_ref": result.model_provenance.get("model_ref"),
            "deployment_id": result.model_provenance.get("deployment_id"),
            "execution_mode": decision.get("execution_mode"),
            "work_intent_hash": work_intent.get("intent_hash"),
        },
        issues=(
            []
            if passed
            else [{"stage": "assertions", "error_code": "LIVE_ASSERTION_FAILED"}]
        ),
    )


def _build_service(environ: Mapping[str, str]) -> LiveIntentCandidateService:
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    return LiveIntentCandidateService(
        client=build_default_ae_mo_generation_client(environ),
        prompt_store=store,
        calibration_registry=IntentCalibrationRegistry.from_environment(environ),
    )


def _failure(stage: str, error_code: str) -> dict[str, Any]:
    return _evidence(
        status="FAIL",
        stages={"activation": "PASS", stage: "FAIL"},
        checks={},
        intent=None,
        issues=[{"stage": stage, "error_code": error_code}],
    )


def _evidence(
    *,
    status: str,
    stages: dict[str, str],
    checks: dict[str, bool],
    intent: dict[str, Any] | None,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "phase": "P6.5",
        "slice": "P6.5-S2",
        "status": status,
        "stages": stages,
        "checks": checks,
        "intent": intent,
        "issues": issues,
        "redaction": {
            "status": "PASS",
            "excluded": [
                "provider_url",
                "provider_endpoint",
                "api_key",
                "service_token",
                "raw_prompt",
                "raw_provider_output",
                "raw_candidate",
                "hidden_reasoning",
                "tenant_id",
                "owner_subject_id",
            ],
        },
        "next_slice": "P6.5-S3" if status == "PASS" else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"p65_s2_live_intent_smoke=skipped reason={ACTIVATION_ENV}"
    intent = evidence.get("intent")
    model_ref = intent.get("model_ref") if isinstance(intent, dict) else None
    return (
        "p65_s2_live_intent_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"model_ref={model_ref or 'unavailable'} "
        f"checks={sum(bool(value) for value in evidence.get('checks', {}).values())} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def write_evidence(output_path: Path, evidence: Mapping[str, Any]) -> None:
    resolved = output_path.expanduser().resolve()
    if not resolved.is_relative_to(Path("/tmp").resolve()):
        raise ValueError("protected live evidence output must be below /tmp")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        f"{json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the protected P6.5-S2 live INTENT candidate smoke."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run_p65_s2_live_intent_candidate_smoke()
    if args.output:
        write_evidence(args.output, evidence)
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
