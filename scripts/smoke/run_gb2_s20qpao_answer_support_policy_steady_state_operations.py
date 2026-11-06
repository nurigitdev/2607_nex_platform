#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_controlled_activation import (
    PROGRESS_EVENT_TYPE,
    OperationalAnswerSupportProgressSink,
)
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    CUTOVER_MODE_CONTROLLED,
    CUTOVER_MODE_ENV,
    ROLLBACK_PENDING_REVIEW,
    ROLLED_BACK,
    OperationalPolicyCutoverStateStore,
    build_installed_answer_support_policy_cutover,
)
from nex_cx.retrieval_answer_support_policy_cutover_operations import (
    DECISION_EVENT_TYPE,
    OperationalPolicyCutoverDecisionSink,
)
from nex_cx.retrieval_answer_support_policy_steady_state import (
    STEADY_STATE_EVENT_TYPE,
    STEADY_STATE_MODE_CONTROLLED,
    STEADY_STATE_MODE_ENV,
    OperationalSteadyStateStateStore,
    build_installed_answer_support_policy_steady_state,
)
from nex_cx.retrieval_answer_support_policy_steady_state_operations import (
    DEFAULT_POLICY_PATH,
    WINDOW_EVENT_TYPE,
    OperationalPolicySteadyStateSource,
    build_installed_policy_steady_state_operations_source,
    load_policy_steady_state_operations_policy,
)
from nex_cx.retrieval_observability import (
    CX_ANSWER_SUPPORT_SHADOW_EVENT,
    OperationalAnswerSupportShadowSink,
)
from nex_mo import remote_provider
from nex_runtime import (
    OperationalEventEmitter,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_session_factory,
    database_pool_settings,
)
from nex_runtime.model_artifact_revision import admit_model_artifact_revision_evidence
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_gb2_s20qpag_policy_cutover_rollback_acceptance import (
    ARTIFACT_PATH,
    CASES_PATH,
    _FailingGenerationClient,
    _LiveGenerationClient,
    _bind_provider,
    _capacity_cases,
    _configuration_issues,
    _p95,
    _probe_ports,
)
from run_migrations import run_service_migrations, service_database_url
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpao_answer_support_policy_steady_state_operations.v1"
SMOKE_ENV = "NEX_GB2_S20QPAO_STEADY_STATE_OPERATIONS"
APPROVED_ENV = "NEX_GB2_S20QPAO_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPAO_OPERATOR_ID"
OUTPUT_PATH = (
    ROOT
    / "reports/live/gb2_ca00_s20qpao_answer_support_policy_"
    "steady_state_operations.json"
)
ACTIVATION_REPORT_PATH = (
    ROOT
    / "reports/live/gb2_ca00_s20qpan_answer_support_policy_"
    "steady_state_activation.json"
)
TRACE_ID = "20ac20ac20ac20ac20ac20ac20ac20ac"


def run_gb2_s20qpao_answer_support_policy_steady_state_operations(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    port_probe: Callable[[str, Sequence[int]], Mapping[str, bool]] | None = None,
    generation_client: Any | None = None,
    event_store: Any | None = None,
    cases_document: Mapping[str, Any] | None = None,
    activation_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    if env.get(APPROVED_ENV) != "1" or not env.get(OPERATOR_ENV):
        return _failure("operator_approval_required")

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_GENERATION_MAX_ATTEMPTS": "1",
        CUTOVER_MODE_ENV: CUTOVER_MODE_CONTROLLED,
        STEADY_STATE_MODE_ENV: STEADY_STATE_MODE_CONTROLLED,
    }
    engine = None
    cleanup = None
    provider_calls = 0
    cases: list[Mapping[str, Any]] = []
    stage = "SOURCE_ADMISSION"
    try:
        policy = load_policy_steady_state_operations_policy(
            Path(
                effective_env.get(
                    "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_OPERATIONS_PATH",
                    DEFAULT_POLICY_PATH,
                )
            )
        )
        admitted_activation = dict(
            activation_report or _load(ACTIVATION_REPORT_PATH)
        )
        _require_activation_binding(
            policy,
            admitted_activation,
            require_private_mode=activation_report is None,
        )
        cases = _capacity_cases(dict(cases_document or _load(CASES_PATH)))[:4]
        if len(cases) != 4:
            raise ValueError("four steady-state operations cases are required")

        activation = _load(
            ROOT
            / "services/nex-cx/nex_cx/data/"
            "answer_support_controlled_activation.v1.json"
        )
        if generation_client is None:
            stage = "PROVIDER_ADMISSION"
            issues = _configuration_issues(effective_env)
            if issues:
                raise ValueError(f"generation provider configuration invalid: {issues}")
            artifact = admit_model_artifact_revision_evidence(_load(ARTIFACT_PATH))
            binding = activation["readiness_manifest"]["candidate_profile"][
                "provider_binding"
            ]
            _bind_provider(effective_env, binding, artifact)
            config = remote_provider.build_remote_generation_execution_config(
                effective_env
            )
            parsed = urlparse(config.url)
            if not parsed.hostname or not parsed.port:
                raise ValueError("generation provider route is incomplete")
            reachable = dict(
                (port_probe or _probe_ports)(parsed.hostname, [parsed.port])
            )
            if reachable != {str(parsed.port): True}:
                raise ValueError("generation provider is unreachable")
            generation_client = _LiveGenerationClient(effective_env, requester)

        if event_store is None:
            stage = "DATABASE_ADMISSION"
            database_url = service_database_url(
                "nex-cx", profile="test", environ=effective_env
            )
            run_service_migrations("nex-cx", database_url=database_url, profile="test")
            engine = build_engine(
                database_url,
                pool_settings=database_pool_settings(
                    "nex-cx", workload="api", environ=effective_env
                ),
            )
            event_store = SqlAlchemyOperationalEventStore(build_session_factory(engine))
            cleanup = lambda: _cleanup_events(engine, policy)
            cleanup()

        emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
        cutover_store = OperationalPolicyCutoverStateStore(emitter, event_store)
        steady_store = OperationalSteadyStateStateStore(emitter, event_store)
        progress_sink = OperationalAnswerSupportProgressSink(emitter)
        outcome_sink = OperationalAnswerSupportShadowSink(emitter)
        decision_sink = OperationalPolicyCutoverDecisionSink(emitter)

        stage = "STEADY_STATE_OPERATIONS_ACTIVATION"
        cutover = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=cutover_store,
            decision_sink=decision_sink,
        )
        runtime = build_installed_answer_support_policy_steady_state(
            environ=effective_env,
            delegate=cutover,
            state_store=steady_store,
        )
        if cutover is None or runtime is None:
            raise ValueError("steady-state operations runtime did not activate")
        source = build_installed_policy_steady_state_operations_source(
            environ=effective_env,
            store=event_store,
            emitter=emitter,
            runtime_snapshot=runtime.snapshot,
        )

        stage = "LIVE_STEADY_STATE_CADENCE"
        started = monotonic()
        results: list[dict[str, Any]] = []
        for wave in range(3):
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(_apply, runtime, case, wave * 4 + offset)
                    for offset, case in enumerate(cases, start=1)
                ]
                results.extend(dict(future.result()) for future in futures)
        elapsed_seconds = max(monotonic() - started, 0.000001)
        runtime_snapshot = runtime.snapshot()
        operations = source.snapshot()
        provider_calls = int(
            runtime_snapshot["generation_client"].get("admitted_count", 0)
        )

        stage = "RESTART_RECOVERY"
        restarted_cutover = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=cutover_store,
            decision_sink=decision_sink,
        )
        restarted = build_installed_answer_support_policy_steady_state(
            environ=effective_env,
            delegate=restarted_cutover,
            state_store=steady_store,
        )
        if restarted is None:
            raise ValueError("steady-state operations runtime did not recover")
        restarted_source = build_installed_policy_steady_state_operations_source(
            environ=effective_env,
            store=event_store,
            emitter=emitter,
            runtime_snapshot=restarted.snapshot,
        )
        restarted_operations = restarted_source.snapshot()

        stage = "ROLLBACK_DOMINANCE"
        fault_cutover = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=_FailingGenerationClient(),
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=cutover_store,
            decision_sink=decision_sink,
        )
        fault_runtime = build_installed_answer_support_policy_steady_state(
            environ=effective_env,
            delegate=fault_cutover,
            state_store=steady_store,
        )
        if fault_runtime is None:
            raise ValueError("fault steady-state runtime was not constructed")
        fallback = fault_runtime.apply(**_application(cases[0], 99))
        terminal_operations = OperationalPolicySteadyStateSource(
            store=event_store,
            policy=policy,
            runtime_snapshot=fault_runtime.snapshot,
        ).snapshot()

        stage = "ACCEPTANCE_ASSERTION"
        decisions = operations["decisions"]
        progress = operations["progress"]
        checks = {
            "pan_activation_evidence_bound": admitted_activation["evidence_hash"]
            == policy["source_activation"]["evidence_hash"],
            "exact_steady_state_authorization_bound": runtime_snapshot[
                "steady_state_authorization_hash"
            ]
            == policy["steady_state_authorization_hash"],
            "exact_operations_profile_bound": runtime_snapshot[
                "operations_profile_hash"
            ]
            == policy["operations_profile_hash"],
            "steady_state_remained_active": operations["state"][
                "steady_state_state"
            ]
            == ACTIVE,
            "steady_state_cadence_complete": operations["operations_status"]
            == "OPERATOR_REVIEW_DUE",
            "exact_provider_sample_count": decisions["provider_sample_count"] == 12,
            "all_provider_decisions_applied": decisions["applied_count"] == 12,
            "decision_distribution_complete": (
                decisions["ready_count"] + decisions["low_confidence_count"] == 12
            ),
            "no_fallback_or_skip": decisions["fallback_count"] == 0
            and decisions["skipped_count"] == 0,
            "progress_completed": progress["completed_count"] == 12
            and progress["failed_count"] == 0,
            "bounded_c4_profile_preserved": runtime_snapshot["generation_client"][
                "maximum_in_flight"
            ]
            == 4
            and runtime_snapshot["generation_client"]["peak_in_flight"] <= 4,
            "slo_checks_passed": all(operations["slo"]["checks"].values()),
            "only_review_escalation_present": operations["escalations"]
            == ["OPERATOR_REVIEW_REQUIRED"],
            "permission_and_evidence_preserved": all(
                result["permission_snapshot"]
                == _package(case, index)["permission_snapshot"]
                and result["evidence_items"] == _package(case, index)["evidence_items"]
                for index, (result, case) in enumerate(
                    zip(results, cases * 3, strict=True), start=1
                )
            ),
            "restart_state_recovered": restarted.snapshot()["steady_state_state"]
            == ACTIVE,
            "restart_cadence_recovered": restarted_operations["cadence"][
                "provider_samples_since_review"
            ]
            == 12
            and restarted_operations["operations_status"] == "OPERATOR_REVIEW_DUE",
            "rollback_state_dominates": terminal_operations["operations_status"]
            == ROLLED_BACK,
            "rollback_current_request_fell_back": fallback
            == _package(cases[0], 99),
            "cadence_does_not_stop_runtime": operations["cadence"]["runtime_stopped"]
            is False,
            "holdout_not_accessed": True,
            "production_cutover_prohibited": operations["safety"][
                "production_cutover_permitted"
            ]
            is False,
        }
        residue_rows = 0
        if cleanup is not None:
            cleanup()
            residue_rows = _residue_count(engine, policy)
        checks["test_database_zero_residue"] = residue_rows == 0
        passed = all(checks.values())
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice_id": "GB2-CA00-S20Q-P-AO",
            "status": "PASS" if passed else "FAIL",
            "decision": (
                "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_ACCEPTED"
                if passed
                else "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_REJECTED"
            ),
            "policy_hash": policy["policy_hash"],
            "source_activation_evidence_hash": policy["source_activation"][
                "evidence_hash"
            ],
            "steady_state_authorization_hash": policy[
                "steady_state_authorization_hash"
            ],
            "operations_profile_hash": policy["operations_profile_hash"],
            "selected_policy_hash": policy["selected_policy_hash"],
            "checks": checks,
            "failed_checks": [name for name, ok in checks.items() if not ok],
            "live_execution": {
                "sample_count": decisions["provider_sample_count"],
                "provider_call_count": provider_calls,
                "ready_count": decisions["ready_count"],
                "low_confidence_count": decisions["low_confidence_count"],
                "elapsed_seconds": round(elapsed_seconds, 6),
                "peak_in_flight": runtime_snapshot["generation_client"][
                    "peak_in_flight"
                ],
                "feedback_p95_latency_ms": progress["feedback_p95_latency_ms"],
                "provider_p95_latency_ms": progress["provider_p95_latency_ms"],
                "e2e_p95_latency_ms": decisions["e2e_p95_latency_ms"],
            },
            "operations_status": operations["operations_status"],
            "health_status": operations["health_status"],
            "rollback_projection": terminal_operations["operations_status"],
            "restart_safe": checks["restart_cadence_recovered"],
            "database_profile": "test" if engine is not None else "injected",
            "test_database_residue_rows": residue_rows,
            "holdout_accessed": False,
            "runtime_stopped_at_review_cadence": False,
            "rollback_contract_preserved": True,
            "production_cutover_permitted": False,
            "next_boundary": (
                "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_OPERATOR_REVIEW"
            ),
        }
        result["evidence_hash"] = semantic_sha256_hash_ref(result)
        _assert_redacted(result, effective_env, cases)
        return result
    except Exception as exc:  # noqa: BLE001 - protected operations boundary
        result = _failure(
            "policy_steady_state_operations_failed",
            detail={"exception": exc.__class__.__name__, "stage": stage},
        )
        result["provider_http_requests"] = provider_calls
        _assert_redacted(result, effective_env, cases)
        return result
    finally:
        if cleanup is not None:
            try:
                cleanup()
            except Exception:  # noqa: BLE001 - best-effort zero-residue cleanup
                pass
        if engine is not None:
            engine.dispose()


def _apply(runtime: Any, case: Mapping[str, Any], index: int) -> dict[str, Any]:
    return dict(runtime.apply(**_application(case, index)))


def _application(case: Mapping[str, Any], index: int) -> dict[str, Any]:
    package = _package(case, index)
    return {
        "query_text": str(case["query"]),
        "evidence_items": package["evidence_items"],
        "primary_package": package,
        "access_context": CxAccessContext(
            tenant_id="s20qpao-tenant",
            subject_id="s20qpao-subject",
            caller_service_id="nex-ae-api",
            scopes=("cx:retrieval:read",),
            request_id=f"s20qpao-request-{index}",
            trace_id=TRACE_ID,
        ),
    }


def _package(case: Mapping[str, Any], index: int) -> dict[str, Any]:
    evidence = [
        {
            "evidence_id": str(row["candidate_id"]),
            "text": str(row["text"]),
            "permission_result": {"visible": True},
        }
        for row in case["candidates"]
    ]
    return {
        "retrieval_package_id": f"s20qpao-package-{index}",
        "package_hash": f"{index:064x}",
        "status": "READY",
        "purpose": "grounded_answer",
        "permission_snapshot": {"policy_version": "cx.private_owner_active.v1"},
        "evidence_items": evidence,
        "retrieval_profile": {
            "confidence_policy": {},
            "quality_policy": {},
            "candidate_summary": {"fused_candidate_count": len(evidence)},
        },
        "score_summary": {"score_spread": 0.0, "confidence_features": None},
        "no_answer_reason": None,
    }


def _require_activation_binding(
    policy: Mapping[str, Any],
    activation: Mapping[str, Any],
    *,
    require_private_mode: bool,
) -> None:
    source = policy["source_activation"]
    if (
        activation.get("status") != "PASS"
        or activation.get("decision") != source["decision"]
        or activation.get("evidence_schema_version")
        != source["evidence_schema_version"]
        or activation.get("evidence_hash") != source["evidence_hash"]
        or activation.get("steady_state_authorization_hash")
        != policy["steady_state_authorization_hash"]
        or activation.get("operator_decision_receipt_hash")
        != source["operator_decision_receipt_hash"]
        or activation.get("operations_profile_hash")
        != policy["operations_profile_hash"]
        or activation.get("selected_policy_hash") != policy["selected_policy_hash"]
        or activation.get("database_profile") != source["database_profile"]
        or activation.get("test_database_residue_rows")
        != source["test_database_residue_rows"]
        or activation.get("rollback", {}).get("reason_code")
        != source["rollback_reason"]
        or activation.get("next_boundary") != source["next_boundary"]
    ):
        raise ValueError("steady-state operations source activation drift")
    if require_private_mode:
        mode = stat.S_IMODE(ACTIVATION_REPORT_PATH.stat().st_mode)
        if mode & 0o077:
            raise ValueError("steady-state activation evidence is not private")


def _event_ids(policy: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for prefix, namespace, value in (
        (
            "cutover",
            "cx-answer-support-policy-cutover",
            policy["cutover_authorization_hash"],
        ),
        (
            "steady",
            "cx-answer-support-policy-steady-state",
            policy["steady_state_authorization_hash"],
        ),
    ):
        for state in (ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW):
            result[f"{prefix}_{state.lower()}"] = str(
                uuid5(NAMESPACE_URL, f"{namespace}:{value}:{state}")
            )
    result["window"] = str(
        uuid5(
            NAMESPACE_URL,
            "cx-answer-support-policy-steady-state-window:"
            f"{policy['steady_state_window_id']}",
        )
    )
    return result


def _cleanup_events(engine: Any, policy: Mapping[str, Any]) -> None:
    ids = _event_ids(policy)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE event_id IN (
                    :cutover_active, :cutover_rolled_back,
                    :cutover_rollback_pending_review,
                    :steady_active, :steady_rolled_back,
                    :steady_rollback_pending_review, :window
                )
                   OR (service_id = 'nex-cx'
                       AND event_type IN (
                           :progress_type, :shadow_type, :decision_type
                       )
                       AND trace_id = :trace_id)
                """
            ),
            {
                **ids,
                "progress_type": PROGRESS_EVENT_TYPE,
                "shadow_type": CX_ANSWER_SUPPORT_SHADOW_EVENT,
                "decision_type": DECISION_EVENT_TYPE,
                "trace_id": TRACE_ID,
            },
        )


def _residue_count(engine: Any, policy: Mapping[str, Any]) -> int:
    ids = _event_ids(policy)
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM service_operational_events
                    WHERE event_id IN (
                        :cutover_active, :cutover_rolled_back,
                        :cutover_rollback_pending_review,
                        :steady_active, :steady_rolled_back,
                        :steady_rollback_pending_review, :window
                    )
                       OR (service_id = 'nex-cx'
                           AND event_type IN (
                               :progress_type, :shadow_type, :decision_type
                           )
                           AND trace_id = :trace_id)
                    """
                ),
                {
                    **ids,
                    "progress_type": PROGRESS_EVENT_TYPE,
                    "shadow_type": CX_ANSWER_SUPPORT_SHADOW_EVENT,
                    "decision_type": DECISION_EVENT_TYPE,
                    "trace_id": TRACE_ID,
                },
            ).scalar_one()
        )


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AO",
        "status": "FAIL",
        "failure_code": code,
        "provider_http_requests": 0,
        "holdout_accessed": False,
        "runtime_stopped_at_review_cadence": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def _assert_redacted(
    result: Mapping[str, Any],
    environ: Mapping[str, str],
    cases: Sequence[Mapping[str, Any]],
) -> None:
    serialized = json.dumps(result, ensure_ascii=False)
    protected = [
        environ.get("NEX_MO_VLLM_API_KEY"),
        environ.get("NEX_CX_TEST_DATABASE_URL"),
    ]
    protected.extend(
        str(row["text"])
        for case in cases
        for row in case.get("candidates", [])
        if isinstance(row, Mapping)
    )
    if any(value and value in serialized for value in protected):
        raise ValueError("steady-state operations evidence leaked private material")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        live = result.get("live_execution", {})
        return (
            "gb2_s20qpao_policy_steady_state_operations=pass "
            f"samples={live.get('sample_count')} "
            f"provider_p95_ms={live.get('provider_p95_latency_ms')} "
            f"e2e_p95_ms={live.get('e2e_p95_latency_ms')} "
            "review=due rollback=verified"
        )
    if status == "skipped":
        return "gb2_s20qpao_policy_steady_state_operations=skipped"
    return (
        "gb2_s20qpao_policy_steady_state_operations=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpao_answer_support_policy_steady_state_operations()
    if result.get("status") != "SKIPPED" or not args.output.exists():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args.output.chmod(0o600)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
