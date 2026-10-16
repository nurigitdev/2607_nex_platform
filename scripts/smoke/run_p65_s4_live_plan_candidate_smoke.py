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
    build_agent_context,
    runtime_policy_ref_from_compatibility_policy,
)
from nex_ae_api.intent_policy import resolve_intent_decision  # noqa: E402
from nex_ae_api.mo_generation_client import (  # noqa: E402
    AeMoGenerationClientError,
    AeMoGenerationConfigurationError,
    build_default_ae_mo_generation_client,
)
from nex_ae_api.plan_candidate_generation import (  # noqa: E402
    LivePlanCandidateService,
    PlanCalibrationRegistry,
    PlanCandidateStageError,
)
from nex_ae_api.planning_capabilities import (  # noqa: E402
    build_capability_snapshot,
)
from nex_ae_api.prompts import (  # noqa: E402
    AE_PLAN_BUILDER_BINDING,
    seed_ae_prompt_registry,
)
from nex_ae_api.runtime_policy import resolve_runtime_policy  # noqa: E402
from nex_ae_api.work_intent import build_work_intent_from_decision  # noqa: E402
from nex_runtime.prompts import PromptRegistryStore  # noqa: E402
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref  # noqa: E402


ACTIVATION_ENV = "NEX_AE_P65_S4_LIVE_SMOKE"
EVIDENCE_SCHEMA_VERSION = "ae_p65_s4_live_plan_evidence.v1"
GOLDEN_PROMPT = (
    "내가 접근할 수 있는 프로젝트 예산 현황 문서를 근거로 총 예산, "
    "집행액, 잔액을 답변하는 실행 계획을 만들어줘."
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
            authority_ref="OA:EAC:p65-s4-live-smoke",
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


def run_p65_s4_live_plan_candidate_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    service: LivePlanCandidateService | None = None,
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
    except (AeMoGenerationConfigurationError, PlanCandidateStageError) as exc:
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
    snapshot_id = str(uuid4())
    agent_plan_id = str(uuid4())
    trace_id = uuid4().hex
    request_id = f"p65-s4-live-{uuid4().hex}"
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    work_intent = _work_intent(
        execution_id=execution_id,
        work_intent_id=work_intent_id,
        interaction_id=interaction_id,
        received_at=now,
    )
    runtime_policy = resolve_runtime_policy({"user_message": GOLDEN_PROMPT})
    resolver = SmokeTrustedResolver(interaction_id=interaction_id, built_at=now)
    agent_context = build_agent_context(
        tenant_id="p65-s4-protected-smoke",
        principal_id="p65-s4-protected-subject",
        agent_id=agent_id,
        execution_id=execution_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        interaction_id=interaction_id,
        work_intent=work_intent,
        runtime_policy_ref=runtime_policy_ref_from_compatibility_policy(
            runtime_policy
        ),
        resolver=resolver,
        context_id=context_id,
        built_at=now,
    )
    capability_snapshot = build_capability_snapshot(
        tenant_id="p65-s4-protected-smoke",
        capability_snapshot_id=snapshot_id,
        snapshot_version=1,
        created_at=now,
    )
    try:
        result = selected_service.generate_and_bind(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            request_id=request_id,
            trace_id=trace_id,
            planning_mode="required",
            agent_plan_id=agent_plan_id,
        )
    except (AeMoGenerationClientError, PlanCandidateStageError) as exc:
        return _failure("plan_generation", exc.error_code)
    except Exception:
        return _failure("plan_generation", "UNEXPECTED_PLAN_FAILURE")

    candidate = result.candidate
    plan = result.agent_plan or {}
    local_steps = [
        step for step in plan.get("steps", [])
        if step.get("step_type") == "LOCAL_CAPABILITY"
    ]
    expected_hash = semantic_sha256_hash_ref(
        {key: value for key, value in plan.items() if key != "plan_hash"}
    )
    checks = {
        "plan_candidate_schema_valid": (
            candidate.get("schema_version") == "p65.plan_candidate.v1"
        ),
        "candidate_vocabulary_is_closed": all(
            step.get("step_type") in {"LOCAL_CAPABILITY", "REPORT"}
            for step in candidate.get("logical_steps", [])
        ),
        "agent_plan_created_by_trusted_binder": (
            plan.get("agent_plan_id") == agent_plan_id
            and plan.get("execution_id") == execution_id
        ),
        "exact_capability_versions_bound_by_ae": (
            bool(local_steps)
            and all(
                step.get("required_capability")
                and step.get("capability_version_constraint")
                for step in local_steps
            )
        ),
        "candidate_has_no_execution_authority": all(
            field not in candidate
            for field in (
                "tenant_id",
                "principal_id",
                "executor_kind",
                "capability_version",
                "approval",
            )
        ),
        "exact_source_lineage_preserved": (
            plan.get("work_intent_ref", {}).get("hash")
            == work_intent.get("intent_hash")
            and plan.get("agent_context_ref", {}).get("hash")
            == agent_context.get("context_hash")
            and plan.get("capability_snapshot_ref", {}).get("hash")
            == capability_snapshot.get("snapshot_hash")
        ),
        "exact_prompt_binding_captured": (
            result.prompt_provenance.get("prompt_binding_key")
            == AE_PLAN_BUILDER_BINDING
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
        "candidate_hash_recorded_in_plan_provenance": (
            result.candidate_hash.startswith("sha256:")
            and plan.get("planner_provenance", {}).get("route_decision_ref")
            == f"semantic-candidate://plan/{result.candidate_hash}"
        ),
        "canonical_agent_plan_hash_valid": plan.get("plan_hash") == expected_hash,
        "required_mode_continues_only_after_binding": result.directive == "CONTINUE",
        "candidate_payload_not_copied_to_agent_plan": (
            "logical_steps" not in plan and "confidence" not in plan
        ),
    }
    passed = all(checks.values())
    return _evidence(
        status="PASS" if passed else "FAIL",
        stages={
            "activation": "PASS",
            "configuration": "PASS",
            "prompt_resolution": "PASS",
            "plan_generation": "PASS",
            "trusted_binding": "PASS" if passed else "FAIL",
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
            "plan_kind": plan.get("plan_kind"),
            "step_count": len(plan.get("steps", [])),
            "agent_plan_hash": plan.get("plan_hash"),
        },
        issues=[]
        if passed
        else [{"stage": "assertions", "error_code": "LIVE_ASSERTION_FAILED"}],
    )


def _build_service(environ: Mapping[str, str]) -> LivePlanCandidateService:
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    return LivePlanCandidateService(
        client=build_default_ae_mo_generation_client(environ),
        prompt_store=store,
        calibration_registry=PlanCalibrationRegistry.from_environment(environ),
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
        actor_ref="OA:SUBJECT:p65-s4-protected-subject",
        received_at=received_at,
        intent_decision=decision,
        input_context_hash=semantic_sha256_hash_ref(
            {"interaction_id": interaction_id, "phase": "P6.5-S4"}
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
        "slice": "P6.5-S4",
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
        "next_slice": "P6.5-S5" if status == "PASS" else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"p65_s4_live_plan_smoke=skipped reason={ACTIVATION_ENV}"
    context = evidence.get("context")
    model_ref = context.get("model_ref") if isinstance(context, dict) else None
    return (
        "p65_s4_live_plan_smoke="
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
        description="Run the protected P6.5-S4 live PLAN candidate smoke."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run_p65_s4_live_plan_candidate_smoke()
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
