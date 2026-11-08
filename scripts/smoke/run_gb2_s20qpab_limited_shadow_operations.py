#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
    ACTIVATION_BUNDLE_PATH_ENV,
    ACTIVATION_MODE_CONTROLLED,
    ACTIVATION_MODE_ENV,
    ACTIVE,
    DEFAULT_ACTIVATION_BUNDLE_PATH,
    PROGRESS_EVENT_TYPE,
    ROLLED_BACK,
    OperationalAnswerSupportProgressSink,
    OperationalRuntimeActivationStateStore,
    build_installed_controlled_answer_support_runtime,
    load_controlled_activation_bundle,
)
from nex_cx.retrieval_answer_support_limited_operations import (
    DEFAULT_POLICY_PATH,
    EXTENDED_POLICY_SCHEMA_VERSION,
    LIMITED_OPERATIONS_ENABLED,
    LIMITED_OPERATIONS_MODE_ENV,
    LIMITED_OPERATIONS_POLICY_PATH_ENV,
    WINDOW_EVENT_TYPE,
    build_installed_limited_shadow_operations_runtime,
    load_limited_operations_policy,
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

SCHEMA_VERSION = "gb2_s20qpab_limited_shadow_operations.v1"
SMOKE_ENV = "NEX_GB2_S20QPAB_LIMITED_SHADOW_OPERATIONS"
APPROVED_ENV = "NEX_GB2_S20QPAB_OPERATOR_APPROVED"
OPERATOR_ENV = "NEX_GB2_S20QPAB_OPERATOR_ID"
OUTPUT_PATH = ROOT / "reports/live/gb2_ca00_s20qpab_limited_shadow_operations.json"
CASES_PATH = ROOT / "scripts/smoke/data/s136_answer_support_extended_shadow_v1_cases.json"
ARTIFACT_PATH = ROOT / "reports/live/gb2_s20qpi_qwen3_5_9b_revision.json"
TRACE_ID = "20ab20ab20ab20ab20ab20ab20ab20ab"


@dataclass(frozen=True)
class LimitedShadowAcceptanceProfile:
    schema_version: str
    slice_id: str
    smoke_env: str
    approved_env: str
    operator_env: str
    trace_id: str
    identity_prefix: str
    accepted_decision: str
    rejected_decision: str
    failure_code: str
    next_boundary: str


PAB_PROFILE = LimitedShadowAcceptanceProfile(
    schema_version=SCHEMA_VERSION,
    slice_id="GB2-CA00-S20Q-P-AB",
    smoke_env=SMOKE_ENV,
    approved_env=APPROVED_ENV,
    operator_env=OPERATOR_ENV,
    trace_id=TRACE_ID,
    identity_prefix="s20qpab",
    accepted_decision="LIMITED_SHADOW_RUNTIME_OPERATIONS_ACCEPTED",
    rejected_decision="LIMITED_SHADOW_RUNTIME_OPERATIONS_REJECTED",
    failure_code="limited_shadow_runtime_operations_acceptance_failed",
    next_boundary="LIMITED_SHADOW_OPERATOR_REVIEW_DECISION",
)


class _LiveGenerationClient:
    def __init__(self, environ: Mapping[str, str], requester: Callable[..., Any] | None):
        self.environ = dict(environ)
        self.requester = requester

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return remote_provider.execute_remote_generation_request(
            payload,
            request_id=request_id,
            trace_id=trace_id,
            environ=self.environ,
            requester=self.requester,
        )


def run_gb2_s20qpab_limited_shadow_operations(
    environ: Mapping[str, str] | None = None,
    *,
    requester: Callable[..., Any] | None = None,
    port_probe: Callable[[str, Sequence[int]], Mapping[str, bool]] | None = None,
    state_store: OperationalRuntimeActivationStateStore | None = None,
    generation_client: Any | None = None,
    bundle_path: Path = DEFAULT_ACTIVATION_BUNDLE_PATH,
    policy_path: Path = DEFAULT_POLICY_PATH,
    cases_document: Mapping[str, Any] | None = None,
    profile: LimitedShadowAcceptanceProfile = PAB_PROFILE,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(profile.smoke_env) != "1":
        return {
            "evidence_schema_version": profile.schema_version,
            "status": "SKIPPED",
            "skip_reason": f"{profile.smoke_env} is not enabled.",
        }
    if env.get(profile.approved_env) != "1" or not env.get(profile.operator_env):
        return _failure("operator_approval_required", profile=profile)

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_GENERATION_MAX_ATTEMPTS": "1",
        ACTIVATION_MODE_ENV: ACTIVATION_MODE_CONTROLLED,
        ACTIVATION_BUNDLE_PATH_ENV: str(bundle_path),
        LIMITED_OPERATIONS_MODE_ENV: LIMITED_OPERATIONS_ENABLED,
        LIMITED_OPERATIONS_POLICY_PATH_ENV: str(policy_path),
    }
    engine = None
    cleanup: Callable[[], None] | None = None
    provider_calls = 0
    cases: list[Mapping[str, Any]] = []
    try:
        bundle = load_controlled_activation_bundle(bundle_path)
        policy = load_limited_operations_policy(policy_path)
        if policy["activation_bundle_hash"] != bundle["bundle_hash"]:
            raise ValueError("limited operations policy is bound to another bundle")
        cases_value = dict(cases_document or _load(CASES_PATH))
        cases = _capacity_cases(cases_value)[: policy["maximum_provider_samples"]]
        if len(cases) != policy["maximum_provider_samples"]:
            raise ValueError("limited operations case count is incomplete")

        if generation_client is None:
            issues = _configuration_issues(effective_env)
            if issues:
                raise ValueError(f"generation provider configuration invalid: {issues}")
            artifact = admit_model_artifact_revision_evidence(_load(ARTIFACT_PATH))
            binding = bundle["readiness_manifest"]["candidate_profile"][
                "provider_binding"
            ]
            _bind_provider(effective_env, binding, artifact)
            config = remote_provider.build_remote_generation_execution_config(
                effective_env
            )
            parsed = urlparse(config.url)
            if not parsed.hostname or not parsed.port:
                raise ValueError("generation provider route is incomplete")
            reachable = dict((port_probe or _probe_ports)(parsed.hostname, [parsed.port]))
            if reachable != {str(parsed.port): True}:
                raise ValueError("generation provider is unreachable")
            generation_client = _LiveGenerationClient(effective_env, requester)

        if state_store is None:
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
                bundle["bundle_hash"],
                profile=profile,
                window_id=policy["window_id"],
            )
            cleanup()
        else:
            event_store = state_store.store
        emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
        state_store = state_store or OperationalRuntimeActivationStateStore(
            emitter=emitter,
            store=event_store,
        )
        progress_sink = OperationalAnswerSupportProgressSink(emitter)
        outcome_sink = OperationalAnswerSupportShadowSink(emitter)
        controlled = build_installed_controlled_answer_support_runtime(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=state_store,
        )
        limited = build_installed_limited_shadow_operations_runtime(
            environ=effective_env,
            controlled_runtime=controlled,
            store=event_store,
            outcome_sink=outcome_sink,
        )
        if controlled is None or limited is None:
            raise ValueError("limited shadow runtime did not activate")

        started = monotonic()
        observations: list[dict[str, Any]] = []
        for wave_start in range(0, len(cases), 4):
            wave = cases[wave_start : wave_start + 4]
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(
                        _observe,
                        limited,
                        case,
                        wave_start + index,
                        profile,
                    )
                    for index, case in enumerate(wave, start=1)
                ]
                observations.extend(future.result() for future in futures)
        elapsed_seconds = max(monotonic() - started, 0.000001)
        provider_calls = sum(item.get("provider_called") is True for item in observations)
        capped = limited.observe(
            **_observation(cases[0], len(cases) + 1, profile=profile)
        )
        snapshot = limited.snapshot()

        restarted_controlled = build_installed_controlled_answer_support_runtime(
            environ=effective_env,
            generation_client=generation_client,
            progress_sink=progress_sink,
            outcome_sink=outcome_sink,
            state_store=state_store,
        )
        restarted = build_installed_limited_shadow_operations_runtime(
            environ=effective_env,
            controlled_runtime=restarted_controlled,
            store=event_store,
            outcome_sink=outcome_sink,
        )
        if restarted is None:
            raise ValueError("limited runtime did not recover after restart")
        restart_capped = restarted.observe(
            **_observation(cases[1], len(cases) + 2, profile=profile)
        )
        restart_snapshot = restarted.snapshot()
        checks = {
            "activation_bundle_binding_verified": True,
            "limited_policy_integrity_verified": True,
            "exact_provider_sample_cap_observed": provider_calls
            == policy["maximum_provider_samples"],
            "all_limited_samples_observed": all(
                item.get("status") == "OBSERVED" for item in observations
            ),
            (
                "post_cap_request_provider_blocked"
                if policy["policy_schema_version"]
                == EXTENDED_POLICY_SCHEMA_VERSION
                else "thirteenth_request_provider_blocked"
            ): capped.get("skip_reason") == "LIMITED_WINDOW_COMPLETE"
            and capped.get("provider_called") is False,
            "restart_sample_cap_preserved": restart_capped.get("skip_reason")
            == "LIMITED_WINDOW_COMPLETE"
            and restart_snapshot["window"]["provider_sample_count"]
            == policy["maximum_provider_samples"],
            "operator_review_required": snapshot["operations_status"]
            == "REVIEW_REQUIRED",
            "bounded_c4_profile_preserved": snapshot["runtime"]["peak_in_flight"]
            <= 4,
            "primary_policy_unchanged": snapshot["safety"]["authoritative_policy"]
            == "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
            "raw_text_projection_prohibited": snapshot["source"]["raw_text_included"]
            is False,
            "production_cutover_prohibited": snapshot["safety"][
                "production_cutover_permitted"
            ]
            is False,
        }
        if policy["policy_schema_version"] == EXTENDED_POLICY_SCHEMA_VERSION:
            authorization = policy["continuation_authorization"]
            window_events = event_store.list_events(
                service_id="nex-cx",
                event_type=WINDOW_EVENT_TYPE,
                limit=policy["maximum_event_scan"],
            )
            checks.update(
                {
                    "fresh_window_marker_verified": _window_marker_verified(
                        window_events, policy
                    ),
                    "operator_continuation_bound": (
                        authorization["decision"]
                        == "CONTINUE_LIMITED_SHADOW_OBSERVATION_APPROVED"
                    ),
                    "zero_provider_failures": snapshot["progress"]["failed_count"]
                    == policy["operational_slo"]["maximum_provider_failures"],
                    "provider_p95_slo_preserved": snapshot["progress"][
                        "provider_p95_latency_ms"
                    ]
                    <= policy["operational_slo"][
                        "maximum_provider_p95_latency_ms"
                    ],
                    "e2e_p95_slo_preserved": snapshot["outcomes"][
                        "e2e_p95_latency_ms"
                    ]
                    <= policy["operational_slo"][
                        "maximum_e2e_p95_latency_ms"
                    ],
                }
            )
        passed = all(checks.values())
        result = {
            "evidence_schema_version": profile.schema_version,
            "slice_id": profile.slice_id,
            "status": "PASS" if passed else "FAIL",
            "decision": profile.accepted_decision if passed else profile.rejected_decision,
            "activation_bundle_hash": bundle["bundle_hash"],
            "operations_policy_hash": policy["policy_hash"],
            "window_id": policy["window_id"],
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "live_execution": {
                "wave_count": (len(cases) + 3) // 4,
                "wave_concurrency": 4,
                "sample_count": len(observations),
                "provider_call_count": provider_calls,
                "elapsed_seconds": round(elapsed_seconds, 6),
                "provider_p95_latency_ms": snapshot["progress"][
                    "provider_p95_latency_ms"
                ],
                "e2e_p95_latency_ms": snapshot["outcomes"][
                    "e2e_p95_latency_ms"
                ],
                "peak_in_flight": snapshot["runtime"]["peak_in_flight"],
            },
            "window": snapshot["window"],
            "operations_status": snapshot["operations_status"],
            "database_profile": "test" if engine is not None else "injected",
            "holdout_accessed": False,
            "user_visible_decision_change": False,
            "production_cutover_permitted": False,
            "next_boundary": profile.next_boundary,
        }
        if policy["policy_schema_version"] == EXTENDED_POLICY_SCHEMA_VERSION:
            result["continuation_authorization"] = {
                key: policy["continuation_authorization"][key]
                for key in (
                    "review_design_hash",
                    "operator_decision_hash",
                    "decision_receipt_hash",
                    "source_evidence_hash",
                    "source_report_document_hash",
                )
            }
        if cleanup is not None:
            cleanup()
            result["test_database_residue_rows"] = _count_events(
                engine,
                profile=profile,
                window_id=policy["window_id"],
            )
        result["evidence_hash"] = semantic_sha256_hash_ref(result)
        _assert_redacted(result, effective_env, cases)
        return result
    except Exception as exc:  # noqa: BLE001 - protected acceptance boundary
        result = _failure(
            profile.failure_code,
            detail={"exception": exc.__class__.__name__},
            profile=profile,
        )
        result["provider_http_requests"] = provider_calls
        _assert_redacted(result, effective_env, cases)
        return result
    finally:
        if cleanup is not None:
            cleanup()
        if engine is not None:
            engine.dispose()


def _observe(
    runtime: Any,
    case: Mapping[str, Any],
    index: int,
    profile: LimitedShadowAcceptanceProfile = PAB_PROFILE,
) -> dict[str, Any]:
    return dict(runtime.observe(**_observation(case, index, profile=profile)))


def _observation(
    case: Mapping[str, Any],
    index: int,
    *,
    profile: LimitedShadowAcceptanceProfile = PAB_PROFILE,
) -> dict[str, Any]:
    return {
        "query_text": str(case["query"]),
        "evidence_items": [
            {
                "evidence_id": str(row["candidate_id"]),
                "text": str(row["text"]),
                "permission_result": {"visible": True},
            }
            for row in case["candidates"]
        ],
        "primary_package": {
            "retrieval_package_id": f"{profile.identity_prefix}-package-{index}",
            "status": "READY",
            "purpose": "grounded_answer",
        },
        "access_context": CxAccessContext(
            tenant_id=f"{profile.identity_prefix}-tenant",
            subject_id=f"{profile.identity_prefix}-subject",
            caller_service_id="nex-ae-api",
            scopes=("cx:retrieval:read",),
            request_id=f"{profile.identity_prefix}-request-{index}",
            trace_id=profile.trace_id,
        ),
    }


def _cleanup_events(
    engine: Any,
    bundle_hash: str,
    *,
    profile: LimitedShadowAcceptanceProfile = PAB_PROFILE,
    window_id: str | None = None,
) -> None:
    state_ids = [
        str(uuid5(NAMESPACE_URL, f"cx-answer-support-activation:{bundle_hash}:{state}"))
        for state in (ACTIVE, ROLLED_BACK)
    ]
    window_event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"cx-answer-support-shadow-window:{window_id or 'not-applicable'}",
        )
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM service_operational_events
                WHERE event_id IN (:active_id, :rollback_id, :window_event_id)
                   OR (service_id = 'nex-cx'
                       AND event_type IN (:progress_type, :outcome_type)
                       AND trace_id = :trace_id)
                """
            ),
            {
                "active_id": state_ids[0],
                "rollback_id": state_ids[1],
                "window_event_id": window_event_id,
                "progress_type": PROGRESS_EVENT_TYPE,
                "outcome_type": CX_ANSWER_SUPPORT_SHADOW_EVENT,
                "trace_id": profile.trace_id,
            },
        )


def _count_events(
    engine: Any,
    *,
    profile: LimitedShadowAcceptanceProfile = PAB_PROFILE,
    window_id: str | None = None,
) -> int:
    window_event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"cx-answer-support-shadow-window:{window_id or 'not-applicable'}",
        )
    )
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM service_operational_events
                    WHERE service_id = 'nex-cx'
                      AND (trace_id = :trace_id OR event_id = :window_event_id)
                    """
                ),
                {
                    "trace_id": profile.trace_id,
                    "window_event_id": window_event_id,
                },
            ).scalar_one()
        )


def _failure(
    code: str,
    *,
    detail: object | None = None,
    profile: LimitedShadowAcceptanceProfile = PAB_PROFILE,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": profile.schema_version,
        "slice_id": profile.slice_id,
        "status": "FAIL",
        "failure_code": code,
        "provider_http_requests": 0,
        "holdout_accessed": False,
        "user_visible_decision_change": False,
        "production_cutover_permitted": False,
    }
    if detail is not None:
        result["failure_detail"] = detail
    return result


def _window_marker_verified(
    events: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> bool:
    authorization = policy["continuation_authorization"]
    return any(
        isinstance(event.get("details"), Mapping)
        and event["details"].get("window_state") == "OPEN"
        and event["details"].get("window_id") == policy["window_id"]
        and event["details"].get("policy_hash") == policy["policy_hash"]
        and event["details"].get("decision_receipt_hash")
        == authorization["decision_receipt_hash"]
        for event in events
    )


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
        raise ValueError("limited operations evidence leaked private material")


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
            "gb2_s20qpab_limited_shadow_operations=pass "
            f"samples={live.get('sample_count')} "
            f"provider_p95_ms={live.get('provider_p95_latency_ms')} "
            "restart_cap=verified"
        )
    if status == "skipped":
        return "gb2_s20qpab_limited_shadow_operations=skipped"
    return (
        "gb2_s20qpab_limited_shadow_operations=fail "
        f"reason={result.get('failure_code', 'checks_failed')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qpab_limited_shadow_operations()
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
