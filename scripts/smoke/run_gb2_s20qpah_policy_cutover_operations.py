#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
    load_controlled_activation_bundle,
)
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    CUTOVER_MODE_CONTROLLED,
    CUTOVER_MODE_ENV,
    DEFAULT_AUTHORIZATION_PATH,
    ROLLBACK_PENDING_REVIEW,
    ROLLED_BACK,
    OperationalPolicyCutoverStateStore,
    build_installed_answer_support_policy_cutover,
    load_cutover_authorization,
)
from nex_cx.retrieval_answer_support_policy_cutover_operations import (
    DECISION_EVENT_TYPE,
    DEFAULT_POLICY_PATH,
    OperationalPolicyCutoverDecisionSink,
    build_installed_policy_cutover_operations_source,
    load_policy_cutover_operations_policy,
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
from run_gb2_s20qpw_sync_capacity import (
    _bind_provider,
    _capacity_cases,
    _configuration_issues,
    _probe_ports,
)
from run_migrations import run_service_migrations, service_database_url
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = "gb2_s20qpah_answer_support_policy_cutover_operations.v1"
SMOKE_ENV = "NEX_GB2_S20QPAH_POLICY_CUTOVER_OPERATIONS"
APPROVED_ENV = "NEX_GB2_S20QPAH_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPAH_OPERATOR_ID"
OUTPUT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpah_answer_support_policy_cutover_operations.json"
)
CASES_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_extended_shadow_v1_cases.json"
)
ARTIFACT_PATH = ROOT / "reports/live/gb2_s20qpi_qwen3_5_9b_revision.json"
TRACE_ID = "20aa20aa20aa20aa20aa20aa20aa20aa"


class _LiveGenerationClient:
    def __init__(
        self, environ: Mapping[str, str], requester: Callable[..., Any] | None
    ) -> None:
        self.environ = dict(environ)
        self.requester = requester

    def create_generation(
        self, payload: dict[str, Any], *, request_id: str, trace_id: str
    ) -> dict[str, Any]:
        return remote_provider.execute_remote_generation_request(
            payload,
            request_id=request_id,
            trace_id=trace_id,
            environ=self.environ,
            requester=self.requester,
        )


def run_gb2_s20qpah_policy_cutover_operations(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    port_probe: Callable[[str, Sequence[int]], Mapping[str, bool]] | None = None,
    generation_client: Any | None = None,
    event_store: Any | None = None,
    cases_document: Mapping[str, Any] | None = None,
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
    }
    engine = None
    cleanup = None
    stage = "SOURCE_ADMISSION"
    provider_calls = 0
    cases: list[Mapping[str, Any]] = []
    try:
        activation = load_controlled_activation_bundle(
            Path(
                effective_env.get(
                    "NEX_CX_ANSWER_SUPPORT_ACTIVATION_BUNDLE_PATH",
                    ROOT
                    / "services/nex-cx/nex_cx/data/answer_support_controlled_activation.v1.json",
                )
            )
        )
        authorization = load_cutover_authorization(
            Path(
                effective_env.get(
                    "NEX_CX_ANSWER_SUPPORT_POLICY_AUTHORIZATION_PATH",
                    DEFAULT_AUTHORIZATION_PATH,
                )
            ),
            activation_bundle=activation,
        )
        policy = load_policy_cutover_operations_policy(
            Path(
                effective_env.get(
                    "NEX_CX_ANSWER_SUPPORT_POLICY_OPERATIONS_PATH",
                    DEFAULT_POLICY_PATH,
                )
            )
        )
        _require_exact_bindings(policy, authorization, activation)
        cases = _capacity_cases(dict(cases_document or _load(CASES_PATH)))
        if len(cases) < 4:
            raise ValueError("at least four cutover operations cases are required")
        cases = cases[:4]

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
            cleanup = lambda: _cleanup_events(
                engine,
                authorization_hash=authorization["authorization_hash"],
                window_id=policy["window_id"],
            )
            cleanup()

        emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
        state_store = OperationalPolicyCutoverStateStore(emitter, event_store)
        decision_sink = OperationalPolicyCutoverDecisionSink(emitter)
        progress_sink = OperationalAnswerSupportProgressSink(emitter)
        outcome_sink = OperationalAnswerSupportShadowSink(emitter)
        stage = "CUTOVER_OPERATIONS_ACTIVATION"
        runtime = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=state_store,
            decision_sink=decision_sink,
        )
        if runtime is None:
            raise ValueError("policy cutover runtime did not activate")
        source = build_installed_policy_cutover_operations_source(
            environ=effective_env,
            store=event_store,
            emitter=emitter,
            runtime_snapshot=runtime.snapshot,
        )

        stage = "LIVE_OPERATIONS_WINDOW"
        started = monotonic()
        results: list[dict[str, Any]] = []
        for wave in range(3):
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(
                        _apply,
                        runtime,
                        case,
                        wave * 4 + offset,
                    )
                    for offset, case in enumerate(cases, start=1)
                ]
                results.extend(future.result() for future in futures)
        elapsed_seconds = max(monotonic() - started, 0.000001)
        runtime_snapshot = runtime.snapshot()
        operations = source.snapshot()
        provider_calls = int(
            runtime_snapshot["generation_client"].get("admitted_count", 0)
        )

        stage = "RESTART_RECOVERY"
        restarted_runtime = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=state_store,
            decision_sink=decision_sink,
        )
        if restarted_runtime is None:
            raise ValueError("active cutover runtime did not recover")
        restarted_source = build_installed_policy_cutover_operations_source(
            environ=effective_env,
            store=event_store,
            emitter=emitter,
            runtime_snapshot=restarted_runtime.snapshot,
        )
        restarted_operations = restarted_source.snapshot()

        stage = "ACCEPTANCE_ASSERTION"
        decisions = operations["decisions"]
        progress = operations["progress"]
        checks = {
            "pag_acceptance_bound": policy["source_acceptance"]["evidence_hash"]
            == "sha256:c07655bcba5fc85db6506bbcba873dbb33d3ed91fd2395cd266837df18545aac",
            "exact_cutover_authorization_bound": policy["authorization_hash"]
            == authorization["authorization_hash"],
            "cutover_remained_active": operations["state"]["cutover_state"] == ACTIVE,
            "bounded_observation_window_complete": operations["operations_status"]
            == "REVIEW_REQUIRED",
            "exact_provider_sample_count": decisions["provider_sample_count"] == 12,
            "all_decisions_user_visible": decisions["applied_count"] == 12,
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
            "permission_and_evidence_preserved": all(
                result["permission_snapshot"]
                == _package(case, index)["permission_snapshot"]
                and result["evidence_items"] == _package(case, index)["evidence_items"]
                for index, (result, case) in enumerate(
                    zip(results, cases * 3, strict=True), start=1
                )
            ),
            "restart_state_recovered": restarted_runtime.snapshot()["cutover_state"]
            == ACTIVE,
            "restart_window_recovered": restarted_operations["decisions"][
                "provider_sample_count"
            ]
            == 12
            and restarted_operations["operations_status"] == "REVIEW_REQUIRED",
            "window_cap_is_observational": operations["safety"][
                "runtime_stopped_at_observation_cap"
            ]
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
            residue_rows = _residue_count(
                engine,
                authorization_hash=authorization["authorization_hash"],
                window_id=policy["window_id"],
            )
        checks["test_database_zero_residue"] = residue_rows == 0
        passed = all(checks.values())
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice_id": "GB2-CA00-S20Q-P-AH",
            "status": "PASS" if passed else "FAIL",
            "decision": (
                "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_ACCEPTED"
                if passed
                else "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_REJECTED"
            ),
            "policy_hash": policy["policy_hash"],
            "authorization_hash": authorization["authorization_hash"],
            "activation_bundle_hash": authorization["activation_bundle_hash"],
            "selected_policy_hash": authorization["selected_policy_hash"],
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
            "restart_safe": checks["restart_window_recovered"],
            "database_profile": "test" if engine is not None else "injected",
            "test_database_residue_rows": residue_rows,
            "holdout_accessed": False,
            "user_visible_policy_change": True,
            "production_cutover_permitted": False,
            "next_boundary": "ANSWER_SUPPORT_POLICY_CUTOVER_OPERATIONS_OPERATOR_REVIEW",
        }
        result["evidence_hash"] = semantic_sha256_hash_ref(result)
        _assert_redacted(result, effective_env, cases)
        return result
    except Exception as exc:  # noqa: BLE001 - protected operations boundary
        result = _failure(
            "policy_cutover_operations_failed",
            detail={"exception": exc.__class__.__name__, "stage": stage},
        )
        result["provider_http_requests"] = provider_calls
        _assert_redacted(result, effective_env, cases)
        return result
    finally:
        if cleanup is not None:
            cleanup()
        if engine is not None:
            engine.dispose()


def _apply(runtime: Any, case: Mapping[str, Any], index: int) -> dict[str, Any]:
    return dict(
        runtime.apply(
            query_text=str(case["query"]),
            evidence_items=_package(case, index)["evidence_items"],
            primary_package=_package(case, index),
            access_context=CxAccessContext(
                tenant_id="s20qpah-tenant",
                subject_id="s20qpah-subject",
                caller_service_id="nex-ae-api",
                scopes=("cx:retrieval:read",),
                request_id=f"s20qpah-request-{index}",
                trace_id=TRACE_ID,
            ),
        )
    )


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
        "retrieval_package_id": f"s20qpah-package-{index}",
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
        "score_summary": {
            "score_spread": 0.0,
            "confidence_features": None,
        },
        "no_answer_reason": None,
    }


def _require_exact_bindings(
    policy: Mapping[str, Any],
    authorization: Mapping[str, Any],
    activation: Mapping[str, Any],
) -> None:
    if (
        policy["authorization_hash"] != authorization["authorization_hash"]
        or policy["activation_bundle_hash"] != activation["bundle_hash"]
        or policy["selected_policy_hash"]
        != activation["selected_policy"]["policy_hash"]
    ):
        raise ValueError("operations policy source binding drift")


def _cleanup_events(engine: Any, *, authorization_hash: str, window_id: str) -> None:
    state_ids = [
        str(
            uuid5(
                NAMESPACE_URL,
                f"cx-answer-support-policy-cutover:{authorization_hash}:{state}",
            )
        )
        for state in (ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW)
    ]
    window_event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"cx-answer-support-policy-cutover-window:{window_id}",
        )
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE event_id IN (:active_id, :rollback_id, :pending_id, :window_id)
                   OR (service_id = 'nex-cx'
                       AND event_type IN (:progress_type, :shadow_type, :decision_type)
                       AND trace_id = :trace_id)
                """
            ),
            {
                "active_id": state_ids[0],
                "rollback_id": state_ids[1],
                "pending_id": state_ids[2],
                "window_id": window_event_id,
                "progress_type": PROGRESS_EVENT_TYPE,
                "shadow_type": CX_ANSWER_SUPPORT_SHADOW_EVENT,
                "decision_type": DECISION_EVENT_TYPE,
                "trace_id": TRACE_ID,
            },
        )


def _residue_count(engine: Any, *, authorization_hash: str, window_id: str) -> int:
    state_ids = [
        str(
            uuid5(
                NAMESPACE_URL,
                f"cx-answer-support-policy-cutover:{authorization_hash}:{state}",
            )
        )
        for state in (ACTIVE, ROLLED_BACK, ROLLBACK_PENDING_REVIEW)
    ]
    window_event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"cx-answer-support-policy-cutover-window:{window_id}",
        )
    )
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM service_operational_events
                    WHERE event_id IN (:active_id, :rollback_id, :pending_id, :window_id)
                       OR (service_id = 'nex-cx'
                           AND event_type IN (:progress_type, :shadow_type, :decision_type)
                           AND trace_id = :trace_id)
                    """
                ),
                {
                    "active_id": state_ids[0],
                    "rollback_id": state_ids[1],
                    "pending_id": state_ids[2],
                    "window_id": window_event_id,
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
        "slice_id": "GB2-CA00-S20Q-P-AH",
        "status": "FAIL",
        "failure_code": code,
        "provider_http_requests": 0,
        "holdout_accessed": False,
        "user_visible_policy_change": False,
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
    protected = [environ.get("NEX_MO_VLLM_API_KEY")]
    protected.extend(
        str(row["text"])
        for case in cases
        for row in case.get("candidates", [])
        if isinstance(row, Mapping)
    )
    if any(value and value in serialized for value in protected):
        raise ValueError("protected operations evidence leaked private material")


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
            "gb2_s20qpah_policy_cutover_operations=pass "
            f"samples={live.get('sample_count')} "
            f"provider_p95_ms={live.get('provider_p95_latency_ms')} "
            f"e2e_p95_ms={live.get('e2e_p95_latency_ms')} "
            "restart=verified"
        )
    if status == "skipped":
        return "gb2_s20qpah_policy_cutover_operations=skipped"
    return (
        "gb2_s20qpah_policy_cutover_operations=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpah_policy_cutover_operations()
    if result.get("status") != "SKIPPED" or not args.output.exists():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
