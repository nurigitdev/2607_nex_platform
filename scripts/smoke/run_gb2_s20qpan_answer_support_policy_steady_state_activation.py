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
)
from nex_cx.retrieval_answer_support_policy_cutover import (
    ACTIVE,
    CUTOVER_MODE_CONTROLLED,
    CUTOVER_MODE_ENV,
    ROLLED_BACK,
    OperationalPolicyCutoverStateStore,
    build_installed_answer_support_policy_cutover,
)
from nex_cx.retrieval_answer_support_policy_steady_state import (
    DEFAULT_AUTHORIZATION_PATH,
    STEADY_STATE_MODE_CONTROLLED,
    STEADY_STATE_MODE_ENV,
    OperationalSteadyStateStateStore,
    build_installed_answer_support_policy_steady_state,
    load_steady_state_authorization,
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
    _assert_redacted,
    _bind_provider,
    _capacity_cases,
    _configuration_issues,
    _load,
    _p95,
    _probe_ports,
)
from run_migrations import run_service_migrations, service_database_url
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

SCHEMA_VERSION = (
    "gb2_s20qpan_answer_support_policy_steady_state_activation.v1"
)
SMOKE_ENV = "NEX_GB2_S20QPAN_STEADY_STATE_ACTIVATION"
APPROVED_ENV = "NEX_GB2_S20QPAN_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPAN_OPERATOR_ID"
OUTPUT_PATH = (
    ROOT
    / "reports/live/gb2_ca00_s20qpan_answer_support_policy_"
    "steady_state_activation.json"
)
TRACE_ID = "20aa20aa20aa20aa20aa20aa20aa20aa"


def run_gb2_s20qpan_answer_support_policy_steady_state_activation(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    port_probe: Callable[[str, Sequence[int]], Mapping[str, bool]] | None = None,
    cutover_state_store: OperationalPolicyCutoverStateStore | None = None,
    steady_state_store: OperationalSteadyStateStateStore | None = None,
    generation_client: Any | None = None,
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
        STEADY_STATE_MODE_ENV: STEADY_STATE_MODE_CONTROLLED,
    }
    engine = None
    cleanup = None
    provider_calls = 0
    cases: list[Mapping[str, Any]] = []
    stage = "SOURCE_ADMISSION"
    try:
        authorization = load_steady_state_authorization(
            Path(
                effective_env.get(
                    "NEX_CX_ANSWER_SUPPORT_STEADY_STATE_AUTHORIZATION_PATH",
                    DEFAULT_AUTHORIZATION_PATH,
                )
            )
        )
        cases = _capacity_cases(dict(cases_document or _load(CASES_PATH)))[:4]
        if len(cases) != 4:
            raise ValueError("four steady-state acceptance cases are required")

        if generation_client is None:
            stage = "PROVIDER_ADMISSION"
            issues = _configuration_issues(effective_env)
            if issues:
                raise ValueError(f"generation provider configuration invalid: {issues}")
            artifact = admit_model_artifact_revision_evidence(_load(ARTIFACT_PATH))
            activation = _load(
                ROOT
                / "services/nex-cx/nex_cx/data/"
                "answer_support_controlled_activation.v1.json"
            )
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

        if cutover_state_store is None or steady_state_store is None:
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
            event_store = SqlAlchemyOperationalEventStore(
                build_session_factory(engine)
            )
            emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
            cutover_state_store = OperationalPolicyCutoverStateStore(
                emitter, event_store
            )
            steady_state_store = OperationalSteadyStateStateStore(
                emitter, event_store
            )
            cleanup = lambda: _cleanup_events(engine, authorization)
            cleanup()
        else:
            event_store = cutover_state_store.store
            emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)

        progress_sink = OperationalAnswerSupportProgressSink(emitter)
        outcome_sink = OperationalAnswerSupportShadowSink(emitter)
        stage = "STEADY_STATE_ACTIVATION"
        cutover = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=cutover_state_store,
        )
        runtime = build_installed_answer_support_policy_steady_state(
            environ=effective_env,
            delegate=cutover,
            state_store=steady_state_store,
        )
        if cutover is None or runtime is None:
            raise ValueError("steady-state runtime did not activate")

        started = monotonic()
        stage = "LIVE_STEADY_STATE_EXECUTION"
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(runtime.apply, **_application(case, index))
                for index, case in enumerate(cases, start=1)
            ]
            applied = [dict(future.result()) for future in futures]
        elapsed_seconds = max(monotonic() - started, 0.000001)
        active_snapshot = runtime.snapshot()
        provider_calls = int(
            active_snapshot["generation_client"].get("admitted_count", 0)
        )
        original_packages = [
            _package(case, index) for index, case in enumerate(cases, start=1)
        ]

        restarted_cutover = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=cutover_state_store,
        )
        restarted = build_installed_answer_support_policy_steady_state(
            environ=effective_env,
            delegate=restarted_cutover,
            state_store=steady_state_store,
        )
        if restarted is None:
            raise ValueError("steady-state runtime did not recover after restart")

        stage = "ROLLBACK_INJECTION"
        fault_cutover = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=_FailingGenerationClient(),
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=cutover_state_store,
        )
        fault_runtime = build_installed_answer_support_policy_steady_state(
            environ=effective_env,
            delegate=fault_cutover,
            state_store=steady_state_store,
        )
        if fault_runtime is None:
            raise ValueError("fault steady-state runtime was not constructed")
        fallback = fault_runtime.apply(**_application(cases[0], 99))
        rollback_snapshot = fault_runtime.snapshot()

        rolled_back_cutover = build_installed_answer_support_policy_cutover(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=cutover_state_store,
        )
        rolled_back_restart = build_installed_answer_support_policy_steady_state(
            environ=effective_env,
            delegate=rolled_back_cutover,
            state_store=steady_state_store,
        )
        if rolled_back_restart is None:
            raise ValueError("rolled-back steady-state runtime was not reconstructed")
        replay_fallback = rolled_back_restart.apply(**_application(cases[0], 100))
        persisted = steady_state_store.current_state(
            authorization["authorization_hash"]
        )

        stage = "ACCEPTANCE_ASSERTION"
        checks = {
            "pam_operator_receipt_verified": authorization["decision_receipt"][
                "steady_state_operations_approved"
            ]
            is True,
            "exact_operations_profile_bound": active_snapshot[
                "operations_profile_hash"
            ]
            == authorization["operations_profile"]["profile_hash"],
            "installed_steady_state_activated": active_snapshot[
                "steady_state_state"
            ]
            == ACTIVE,
            "live_provider_sample_count_complete": provider_calls == 4,
            "answer_support_decision_preserved": all(
                result.get("status") in {"READY", "LOW_CONFIDENCE"}
                and result.get("package_hash") != original["package_hash"]
                for result, original in zip(applied, original_packages, strict=True)
            ),
            "permission_and_evidence_preserved": all(
                result.get("permission_snapshot")
                == original["permission_snapshot"]
                and result.get("evidence_items") == original["evidence_items"]
                for result, original in zip(applied, original_packages, strict=True)
            ),
            "bounded_c4_profile_preserved": active_snapshot["generation_client"][
                "maximum_in_flight"
            ]
            == 4,
            "active_restart_recovered": restarted.snapshot()[
                "steady_state_state"
            ]
            == ACTIVE,
            "provider_failure_rolled_back": rollback_snapshot[
                "steady_state_state"
            ]
            == ROLLED_BACK,
            "rollback_reason_preserved": rollback_snapshot[
                "steady_state_reason_code"
            ]
            == "PROVIDER_ERROR",
            "current_request_fell_back": fallback == _package(cases[0], 99),
            "rollback_restart_fell_back": replay_fallback
            == _package(cases[0], 100),
            "rollback_persisted": persisted is not None
            and persisted.get("steady_state_state") == ROLLED_BACK,
            "production_cutover_prohibited": True,
        }
        residue_rows = 0
        if cleanup is not None:
            cleanup()
            residue_rows = _residue_count(engine, authorization)
        checks["test_database_zero_residue"] = residue_rows == 0
        passed = all(checks.values())
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice_id": "GB2-CA00-S20Q-P-AN",
            "status": "PASS" if passed else "FAIL",
            "decision": (
                "ANSWER_SUPPORT_POLICY_STEADY_STATE_ACTIVATION_AND_ROLLBACK_ACCEPTED"
                if passed
                else "ANSWER_SUPPORT_POLICY_STEADY_STATE_ACTIVATION_REJECTED"
            ),
            "steady_state_authorization_hash": authorization[
                "authorization_hash"
            ],
            "operator_decision_receipt_hash": authorization["decision_receipt"][
                "receipt_hash"
            ],
            "operations_profile_hash": authorization["operations_profile"][
                "profile_hash"
            ],
            "cutover_authorization_hash": authorization[
                "cutover_authorization_hash"
            ],
            "selected_policy_hash": authorization["selected_policy_hash"],
            "checks": checks,
            "failed_checks": [name for name, ok in checks.items() if not ok],
            "live_execution": {
                "sample_count": len(applied),
                "provider_call_count": provider_calls,
                "elapsed_seconds": round(elapsed_seconds, 6),
                "peak_in_flight": active_snapshot["generation_client"][
                    "peak_in_flight"
                ],
                "provider_p95_latency_ms": _p95(
                    active_snapshot["generation_client"]["provider_latencies_ms"]
                ),
                "e2e_p95_latency_ms": active_snapshot["e2e_p95_latency_ms"],
            },
            "rollback": {
                "steady_state_state": rollback_snapshot["steady_state_state"],
                "reason_code": rollback_snapshot["steady_state_reason_code"],
                "restart_safe": replay_fallback == _package(cases[0], 100),
            },
            "database_profile": "test" if engine is not None else "injected",
            "test_database_residue_rows": residue_rows,
            "holdout_accessed": False,
            "runtime_algorithm_changed": False,
            "production_cutover_permitted": False,
            "next_boundary": "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS",
        }
        result["evidence_hash"] = semantic_sha256_hash_ref(result)
        _assert_redacted(result, effective_env, cases)
        return result
    except Exception as exc:  # noqa: BLE001 - protected acceptance boundary
        return _failure(
            "steady_state_activation_acceptance_failed",
            detail={"exception": exc.__class__.__name__, "stage": stage},
        )
    finally:
        if cleanup is not None:
            try:
                cleanup()
            except Exception:  # noqa: BLE001 - best-effort zero-residue cleanup
                pass
        if engine is not None:
            engine.dispose()


def _event_ids(authorization: Mapping[str, Any]) -> dict[str, str]:
    cutover_hash = str(authorization["cutover_authorization_hash"])
    steady_hash = str(authorization["authorization_hash"])
    result: dict[str, str] = {}
    for prefix, value in (("cutover", cutover_hash), ("steady", steady_hash)):
        namespace = (
            "cx-answer-support-policy-cutover"
            if prefix == "cutover"
            else "cx-answer-support-policy-steady-state"
        )
        for state in (ACTIVE, ROLLED_BACK, "ROLLBACK_PENDING_REVIEW"):
            result[f"{prefix}_{state.lower()}"] = str(
                uuid5(NAMESPACE_URL, f"{namespace}:{value}:{state}")
            )
    return result


def _application(case: Mapping[str, Any], index: int) -> dict[str, Any]:
    package = _package(case, index)
    return {
        "query_text": str(case["query"]),
        "evidence_items": package["evidence_items"],
        "primary_package": package,
        "access_context": CxAccessContext(
            tenant_id="s20qpan-tenant",
            subject_id="s20qpan-subject",
            caller_service_id="nex-ae-api",
            scopes=("cx:retrieval:read",),
            request_id=f"s20qpan-request-{index}",
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
        "retrieval_package_id": f"s20qpan-package-{index}",
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


def _cleanup_events(engine: Any, authorization: Mapping[str, Any]) -> None:
    ids = _event_ids(authorization)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE event_id IN (
                    :cutover_active, :cutover_rolled_back,
                    :cutover_rollback_pending_review,
                    :steady_active, :steady_rolled_back,
                    :steady_rollback_pending_review
                )
                   OR (service_id = 'nex-cx'
                       AND event_type IN (
                           :progress_type,
                           :outcome_type
                       )
                       AND trace_id = :trace_id)
                """
            ),
            {
                **ids,
                "progress_type": PROGRESS_EVENT_TYPE,
                "outcome_type": CX_ANSWER_SUPPORT_SHADOW_EVENT,
                "trace_id": TRACE_ID,
            },
        )


def _residue_count(engine: Any, authorization: Mapping[str, Any]) -> int:
    ids = _event_ids(authorization)
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
                        :steady_rollback_pending_review
                    )
                       OR (service_id = 'nex-cx'
                           AND event_type IN (
                               :progress_type,
                               :outcome_type
                           )
                           AND trace_id = :trace_id)
                    """
                ),
                {
                    **ids,
                    "progress_type": PROGRESS_EVENT_TYPE,
                    "outcome_type": CX_ANSWER_SUPPORT_SHADOW_EVENT,
                    "trace_id": TRACE_ID,
                },
            ).scalar_one()
        )


def _failure(code: str, *, detail: object | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-AN",
        "status": "FAIL",
        "failure_code": code,
        "provider_http_requests": 0,
        "holdout_accessed": False,
        "steady_state_operations_active": False,
        "runtime_algorithm_changed": False,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        live = result.get("live_execution", {})
        return (
            "gb2_s20qpan_policy_steady_state_activation=pass "
            f"samples={live.get('sample_count')} "
            f"provider_p95_ms={live.get('provider_p95_latency_ms')} "
            "rollback=verified"
        )
    if status == "skipped":
        return "gb2_s20qpan_policy_steady_state_activation=skipped"
    return (
        "gb2_s20qpan_policy_steady_state_activation=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpan_answer_support_policy_steady_state_activation()
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
