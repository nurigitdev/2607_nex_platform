#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = Path(
    "reports/quality/"
    "mybee-w70-cp-m1-e2e-fx-01b6b1-product-coordinator-storage-fit.json"
)
SCHEMA_VERSION = "mybee_cp_m1_e2e_fx_01b6b1_storage_fit_audit.v1"

COORDINATOR_CONTRACT = (
    "services/nex-ae-api/nex_ae_api/product_planning_coordinators.py"
)
M1_REGISTRATION = (
    "services/nex-ae-api/nex_ae_api/m1_product_planning_coordinator.py"
)
BACKGROUND_PLANNING = "services/nex-ae-api/nex_ae_api/background_planning.py"
M1_MATERIALIZER = "services/nex-ae-api/nex_ae_api/m1_plan_materialization.py"
WAIT_FOUNDATION = "database/nex-ae-api/migrations/2402_ae_wait_registration.sql"
WAIT_TYPES = (
    "database/nex-ae-api/migrations/2502_ae_wait_registration_generalization.sql"
)
WAIT_NSL_BINDING = (
    "database/nex-ae-api/migrations/2503_ae_nsl_approval_wait_binding.sql"
)
EVENT_FOUNDATION = "database/nex-ae-api/migrations/2404_ae_work_result_resume.sql"
EVENT_TYPES = "database/nex-ae-api/migrations/2505_ae_nsl_approval_event_inbox.sql"
AGENT_PLAN = (
    "database/nex-ae-api/migrations/2103_ae_capability_plan_validation.sql"
)
EXECUTABLE_PLAN = "database/nex-ae-api/migrations/2104_ae_executable_plan.sql"
STEP_RESULT = "database/nex-ae-api/migrations/2106_ae_step_result.sql"
RUNTIME_JOB = "database/nex-ae-api/migrations/2004_ae_runtime_job.sql"

_FORBIDDEN_PRODUCT_PATTERNS = (
    "vo00",
    "1350.20",
    "10000",
    r"golden[_-]a",
    "fixture",
    "demo_runtime",
)


def audit_storage_fit(root: Path = ROOT) -> dict[str, Any]:
    issues: list[str] = []
    paths = (
        COORDINATOR_CONTRACT,
        M1_REGISTRATION,
        BACKGROUND_PLANNING,
        M1_MATERIALIZER,
        WAIT_FOUNDATION,
        WAIT_TYPES,
        WAIT_NSL_BINDING,
        EVENT_FOUNDATION,
        EVENT_TYPES,
        AGENT_PLAN,
        EXECUTABLE_PLAN,
        STEP_RESULT,
        RUNTIME_JOB,
    )
    texts = {path: _read(root, path, issues) for path in paths}
    compact = {path: _compact(value) for path, value in texts.items()}

    coordinator_contract_present = all(
        token in texts[COORDINATOR_CONTRACT]
        for token in (
            "class ProductPlanningCoordinator(Protocol)",
            "class ProductPlanningCoordinatorRegistry",
            "capability_registration_hash",
            'PRODUCT_COORDINATOR_ACTIVATION_STATUSES = frozenset(',
        )
    )
    m1_registration_present = all(
        token in texts[M1_REGISTRATION]
        for token in (
            "build_m1_product_planning_coordinator_registration",
            'activation_status="CONTRACT_ONLY"',
            '"WAITING_BUSINESS_APPROVAL"',
            '"WAITING_ACCOUNTING_APPROVAL"',
            'ready_state="READY_FOR_D04"',
        )
    )
    product_value_residue = sorted(
        pattern
        for pattern in _FORBIDDEN_PRODUCT_PATTERNS
        if re.search(
            pattern,
            (texts[COORDINATOR_CONTRACT] + texts[M1_REGISTRATION]).lower(),
        )
    )
    generic_contract_clean = not product_value_residue

    wait_requires_executable_step = all(
        token in compact[WAIT_FOUNDATION]
        for token in (
            "executable_step_id text not null",
            "references ae_executable_step",
        )
    )
    wait_types_are_narrow = (
        "wait_type in ('work_result', 'nsl_approval')" in compact[WAIT_TYPES]
        and "business_formal" not in compact[WAIT_TYPES]
        and "accounting_approval" not in compact[WAIT_TYPES]
    )
    nsl_wait_is_strictly_bound = all(
        token in compact[WAIT_NSL_BINDING]
        for token in (
            "wait_type = 'nsl_approval'",
            "approval_request_id is not null",
            "references ae_nsl_approval_request",
        )
    )
    event_types_are_narrow = (
        "event_type in ('work_result_submitted', 'nsl_approval_decided')"
        in compact[EVENT_TYPES]
        and "business_formal_approval_decided" not in compact[EVENT_TYPES]
        and "accounting_approval_decided" not in compact[EVENT_TYPES]
    )
    event_shape_is_domain_specific = all(
        token in compact[EVENT_TYPES]
        for token in (
            "event_type = 'work_result_submitted'",
            "event_type = 'nsl_approval_decided'",
            "approval_request_id is not null",
        )
    )
    step_result_requires_executable_plan = all(
        token in compact[STEP_RESULT]
        for token in (
            "executable_plan_id uuid not null",
            "executable_step_id text not null",
            "references ae_executable_plan",
            "references ae_executable_step",
        )
    )
    runtime_job_is_not_checkpoint_store = all(
        token in compact[RUNTIME_JOB]
        for token in (
            "job_type text not null",
            "'start_execution', 'continue_execution'",
            "payload_json jsonb not null",
        )
    ) and not any(
        token in compact[RUNTIME_JOB]
        for token in (
            "checkpoint_hash",
            "checkpoint_version",
            "coordinator_id",
        )
    )
    plan_versioning_available = all(
        token in compact[AGENT_PLAN]
        for token in (
            "agent_plan_version integer not null",
            "unique (tenant_id, agent_execution_id, agent_plan_version)",
        )
    ) and all(
        token in compact[EXECUTABLE_PLAN]
        for token in (
            "executable_plan_version integer not null",
            "unique (tenant_id, agent_execution_id, executable_plan_version)",
        )
    )
    materializer_is_version_one = '"agent_plan_version": 1' in texts[
        M1_MATERIALIZER
    ]
    background_compiles_provider_plan_directly = (
        "self.semantic_admission.admit_and_compile(" in texts[BACKGROUND_PLANNING]
    )

    checks = {
        "coordinator_contract_present": coordinator_contract_present,
        "m1_contract_only_registration_present": m1_registration_present,
        "generic_contract_has_no_fixture_business_values": generic_contract_clean,
        "wait_requires_existing_executable_step": wait_requires_executable_step,
        "wait_types_are_work_result_or_nsl_only": wait_types_are_narrow,
        "nsl_wait_has_strict_nsl_lineage": nsl_wait_is_strictly_bound,
        "event_types_are_work_result_or_nsl_only": event_types_are_narrow,
        "event_shape_is_domain_specific": event_shape_is_domain_specific,
        "step_result_requires_existing_executable_plan": (
            step_result_requires_executable_plan
        ),
        "runtime_job_is_not_typed_checkpoint_storage": (
            runtime_job_is_not_checkpoint_store
        ),
        "plan_versioning_exists": plan_versioning_available,
        "m1_materializer_currently_emits_version_one": materializer_is_version_one,
        "background_planning_currently_compiles_provider_plan": (
            background_compiles_provider_plan_directly
        ),
    }
    if not coordinator_contract_present:
        issues.append("generic product planning coordinator contract is unavailable")
    if not m1_registration_present:
        issues.append("M1 coordinator contract registration is unavailable")
    if product_value_residue:
        issues.append("product coordinator contract contains fixture business values")
    for name in (
        "wait_requires_existing_executable_step",
        "wait_types_are_work_result_or_nsl_only",
        "nsl_wait_has_strict_nsl_lineage",
        "event_types_are_work_result_or_nsl_only",
        "event_shape_is_domain_specific",
        "step_result_requires_existing_executable_plan",
        "runtime_job_is_not_typed_checkpoint_storage",
        "plan_versioning_exists",
        "m1_materializer_currently_emits_version_one",
        "background_planning_currently_compiles_provider_plan",
    ):
        if not checks[name]:
            issues.append(f"source-backed storage invariant changed: {name}")

    durable_storage_fit = {
        "work_intent_and_agent_context": {
            "fit": True,
            "decision": "REUSE_IMMUTABLE_LINEAGE",
        },
        "provider_semantic_evidence": {
            "fit": True,
            "decision": "RETAIN_AS_NON_AUTHORITATIVE_EVIDENCE",
        },
        "agent_plan_and_executable_plan": {
            "fit": True,
            "conditional": True,
            "decision": (
                "FINAL_DETERMINISTIC_PLAN_MUST_BE_FIRST_EXECUTABLE_PLAN_"
                "UNTIL_VERSION_POLICY_IS_EXPLICIT"
            ),
        },
        "wait_registration": {
            "fit": False,
            "reason": (
                "requires an existing executable step and admits only "
                "WORK_RESULT or NSL_APPROVAL"
            ),
        },
        "external_event_inbox": {
            "fit": False,
            "reason": (
                "admits only WORK_RESULT_SUBMITTED or NSL_APPROVAL_DECIDED "
                "with domain-specific shape constraints"
            ),
        },
        "step_result": {
            "fit": False,
            "reason": "requires an existing ExecutablePlan and ExecutableStep",
        },
        "runtime_job_payload": {
            "fit": False,
            "reason": (
                "is mutable work delivery state without typed checkpoint "
                "version, hash, or coordinator lineage"
            ),
        },
    }
    audit_status = "PASS" if not issues and all(checks.values()) else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "CP-M1-E2E-FX-01B.6B.1",
        "audit_status": audit_status,
        "storage_fit": "NOT_FIT",
        "entry_decision": "STOP_FOR_CONTROLLED_PERSISTENCE_DECISION",
        "coordinator_activation": "CONTRACT_ONLY",
        "provider_plan_policy": (
            "EVIDENCE_ONLY_BEFORE_FINAL_DETERMINISTIC_PLAN"
        ),
        "durable_storage_fit": durable_storage_fit,
        "checks": checks,
        "product_value_residue": product_value_residue,
        "required_follow_up": {
            "slice": "CP-M1-E2E-FX-01B.6B.1A",
            "title": (
                "Durable Product Preparation Checkpoint and Approval Event "
                "Persistence Decision"
            ),
            "minimum_scope": [
                "typed immutable versioned product preparation checkpoint",
                "typed BUSINESS_FORMAL and accounting approval event admission",
                "exact AgentExecution and coordinator lineage",
                "idempotent ACK-loss and restart resume binding",
                "explicit final deterministic plan version policy",
            ],
            "migration_authorized_by_current_slice": False,
        },
        "remote_provider_required": False,
        "database_contacted": False,
        "content_included": False,
        "secret_included": False,
        "issues": issues,
    }


def _read(root: Path, relative: str, issues: list[str]) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        issues.append(f"required source is unavailable: {relative}")
        return ""


def _compact(value: str) -> str:
    return " ".join(value.lower().split())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = audit_storage_fit(args.root.resolve())
    report = args.report
    if not report.is_absolute():
        report = args.root.resolve() / report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["audit_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
