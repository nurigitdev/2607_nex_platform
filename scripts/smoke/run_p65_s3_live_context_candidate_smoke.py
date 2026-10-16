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

from nex_ae_api.agent_context import (  # noqa: E402
    ContextBuildRequest,
    TrustedContextResolution,
    runtime_policy_ref_from_compatibility_policy,
)
from nex_ae_api.context_candidate_generation import (  # noqa: E402
    ContextCalibrationRegistry,
    ContextCandidateStageError,
    LiveContextCandidateService,
)
from nex_ae_api.intent_policy import resolve_intent_decision  # noqa: E402
from nex_ae_api.mo_generation_client import (  # noqa: E402
    AeMoGenerationClientError,
    AeMoGenerationConfigurationError,
    build_default_ae_mo_generation_client,
)
from nex_ae_api.prompts import (  # noqa: E402
    AE_CONTEXT_CANDIDATE_BINDING,
    seed_ae_prompt_registry,
)
from nex_ae_api.runtime_policy import resolve_runtime_policy  # noqa: E402
from nex_ae_api.work_intent import build_work_intent_from_decision  # noqa: E402
from nex_runtime.prompts import PromptRegistryStore  # noqa: E402
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref  # noqa: E402


ACTIVATION_ENV = "NEX_AE_P65_S3_LIVE_SMOKE"
EVIDENCE_SCHEMA_VERSION = "ae_p65_s3_live_context_evidence.v1"
GOLDEN_PROMPT = (
    "내가 접근할 수 있는 프로젝트 예산 현황 문서에서 총 예산, 집행액, "
    "잔액을 찾을 수 있도록 필요한 context 후보를 만들어줘."
)


class SmokeTrustedResolver:
    def __init__(self, *, interaction_id: str, built_at: str) -> None:
        self.interaction_id = interaction_id
        self.built_at = built_at
        self.request: ContextBuildRequest | None = None

    def resolve(self, request: ContextBuildRequest) -> TrustedContextResolution:
        self.request = request
        return TrustedContextResolution(
            project_ref=None,
            authority_ref="OA:EAC:p65-s3-live-smoke",
            resolved_entities=(),
            retrieval_refs=(),
            evidence_refs=(),
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "INTERACTION_REF",
                    "source_ref": f"AE:INTERACTION:{self.interaction_id}",
                    "source_version": "1",
                    "content_hash": semantic_sha256_hash_ref(
                        {"interaction_id": self.interaction_id}
                    ),
                    "as_of": self.built_at,
                },
            ),
            budget_tokens=4096,
            estimated_used_tokens=128,
        )


def run_p65_s3_live_context_candidate_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    service: LiveContextCandidateService | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return _evidence(
            status="SKIPPED",
            stages={"activation": "SKIPPED"},
            checks={},
            context=None,
            issues=[{"stage": "activation", "error_code": "live_smoke_not_enabled"}],
        )
    try:
        selected_service = service or _build_service(env)
    except (AeMoGenerationConfigurationError, ContextCandidateStageError) as exc:
        return _failure("configuration", exc.error_code)
    except Exception:
        return _failure("configuration", "UNEXPECTED_CONFIGURATION_FAILURE")

    execution_id = str(uuid4())
    work_intent_id = str(uuid4())
    context_id = str(uuid4())
    agent_id = str(uuid4())
    workspace_id = str(uuid4())
    conversation_id = str(uuid4())
    interaction_id = str(uuid4())
    trace_id = uuid4().hex
    request_id = f"p65-s3-live-{uuid4().hex}"
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    work_intent = _work_intent(
        execution_id=execution_id,
        work_intent_id=work_intent_id,
        interaction_id=interaction_id,
        received_at=now,
    )
    runtime_policy = resolve_runtime_policy({"user_message": GOLDEN_PROMPT})
    resolver = SmokeTrustedResolver(interaction_id=interaction_id, built_at=now)
    try:
        result = selected_service.generate_and_resolve(
            work_intent=work_intent,
            base_context={
                "interaction_text": GOLDEN_PROMPT,
                "conversation_summary": None,
                "resource_label_hints": ["프로젝트 예산 현황"],
            },
            tenant_id="p65-s3-protected-smoke",
            principal_id="p65-s3-protected-subject",
            agent_id=agent_id,
            execution_id=execution_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            interaction_id=interaction_id,
            runtime_policy_ref=runtime_policy_ref_from_compatibility_policy(
                runtime_policy
            ),
            resolver=resolver,
            request_id=request_id,
            trace_id=trace_id,
            planning_mode="required",
            context_id=context_id,
            built_at=now,
        )
    except (AeMoGenerationClientError, ContextCandidateStageError) as exc:
        return _failure("context_generation", exc.error_code)
    except Exception:
        return _failure("context_generation", "UNEXPECTED_CONTEXT_FAILURE")

    candidate = result.candidate
    context = result.agent_context or {}
    hints = resolver.request.candidate_hints if resolver.request is not None else None
    checks = {
        "context_candidate_schema_valid": (
            candidate.get("schema_version") == "p65.context_candidate_set.v1"
        ),
        "bounded_hints_reached_trusted_resolver": (
            hints is not None and hints.candidate_hash == result.candidate_hash
        ),
        "agent_context_created_by_trusted_resolver": (
            context.get("context_id") == context_id
            and context.get("execution_id") == execution_id
        ),
        "candidate_has_no_context_authority": (
            "tenant_id" not in candidate
            and "principal_id" not in candidate
            and "project_ref" not in candidate
        ),
        "trusted_scope_preserved": (
            context.get("identity", {}).get("tenant_id")
            == "p65-s3-protected-smoke"
            and context.get("identity", {}).get("principal_id")
            == "p65-s3-protected-subject"
            and context.get("project_ref") is None
        ),
        "exact_prompt_binding_captured": (
            result.prompt_provenance.get("prompt_binding_key")
            == AE_CONTEXT_CANDIDATE_BINDING
            and result.prompt_provenance.get("prompt_template_version") == "v1"
        ),
        "model_specific_calibration_selected": (
            result.admission_policy_ref is not None
            and result.selected_threshold is not None
            and float(candidate.get("confidence", -1))
            >= result.selected_threshold
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
        "required_mode_continues_only_after_resolution": result.directive == "CONTINUE",
        "candidate_payload_not_copied_to_agent_context": (
            "candidate_hints" not in context and "candidate_hash" not in context
        ),
    }
    passed = all(checks.values())
    return _evidence(
        status="PASS" if passed else "FAIL",
        stages={
            "activation": "PASS",
            "configuration": "PASS",
            "prompt_resolution": "PASS",
            "context_generation": "PASS",
            "trusted_resolution": "PASS" if passed else "FAIL",
        },
        checks=checks,
        context={
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
            "agent_context_hash": context.get("context_hash"),
        },
        issues=[]
        if passed
        else [{"stage": "assertions", "error_code": "LIVE_ASSERTION_FAILED"}],
    )


def _build_service(environ: Mapping[str, str]) -> LiveContextCandidateService:
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    return LiveContextCandidateService(
        client=build_default_ae_mo_generation_client(environ),
        prompt_store=store,
        calibration_registry=ContextCalibrationRegistry.from_environment(environ),
    )


def _work_intent(
    *,
    execution_id: str,
    work_intent_id: str,
    interaction_id: str,
    received_at: str,
) -> dict[str, Any]:
    decision = resolve_intent_decision(
        {
            "user_message": GOLDEN_PROMPT,
            "generation": {"execution_mode": "GROUNDED_ANSWER"},
        }
    )
    return build_work_intent_from_decision(
        execution_id=execution_id,
        source_ref=f"AE:INTERACTION:{interaction_id}",
        actor_ref="OA:SUBJECT:p65-s3-protected-subject",
        received_at=received_at,
        intent_decision=decision,
        input_context_hash=semantic_sha256_hash_ref(
            {"interaction_id": interaction_id, "phase": "P6.5-S3"}
        ),
        work_intent_id=work_intent_id,
    )


def _failure(stage: str, error_code: str) -> dict[str, Any]:
    return _evidence(
        status="FAIL",
        stages={"activation": "PASS", stage: "FAIL"},
        checks={},
        context=None,
        issues=[{"stage": stage, "error_code": error_code}],
    )


def _evidence(
    *,
    status: str,
    stages: dict[str, str],
    checks: dict[str, bool],
    context: dict[str, Any] | None,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "phase": "P6.5",
        "slice": "P6.5-S3",
        "status": status,
        "stages": stages,
        "checks": checks,
        "context": context,
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
        "next_slice": "P6.5-S4" if status == "PASS" else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"p65_s3_live_context_smoke=skipped reason={ACTIVATION_ENV}"
    context = evidence.get("context")
    model_ref = context.get("model_ref") if isinstance(context, dict) else None
    return (
        "p65_s3_live_context_smoke="
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
        description="Run the protected P6.5-S3 live CONTEXT candidate smoke."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run_p65_s3_live_context_candidate_smoke()
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
