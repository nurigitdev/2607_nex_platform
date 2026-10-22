#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-wc",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5
import run_p6_s5_postgres_smoke as p6_s5
import run_p8_s06_nsl_compatibility as p8_s06
from nex_ae_api.delegated_work import SqlAlchemyWaitRegistrationRepository
from nex_ae_api.nsl_approval_events import SqlAlchemyNslApprovalEventService
from nex_ae_api.nsl_approval_publication import P8NSLApprovalPort
from nex_ae_api.nsl_approval_requests import SqlAlchemyProtectedApprovalRequestStore
from nex_ae_api.platform_approval_evidence import (
    SqlAlchemyPlatformApprovalEvidenceRepository,
    build_platform_approval_evidence,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_runtime import load_env_file, redact_database_url
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from run_migrations import run_service_migrations

SCHEMA_VERSION = "p8_s53_approval_resume_postgres.v1"
SMOKE_ENV = "NEX_P8_S53_POSTGRES_SMOKE"
AE_DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
WC_DATABASE_ENV = "NEX_WC_TEST_DATABASE_URL"
EXPECTED_AE_DATABASE = "nex_ae_test"
EXPECTED_AE_ROLE = "nex_ae_user"
EXPECTED_WC_DATABASE = "nex_wc_test"
EXPECTED_WC_ROLE = "nex_wc_user"
DEFAULT_SOURCE = Path("/home/tprover/2608_nsl")
DEFAULT_LOCK = ROOT / "deployment/locks/nsl-v0.2-wheel.json"
DEFAULT_WHEEL_DIRECTORY = ROOT / "reports/deployment/p8-nsl-v0.2-wheel"
DEFAULT_PLATFORM_LOCK = ROOT / "deployment/locks/python-production.lock"
DEFAULT_REPORT = ROOT / "reports/quality/p8-s53-approval-resume-postgres.json"
WORKER = ROOT / "scripts/smoke/p8_s53_nsl_resume_worker.py"


class P8S53SmokeError(RuntimeError):
    pass


class _ApprovalRequestSnapshot:
    def __init__(self, value: Mapping[str, Any]) -> None:
        self._value = dict(value)

    def to_data(self) -> dict[str, Any]:
        return copy.deepcopy(self._value)


class _BindingSource:
    def __init__(self, value: Mapping[str, Any]) -> None:
        self._value = dict(value)

    def resolve(self, _approval_request: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(self._value)


class _WcClient:
    def __init__(self, service: ApprovalWorkItemService) -> None:
        self._service = service

    def create_or_get(self, work_item: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._service.create_or_get(work_item)


class _AuthorizationSource:
    def __init__(
        self, *, tenant_id: str, subject_id: str, decision_ref: str
    ) -> None:
        self._tenant_id = tenant_id
        self._subject_id = subject_id
        self._decision_ref = decision_ref

    def effective_authorization(self, **_kwargs: Any) -> Mapping[str, Any]:
        return {
            "active": True,
            "tenant_id": self._tenant_id,
            "subject_id": self._subject_id,
            "scopes": ["approval:decide"],
            "roles": [],
            "revision_hash": "f" * 64,
            "decision_ref": self._decision_ref,
        }


def run_p8_s53_approval_resume_postgres(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    source: Path = DEFAULT_SOURCE,
    lock_path: Path = DEFAULT_LOCK,
    wheel_directory: Path = DEFAULT_WHEEL_DIRECTORY,
    report_path: Path = DEFAULT_REPORT,
    python_bin: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S53",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
            "actual_postgres": False,
        }
    ae_database_url = env.get(AE_DATABASE_ENV, "")
    wc_database_url = env.get(WC_DATABASE_ENV, "")
    try:
        _require_database_target(
            ae_database_url,
            role=EXPECTED_AE_ROLE,
            database=EXPECTED_AE_DATABASE,
            label=AE_DATABASE_ENV,
        )
        _require_database_target(
            wc_database_url,
            role=EXPECTED_WC_ROLE,
            database=EXPECTED_WC_DATABASE,
            label=WC_DATABASE_ENV,
        )
        lock = p8_s06._load_object(lock_path, "NSL v0.2 wheel lock")
        release = p8_s06._verify_v02_release(source, wheel_directory, lock)
        ae_migration = run_service_migrations(
            "nex-ae-api", database_url=ae_database_url, profile="test"
        )
        wc_migration = run_service_migrations(
            "nex-wc", database_url=wc_database_url, profile="test"
        )
        with TemporaryDirectory(prefix="p8-s53-") as temporary:
            temporary_root = Path(temporary)
            target = temporary_root / "site-packages"
            wheel = wheel_directory / str(lock["wheel_filename"])
            p8_s06._install_wheel(python_bin, wheel, target, env)
            v02_env = _worker_environment(env, target)
            skill = _skill_identity(
                python_bin=python_bin,
                profile=source
                / "examples/voucher_draft_validation/controlled.profile.json",
                env=v02_env,
            )
            scenarios = _execute_scenarios(
                ae_database_url=ae_database_url,
                wc_database_url=wc_database_url,
                source=source,
                temporary_root=temporary_root,
                target=target,
                env=v02_env,
                python_bin=python_bin,
                lock_path=lock_path,
            )
        checks = {
            "release_identity_exact": release["wheel_sha256"]
            == lock["wheel_sha256"],
            "actual_ae_postgres": all(
                case["database"] == EXPECTED_AE_DATABASE
                and case["role"] == EXPECTED_AE_ROLE
                for case in scenarios.values()
            ),
            "actual_wc_postgres": all(
                case["wc_database"] == EXPECTED_WC_DATABASE
                and case["wc_role"] == EXPECTED_WC_ROLE
                for case in scenarios.values()
            ),
            "approve_resume_valid": _scenario_matches(
                scenarios["approve"], "VALID", "APPROVED", True
            ),
            "reject_resume_blocked": _scenario_matches(
                scenarios["reject"], "VALID", "REJECTED", False
            ),
            "expired_resume_blocked": _scenario_matches(
                scenarios["expiry"], "EXPIRED", "EXPIRED", False
            ),
            "mismatch_rejected_before_job": all(
                case["mismatch_event"]["inbox_state"] == "REJECTED"
                and case["mismatch_event"]["resume_runtime_job_id"] is None
                for case in scenarios.values()
            ),
            "exact_resume_lineage": all(
                case["lineage_exact"] for case in scenarios.values()
            ),
            "zero_eos_mutation": all(
                case["resume"]["write_execution"] == "not_started"
                and case["resume"]["eos_mutation_count"] == 0
                and case["prefix_audit"]["write_requested_count"] == 0
                for case in scenarios.values()
            ),
            "cleanup_complete": all(
                case["cleanup_remaining"] == 0 for case in scenarios.values()
            ),
        }
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S53",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "remote_provider_required": False,
            "release": release,
            "skill": skill,
            "databases": {
                "ae": redact_database_url(ae_database_url),
                "wc": redact_database_url(wc_database_url),
            },
            "migrations": {
                "ae": _migration_summary(ae_migration),
                "wc": _migration_summary(wc_migration),
            },
            "scenarios": scenarios,
            "checks": checks,
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "decision": {
                "p8_4_closed": all(checks.values()),
                "eos_write_enabled": False,
                "eos_mutation_count": 0,
            },
        }
    except Exception as exc:  # noqa: BLE001 - protected gate records failure evidence.
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S53",
            "status": "FAIL",
            "actual_postgres": False,
            "issues": [_redact(str(exc), ae_database_url, wc_database_url)],
            "decision": {"p8_4_closed": False, "eos_write_enabled": False},
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


def _execute_scenarios(
    *,
    ae_database_url: str,
    wc_database_url: str,
    source: Path,
    temporary_root: Path,
    target: Path,
    env: Mapping[str, str],
    python_bin: str,
    lock_path: Path,
) -> dict[str, Any]:
    original_snapshot_builder = p5_s5.build_capability_snapshot
    original_plan_builder = p5_s5.build_deterministic_agent_plan
    results: dict[str, Any] = {}
    for name, decision in (
        ("approve", "APPROVE"),
        ("reject", "REJECT"),
        ("expiry", "APPROVE"),
    ):
        case_root = temporary_root / name
        profile = _copy_profile(source=source, case_root=case_root)
        if name == "expiry":
            _build_expiring_program(
                python_bin=python_bin,
                profile=profile,
                env=env,
            )
        scenario_skill = _skill_identity(
            python_bin=python_bin,
            profile=profile,
            env=env,
        )

        def build_snapshot(
            *, admitted_skill: Mapping[str, Any] = scenario_skill, **kwargs: Any
        ) -> dict[str, Any]:
            local_capability = p6_s5.build_local_skill_capability(
                skill_id=str(admitted_skill["skill_id"]),
                exact_skill_version=str(admitted_skill["skill_version"]),
                skill_semantic_hash=str(admitted_skill["semantic_hash"]),
                input_contract_ref="contract://nex/p8/nsl-v0.2-controlled-input/v1",
                output_contract_ref="contract://nex/p8/approval-resume/v1",
                runtime_contract_ref="contract://nex/nsl/controlled-runtime/v0.2",
                trust_policy_id="nsl.production.ed25519.v1",
                backend_profile="NSL_V02_IN_PROCESS",
            )
            return original_snapshot_builder(
                **kwargs,
                capabilities=(*p6_s5.DEFAULT_P5_CAPABILITIES, local_capability),
            )

        def build_plan(
            *, admitted_skill: Mapping[str, Any] = scenario_skill, **kwargs: Any
        ) -> dict[str, Any]:
            plan = original_plan_builder(**kwargs)
            plan["steps"][0].update(
                {
                    "title": "Run protected NSL controlled Skill",
                    "objective": "Suspend and resume one governed WRITE before mutation.",
                    "required_capability": admitted_skill["skill_id"],
                    "capability_version_constraint": admitted_skill["skill_version"],
                    "output_contract_ref": "contract://nex/p8/approval-resume/v1",
                }
            )
            plan["plan_hash"] = semantic_sha256_hash_ref(
                {key: value for key, value in plan.items() if key != "plan_hash"}
            )
            return plan

        try:
            p5_s5.build_capability_snapshot = build_snapshot
            p5_s5.build_deterministic_agent_plan = build_plan
            case_evidence: dict[str, Any] = {}

            def verify_case(
                fixture: Mapping[str, Any],
                *,
                case: str = name,
                outcome: str = decision,
                root: Path = case_root,
                captured: dict[str, Any] = case_evidence,
            ) -> Mapping[str, Any]:
                verification = _verify_scenario(
                    fixture,
                    scenario=case,
                    decision=outcome,
                    ae_database_url=ae_database_url,
                    wc_database_url=wc_database_url,
                    profile=root / "controlled.profile.json",
                    target=target,
                    env=env,
                    python_bin=python_bin,
                    lock_path=lock_path,
                )
                captured.update(verification["scenario"])
                return verification

            result = p5_s5._execute_postgres_smoke(
                ae_database_url,
                verifier=verify_case,
            )
            if result["status"] != "PASS":
                raise P8S53SmokeError(f"{name} PostgreSQL fixture failed")
            results[name] = {
                "database": result["database"],
                "role": result["role"],
                **case_evidence,
            }
        finally:
            p5_s5.build_capability_snapshot = original_snapshot_builder
            p5_s5.build_deterministic_agent_plan = original_plan_builder
    return results


def _verify_scenario(
    fixture: Mapping[str, Any],
    *,
    scenario: str,
    decision: str,
    ae_database_url: str,
    wc_database_url: str,
    profile: Path,
    target: Path,
    env: Mapping[str, str],
    python_bin: str,
    lock_path: Path,
) -> dict[str, Any]:
    ae_factory = fixture["factory"]
    tenant_id = str(fixture["tenant_id"])
    execution = dict(fixture["execution"])
    local_step = dict(fixture["executable_plan"]["steps"][0])
    if local_step.get("executor_kind") != "LOCAL_SKILL":
        raise P8S53SmokeError("P8-S53 fixture did not compile a LOCAL_SKILL step")
    approver_id = str(execution["principal_id"])
    nsl_execution_id = f"p8-s53-{scenario}-{uuid4().hex}"
    business_operation_id = f"p8-s53-operation-{scenario}-{uuid4().hex}"
    worker_id = f"p8-s53-{scenario}-{uuid4().hex[:12]}"
    wc_engine = create_engine(wc_database_url, poolclass=NullPool)
    wc_factory = sessionmaker(bind=wc_engine, expire_on_commit=False)
    cleanup_remaining = -1
    try:
        _bind_profile_principal(
            profile=profile,
            tenant_id=tenant_id,
            subject_id=approver_id,
        )
        case_root = profile.parent
        checkpoint = case_root / "controlled-prefix.nsc"
        approval_path = case_root / "approval-request.json"
        audit_path = case_root / "controlled-prefix.audit.jsonl"
        prefix = _run_json(
            (
                python_bin,
                "-m",
                "nsl",
                "run",
                "--profile",
                str(profile),
                "--no-isolate",
                "--execution-id",
                nsl_execution_id,
                "--business-operation-id",
                business_operation_id,
                "--checkpoint-out",
                str(checkpoint),
                "--approval-request-out",
                str(approval_path),
                "--audit-out",
                str(audit_path),
            ),
            env=env,
            operation=f"execute P8-S53 {scenario} controlled prefix",
        )
        request_data = _approval_request_data(approval_path)
        prefix_audit = p8_s06._audit_summary(audit_path)
        if prefix.get("result", {}).get("status") != "WAITING_FOR_APPROVAL":
            raise P8S53SmokeError("NSL v0.2 prefix did not suspend for approval")
        if request_data["tenant_id"] != tenant_id:
            raise P8S53SmokeError("NSL v0.2 prefix tenant differs from AE tenant")
        checkpoint_version = _checkpoint_version(checkpoint)
        decision_time = datetime.now(UTC).replace(microsecond=0)
        expires_at = (
            None
            if request_data["expires_at"] is None
            else _instant(request_data["expires_at"])
        )
        if expires_at is not None and decision_time >= expires_at:
            raise P8S53SmokeError("generated ApprovalRequest expired before decision")
        _mark_waiting(
            ae_factory,
            tenant_id=tenant_id,
            execution_id=execution["agent_execution_id"],
            step_id=local_step["executable_step_id"],
        )
        request_store = SqlAlchemyProtectedApprovalRequestStore(
            ae_factory, clock=lambda: decision_time
        )
        wait_repository = SqlAlchemyWaitRegistrationRepository(ae_factory)
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_factory)
        publication = P8NSLApprovalPort(
            binding_source=_BindingSource(
                {
                    "tenant_id": tenant_id,
                    "agent_execution_id": execution["agent_execution_id"],
                    "executable_step_id": local_step["executable_step_id"],
                    "nsl_execution_id": nsl_execution_id,
                    "business_operation_id": business_operation_id,
                    "checkpoint_version": checkpoint_version,
                    "target_approver_ref": approver_id,
                    "target_role_ref": None,
                    "target_org_scope_ref": None,
                    "target_project_scope_ref": None,
                }
            ),
            request_store=request_store,
            wait_repository=wait_repository,
            wc_client=_WcClient(ApprovalWorkItemService(wc_repository)),
            clock=lambda: decision_time,
        )
        asyncio.run(publication.publish(_ApprovalRequestSnapshot(request_data)))
        work_item = wc_repository.get_by_source(
            tenant_id=tenant_id,
            approval_domain="NSL_WRITE",
            source_ref=request_data["approval_request_id"],
        )
        if work_item is None:
            raise P8S53SmokeError("WC ApprovalWorkItem was not persisted")
        decision_ref = f"oa-decision-p8-s53-{scenario}"
        decision_result = ApprovalDecisionService(
            wc_repository,
            authorizer=ApprovalDecisionAuthorizer(
                _AuthorizationSource(
                    tenant_id=tenant_id,
                    subject_id=approver_id,
                    decision_ref=decision_ref,
                ),
                clock=lambda: decision_time,
            ),
            clock=lambda: decision_time,
        ).decide(
            tenant_id=tenant_id,
            approval_work_item_id=work_item["approval_work_item_id"],
            decision=decision,
            decided_by=approver_id,
        )
        approval_decision = decision_result["decision"]
        terminal_item = wc_repository.get(
            tenant_id=tenant_id,
            approval_work_item_id=work_item["approval_work_item_id"],
        )
        protected = request_store.get(
            tenant_id=tenant_id,
            approval_request_id=request_data["approval_request_id"],
        )
        canonical_request = request_store.load_request(
            tenant_id=tenant_id,
            approval_request_id=request_data["approval_request_id"],
        )
        wait = wait_repository.get(
            tenant_id=tenant_id,
            agent_execution_id=execution["agent_execution_id"],
            executable_step_id=local_step["executable_step_id"],
            wait_type="NSL_APPROVAL",
        )
        if any(value is None for value in (terminal_item, protected, canonical_request, wait)):
            raise P8S53SmokeError("approval persistence lineage is incomplete")
        evidence = build_platform_approval_evidence(
            approval_request=canonical_request,
            protected_request=protected,
            wait_registration=wait,
            approval_work_item=terminal_item,
            approval_decision=approval_decision,
            created_at=decision_time,
        )
        saved_evidence = SqlAlchemyPlatformApprovalEvidenceRepository(
            ae_factory
        ).create_or_get(evidence)
        event_service = SqlAlchemyNslApprovalEventService(
            ae_factory,
            runtime_jobs=SqlAlchemyRuntimeJobQueue(ae_factory),
            clock=lambda: decision_time,
        )
        event = _approval_event(
            execution=execution,
            work_item=work_item,
            decision=approval_decision,
            evidence=saved_evidence,
        )
        mismatch = event_service.ingest(
            {
                **event,
                "event_id": str(uuid4()),
                "nsl_execution_id": f"{nsl_execution_id}-mismatch",
            }
        )
        matched = event_service.ingest(event)
        if matched["inbox_state"] != "MATCHED":
            raise P8S53SmokeError("valid approval event did not enqueue resume")
        if scenario == "expiry":
            if expires_at is None:
                raise P8S53SmokeError("expiry scenario requires an NSL TTL policy")
            observed_at = expires_at
        else:
            observed_at = decision_time + timedelta(seconds=1)
        resume = _run_resume_worker(
            python_bin=python_bin,
            env=env,
            target=target,
            ae_database_url=ae_database_url,
            wc_database_url=wc_database_url,
            tenant_id=tenant_id,
            worker_id=worker_id,
            profile=profile,
            checkpoint=checkpoint,
            approval_request=approval_path,
            observed_at=observed_at,
            lock_path=lock_path,
        )
        with wc_engine.connect() as connection:
            wc_database, wc_role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
        lineage_exact = (
            resume["nsl_execution_id"] == nsl_execution_id
            and resume["business_operation_id"] == business_operation_id
            and resume["checkpoint_version"] == checkpoint_version
            and resume["approval_request_id"]
            == request_data["approval_request_id"]
            and resume["claim_id"] == matched["resume_runtime_job_id"]
        )
        scenario_evidence = {
            "scenario": scenario,
            "wc_database": wc_database,
            "wc_role": wc_role,
            "prefix_status": prefix["result"]["status"],
            "prefix_audit": prefix_audit,
            "mismatch_event": mismatch,
            "matched_event": matched,
            "resume": resume,
            "lineage_exact": lineage_exact,
        }
        return {
            "checks": {
                f"{scenario}_prefix_waiting": scenario_evidence["prefix_status"]
                == "WAITING_FOR_APPROVAL",
                f"{scenario}_mismatch_rejected": mismatch["inbox_state"]
                == "REJECTED",
                f"{scenario}_resume_completed": resume["runtime_job_state"]
                == "DONE",
                f"{scenario}_lineage_exact": lineage_exact,
                f"{scenario}_zero_write": prefix_audit["write_requested_count"]
                == 0
                and resume["write_execution"] == "not_started",
            },
            "row_counts": {f"p8_s53_{scenario}_resume_job": 1},
            "scenario": scenario_evidence,
        }
    finally:
        cleanup_remaining = _cleanup_case(
            ae_factory,
            wc_factory,
            tenant_id=tenant_id,
        )
        wc_engine.dispose()
        if "scenario_evidence" in locals():
            scenario_evidence["cleanup_remaining"] = cleanup_remaining


def _copy_profile(*, source: Path, case_root: Path) -> Path:
    shutil.copytree(source / "examples/voucher_draft_validation", case_root)
    return case_root / "controlled.profile.json"


def _bind_profile_principal(
    *, profile: Path, tenant_id: str, subject_id: str
) -> None:
    principal_path = profile.parent / "principal_write.json"
    principal = json.loads(principal_path.read_text(encoding="utf-8"))
    principal["tenant_id"] = tenant_id
    principal["subject_id"] = subject_id
    principal_path.write_text(
        json.dumps(principal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _build_expiring_program(
    *, python_bin: str, profile: Path, env: Mapping[str, str]
) -> None:
    output = profile.parent / "voucher_draft_write_ttl.nso"
    script = (
        "from dataclasses import replace; "
        "from pathlib import Path; "
        "from nsl.cli import _load_program; "
        "from nsl.cli_config import load_tool_catalog; "
        "from nsl.cli_profile import resolve_cli_configuration; "
        "from nsl.ir import ApprovalPolicy,ApprovalStatement,NsoCodec; "
        f"profile=Path({str(profile)!r}); "
        "config=resolve_cli_configuration(profile_path=profile); "
        "skill=_load_program(config.program,load_tool_catalog(config.tool_contracts)); "
        "body=tuple(replace(item,policy=ApprovalPolicy(ttl_seconds=60)) "
        "if isinstance(item,ApprovalStatement) else item for item in skill.body); "
        "skill=replace(skill,body=body).with_computed_hash(); "
        f"Path({str(output)!r}).write_bytes(NsoCodec.encode(skill))"
    )
    completed = subprocess.run(
        (python_bin, "-c", script),
        cwd=ROOT,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not output.is_file():
        detail = (completed.stderr or completed.stdout).strip()
        raise P8S53SmokeError(f"build NSL TTL fixture failed: {detail[-2000:]}")
    document = json.loads(profile.read_text(encoding="utf-8"))
    document["program"] = output.name
    profile.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _mark_waiting(
    factory: sessionmaker[Session], *, tenant_id: str, execution_id: str, step_id: str
) -> None:
    with factory.begin() as session:
        parent = session.execute(
            text(
                "UPDATE ae_agent_execution SET state = 'WAITING_APPROVAL', "
                "phase = 'STEP_EXECUTION', version = version + 1, updated_at = now() "
                "WHERE tenant_id = :tenant AND agent_execution_id = :execution"
            ),
            {"tenant": tenant_id, "execution": execution_id},
        )
        step = session.execute(
            text(
                "UPDATE ae_executable_step SET state = 'WAITING', "
                "version = version + 1, updated_at = now() "
                "WHERE tenant_id = :tenant AND executable_step_id = :step "
                "AND executor_kind = 'LOCAL_SKILL'"
            ),
            {"tenant": tenant_id, "step": step_id},
        )
        if int(parent.rowcount or 0) != 1 or int(step.rowcount or 0) != 1:
            raise P8S53SmokeError("approval suspension state could not be projected")


def _approval_event(
    *,
    execution: Mapping[str, Any],
    work_item: Mapping[str, Any],
    decision: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "ae_nsl_approval_decided_event.v1",
        "event_id": str(uuid4()),
        "event_name": "NSL_APPROVAL_DECIDED",
        "tenant_id": evidence["tenant_id"],
        "approval_work_item_ref": work_item["approval_work_item_id"],
        "approval_request_id": evidence["approval_request_id"],
        "nsl_execution_id": evidence["nsl_execution_id"],
        "business_operation_id": evidence["business_operation_id"],
        "decision": evidence["decision"],
        "approval_evidence_ref": (
            f"ae-approval-evidence:{evidence['approval_request_id']}"
        ),
        "evidence_integrity": evidence["evidence_integrity"],
        "correlation_id": execution["correlation_id"],
        "causation_id": decision["decision_id"],
        "occurred_at": decision["decided_at"],
    }


def _run_resume_worker(
    *,
    python_bin: str,
    env: Mapping[str, str],
    target: Path,
    ae_database_url: str,
    wc_database_url: str,
    tenant_id: str,
    worker_id: str,
    profile: Path,
    checkpoint: Path,
    approval_request: Path,
    observed_at: datetime,
    lock_path: Path,
) -> dict[str, Any]:
    worker_env = _worker_environment(env, target)
    return _run_json(
        (
            python_bin,
            str(WORKER),
            "--ae-database-url",
            ae_database_url,
            "--wc-database-url",
            wc_database_url,
            "--tenant-id",
            tenant_id,
            "--worker-id",
            worker_id,
            "--profile",
            str(profile),
            "--checkpoint",
            str(checkpoint),
            "--approval-request",
            str(approval_request),
            "--observed-at",
            _time(observed_at),
            "--lock",
            str(lock_path),
            "--platform-lock",
            str(DEFAULT_PLATFORM_LOCK),
        ),
        env=worker_env,
        operation="execute isolated NSL v0.2 approval resume worker",
    )


def _skill_identity(
    *, python_bin: str, profile: Path, env: Mapping[str, str]
) -> dict[str, Any]:
    document = json.loads(profile.read_text(encoding="utf-8"))
    program = profile.parent / str(document["program"])
    if program.suffix == ".nso":
        result = _run_json(
            (python_bin, "-m", "nsl", "inspect", str(program)),
            env=env,
            operation="inspect admitted NSL v0.2 controlled artifact",
        )["artifact"]
        return {
            "skill_id": result["skill"]["id"],
            "skill_version": result["skill"]["version"],
            "semantic_hash": result["hashes"]["semantic_sha256"],
        }
    result = _run_json(
        (python_bin, "-m", "nsl", "check", "--profile", str(profile)),
        env=env,
        operation="inspect admitted NSL v0.2 controlled Skill",
    )
    return {
        "skill_id": result["skill_id"],
        "skill_version": result["skill_version"],
        "semantic_hash": result["semantic_hash"],
    }


def _worker_environment(
    env: Mapping[str, str], target: Path
) -> dict[str, str]:
    isolated = dict(env)
    isolated["PYTHONPATH"] = os.pathsep.join(
        (
            str(target),
            str(ROOT / "services/nex-ae-api"),
            str(ROOT / "services/nex-wc"),
            str(ROOT / "services/_shared"),
        )
    )
    isolated["PYTHONDONTWRITEBYTECODE"] = "1"
    return isolated


def _run_json(
    command: Sequence[str], *, env: Mapping[str, str], operation: str
) -> dict[str, Any]:
    completed = subprocess.run(
        tuple(command),
        cwd=ROOT,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise P8S53SmokeError(f"{operation} failed: {detail[-2000:]}")
    value = json.loads(completed.stdout)
    if not isinstance(value, Mapping):
        raise P8S53SmokeError(f"{operation} returned a non-object")
    return dict(value)


def _approval_request_data(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    request = document.get("approval_request")
    if document.get("schema_version") != "1.0" or not isinstance(request, Mapping):
        raise P8S53SmokeError("NSL ApprovalRequest artifact is invalid")
    return dict(request)


def _checkpoint_version(path: Path) -> int:
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    version = checkpoint.get("checkpoint_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise P8S53SmokeError("NSL checkpoint version is invalid")
    return version


def _cleanup_case(
    ae_factory: sessionmaker[Session],
    wc_factory: sessionmaker[Session],
    *,
    tenant_id: str,
) -> int:
    with ae_factory.begin() as session:
        for table in (
            "ae_runtime_job_attempt",
            "ae_external_event_inbox",
            "ae_approval_evidence",
            "ae_wait_registration",
            "ae_runtime_job",
            "ae_nsl_approval_request",
        ):
            session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant"),
                {"tenant": tenant_id},
            )
    with wc_factory.begin() as session:
        for table in (
            "wc_approval_outbox",
            "wc_approval_decision",
            "wc_approval_work_item",
        ):
            session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tenant"),
                {"tenant": tenant_id},
            )
    remaining = 0
    with ae_factory() as session:
        for table in (
            "ae_runtime_job_attempt",
            "ae_external_event_inbox",
            "ae_approval_evidence",
            "ae_wait_registration",
            "ae_runtime_job",
            "ae_nsl_approval_request",
        ):
            remaining += int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
    with wc_factory() as session:
        for table in (
            "wc_approval_outbox",
            "wc_approval_decision",
            "wc_approval_work_item",
        ):
            remaining += int(
                session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"),
                    {"tenant": tenant_id},
                ).scalar_one()
            )
    return remaining


def _scenario_matches(
    scenario: Mapping[str, Any], validation: str, status: str, gate_passed: bool
) -> bool:
    resume = scenario["resume"]
    return (
        resume["approval_validation"] == validation
        and resume["approval_status"] == status
        and resume["approval_gate_passed"] is gate_passed
        and resume["claim_consumed"] is True
        and resume["checkpoint_consumed"] is True
        and resume["runtime_job_state"] == "DONE"
    )


def _require_database_target(
    value: str, *, role: str, database: str, label: str
) -> None:
    if not value:
        raise P8S53SmokeError(f"{label} is required")
    parsed = urlsplit(value)
    if unquote(parsed.username or "") != role or unquote(
        parsed.path.lstrip("/")
    ) != database:
        raise P8S53SmokeError(f"{label} must target {role}@.../{database}")


def _migration_summary(value: Any) -> dict[str, Any]:
    return {
        "planned_count": len(value.planned),
        "applied_count": len(value.applied),
        "skipped_count": len(value.skipped),
        "latest_version": value.planned[-1] if value.planned else None,
    }


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise P8S53SmokeError("timestamp must include timezone")
    return parsed.astimezone(UTC)


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _redact(detail: str, *database_urls: str) -> str:
    redacted = detail
    for database_url in database_urls:
        if not database_url:
            continue
        redacted = redacted.replace(database_url, redact_database_url(database_url))
        password = urlsplit(database_url).password
        if password:
            redacted = redacted.replace(unquote(password), "***")
    return redacted


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "p8_s53_approval_resume_postgres="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"checks={evidence.get('checks_passed', 0)}/"
        f"{evidence.get('checks_total', 0)} "
        f"p8_4_closed={str(bool(evidence.get('decision', {}).get('p8_4_closed'))).lower()} "
        f"eos_mutations={evidence.get('decision', {}).get('eos_mutation_count', 'not-run')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run P8-S53 protected approval resume PostgreSQL gate"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_env_file(ROOT / ".env.local")
    result = run_p8_s53_approval_resume_postgres(
        execute=args.execute,
        source=args.source,
        report_path=args.report,
        python_bin=args.python_bin,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
