#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_mo.remote_provider import (  # noqa: E402
    execute_remote_embedding_request,
    execute_remote_generation_request,
    execute_remote_rerank_request,
)
from nex_runtime.database import (  # noqa: E402
    build_engine,
    database_pool_settings,
)
from nex_runtime.preproduction_live_workload import (  # noqa: E402
    PROTECTED_LIVE_OPERATION_COUNTS,
    PROTECTED_LIVE_PROVIDER_CALL_CAPS,
    build_protected_live_load_plan,
    build_protected_live_soak_profile,
    protected_live_plan_summary,
)
from nex_runtime.preproduction_load import (  # noqa: E402
    LoadRequest,
    OperationOutcome,
    run_bounded_load,
)
from nex_runtime.preproduction_workload import admit_workload_profile  # noqa: E402
import run_platform_authenticated_ingestion_postgres_smoke as ingestion  # noqa: E402
import run_platform_release_candidate_live_providers as live_providers  # noqa: E402


SCHEMA_VERSION = "s149_release_bound_target_workload.v1"
PROTECTED_GENERATION_REASONING_MODE = "disabled"
ACTIVATION_ENV = "NEX_S149_RELEASE_BOUND_TARGET_WORKLOAD"
PROFILE_ENV = "NEX_S149_RELEASE_BOUND_TARGET_WORKLOAD_PROFILE"
DEFAULT_PROFILE = "test"
PREDECESSOR_REPORT = (
    ROOT / "reports" / "deployment" / "s149-single-host-live-acceptance.json"
)
REPORT_PATH = ROOT / "reports" / "deployment" / "s149-release-bound-workload.json"
DATABASE_TARGETS = {
    "nex-oa": "NEX_OA_TEST_DATABASE_URL",
    "nex-ae-api": "NEX_AE_TEST_DATABASE_URL",
    "nex-cx": "NEX_CX_TEST_DATABASE_URL",
    "nex-mo": "NEX_MO_TEST_DATABASE_URL",
    "nex-ag": "NEX_AG_TEST_DATABASE_URL",
}
PROTECTED_ENV_KEYS = (
    *DATABASE_TARGETS.values(),
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_MODELS_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")

SentinelRunner = Callable[[Mapping[str, str], str], Mapping[str, Any]]
LoadExecutor = Callable[
    [Mapping[str, str], Mapping[str, Any], Sequence[LoadRequest]],
    Mapping[str, Any],
]
EngineBuilder = Callable[[str, str, Mapping[str, str]], Engine]


class ProtectedLiveOperationRuntime:
    def __init__(
        self,
        engines: Mapping[str, Engine],
        environ: Mapping[str, str],
        *,
        embedding_executor: Callable[..., Mapping[str, Any]] = execute_remote_embedding_request,
        reranker_executor: Callable[..., Mapping[str, Any]] = execute_remote_rerank_request,
        generation_executor: Callable[..., Mapping[str, Any]] = execute_remote_generation_request,
        run_token: str | None = None,
    ) -> None:
        self._engines = dict(engines)
        self._environ = dict(environ)
        self._embedding_executor = embedding_executor
        self._reranker_executor = reranker_executor
        self._generation_executor = generation_executor
        self._run_token = run_token or secrets.token_hex(6)
        self._lock = threading.Lock()
        self._operation_counts: Counter[str] = Counter()
        self._operation_outcomes: Counter[tuple[str, str]] = Counter()
        self._database_counts: Counter[str] = Counter()
        self._provider_counts: Counter[str] = Counter()

    def __call__(self, request: LoadRequest) -> OperationOutcome:
        with self._lock:
            self._operation_counts[request.operation_id] += 1
        try:
            outcome = self._dispatch(request)
        except Exception:  # noqa: BLE001 - protected evidence stays metadata-only
            outcome = OperationOutcome(
                status="ERROR",
                reason_code=(
                    "provider_error"
                    if request.operation_id
                    in {"hybrid_retrieval", "grounded_generation"}
                    else "database_error"
                ),
                saturation_ratio=0.0,
            )
        with self._lock:
            self._operation_outcomes[(request.operation_id, outcome.status)] += 1
        return outcome

    def _dispatch(self, request: LoadRequest) -> OperationOutcome:
        if request.operation_id == "auth_trust":
            return self._read_probe("nex-oa", "SELECT count(*) FROM oa_subjects")
        if request.operation_id == "document_ingestion":
            return self._ingestion_persistence_probe(request)
        if request.operation_id == "artifact_access":
            return self._read_probe(
                "nex-ae-api", "SELECT count(*) FROM ae_artifacts"
            )
        if request.operation_id == "ag_operations":
            return self._read_probe("nex-ag", "SELECT count(*) FROM ag_alerts")
        if request.operation_id == "readiness_probe":
            services = tuple(DATABASE_TARGETS)
            service_id = services[int(request.request_id[-2:], 16) % len(services)]
            return self._read_probe(service_id, "SELECT 1")
        if request.operation_id == "hybrid_retrieval":
            return self._hybrid_provider_probe()
        if request.operation_id == "grounded_generation":
            return self._generation_provider_probe(request)
        raise ValueError("unsupported protected-live operation")

    def _read_probe(self, service_id: str, statement: str) -> OperationOutcome:
        engine = self._engines[service_id]
        with engine.connect() as connection:
            connection.execute(text(statement)).scalar()
            saturation = _pool_saturation(engine)
        with self._lock:
            self._database_counts[service_id] += 1
        return OperationOutcome("SUCCESS", "completed", saturation)

    def _ingestion_persistence_probe(self, request: LoadRequest) -> OperationOutcome:
        engine = self._engines["nex-cx"]
        event_id = f"s149-load:{self._run_token}:{request.request_id.removeprefix('load:')}"
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO service_operational_events (
                        event_id, service_id, event_type, severity,
                        request_id, message
                    ) VALUES (
                        :event_id, 'nex-cx', 's149.load.document_ingestion_probe',
                        'INFO', :request_id, 'S149 document ingestion persistence probe'
                    )
                    """
                ),
                {"event_id": event_id, "request_id": request.request_id},
            )
            connection.execute(text("SELECT count(*) FROM cx_ingest_runs")).scalar()
            saturation = _pool_saturation(engine)
        with self._lock:
            self._database_counts["nex-cx"] += 1
        return OperationOutcome(
            "SUCCESS",
            "completed",
            saturation,
            hashlib.sha256(event_id.encode("utf-8")).hexdigest(),
        )

    def _hybrid_provider_probe(self) -> OperationOutcome:
        query = "S149 permission filtered retrieval health probe"
        documents = (
            "Authorized staging evidence for the release candidate.",
            "Unrelated synthetic control document.",
        )
        with self._lock:
            self._provider_counts["embedding"] += 1
        self._embedding_executor(
            {"alias": "embedding-default", "inputs": [query, *documents]},
            environ=self._environ,
        )
        with self._lock:
            self._provider_counts["reranking"] += 1
        self._reranker_executor(
            {
                "alias": "reranker-default",
                "query": query,
                "documents": list(documents),
                "top_n": 2,
            },
            environ=self._environ,
        )
        return OperationOutcome("SUCCESS", "completed", 0.0)

    def _generation_provider_probe(self, request: LoadRequest) -> OperationOutcome:
        with self._lock:
            self._provider_counts["generation"] += 1
        self._generation_executor(
            {
                "alias": "general-llm-default",
                "provider_capability": "generation",
                "messages": [
                    {
                        "role": "system",
                        "content": "Reply with only the word OK.",
                    },
                    {"role": "user", "content": "S149 health probe"},
                ],
                "temperature": 0.0,
                "max_output_tokens": 32,
                "stream": False,
                "reasoning_mode": PROTECTED_GENERATION_REASONING_MODE,
            },
            request_id=request.request_id,
            trace_id=hashlib.sha256(request.request_id.encode()).hexdigest()[:32],
            environ=self._environ,
        )
        return OperationOutcome("SUCCESS", "completed", 0.0)

    def cleanup(self) -> dict[str, Any]:
        engine = self._engines["nex-cx"]
        pattern = f"s149-load:{self._run_token}:%"
        with engine.begin() as connection:
            deleted = connection.execute(
                text(
                    "DELETE FROM service_operational_events "
                    "WHERE event_id LIKE :pattern"
                ),
                {"pattern": pattern},
            ).rowcount
            residue = connection.execute(
                text(
                    "SELECT count(*) FROM service_operational_events "
                    "WHERE event_id LIKE :pattern"
                ),
                {"pattern": pattern},
            ).scalar_one()
        return {
            "status": "PASS" if residue == 0 else "FAIL",
            "deleted_row_count": max(0, int(deleted or 0)),
            "residue_count": int(residue),
        }

    def statistics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "operation_counts": dict(self._operation_counts),
                "operation_outcome_counts": {
                    operation_id: {
                        status: self._operation_outcomes[(operation_id, status)]
                        for status in ("SUCCESS", "ERROR", "TIMEOUT", "DENIED")
                    }
                    for operation_id in self._operation_counts
                },
                "database_call_counts": dict(self._database_counts),
                "provider_call_counts": dict(self._provider_counts),
                "generation_reasoning_mode": PROTECTED_GENERATION_REASONING_MODE,
            }

    def close(self) -> None:
        for engine in self._engines.values():
            engine.dispose()


def run_s149_release_bound_target_workload(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    predecessor_report: Path = PREDECESSOR_REPORT,
    report_path: Path = REPORT_PATH,
    sentinel_runner: SentinelRunner | None = None,
    load_executor: LoadExecutor | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(ACTIVATION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "requirement": "S149",
            "slice": "1491",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {ACTIVATION_ENV}=1 are required.",
        }
    if env.get(PROFILE_ENV, DEFAULT_PROFILE) != DEFAULT_PROFILE:
        return _failure("profile_not_allowed")

    try:
        predecessor = _load_predecessor(predecessor_report)
        release_binding = dict(predecessor["release_binding"])
        release_candidate_id = str(release_binding["release_candidate_id"])
        profile = build_protected_live_soak_profile(release_candidate_id)
        admitted = admit_workload_profile(
            profile,
            expected_release_candidate_id=release_candidate_id,
        )
        plan = build_protected_live_load_plan(admitted)
        plan_summary = protected_live_plan_summary(plan)
        if plan_summary["status"] != "PASS":
            return _failure("protected_live_plan_invalid")

        sentinel = sentinel_runner or _run_journey_sentinel
        pre_sentinel = dict(sentinel(env, "pre"))
        if pre_sentinel.get("status") != "PASS":
            return _failure("pre_workload_sentinel_failed")

        executor = load_executor or _run_actual_load
        workload = dict(executor(env, admitted, plan))
        post_sentinel = dict(sentinel(env, "post"))
        result = _evaluate(
            predecessor=predecessor,
            admitted=admitted,
            plan_summary=plan_summary,
            pre_sentinel=pre_sentinel,
            workload=workload,
            post_sentinel=post_sentinel,
        )
        assert_evidence_redacted(result, env)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    except Exception as exc:  # noqa: BLE001 - protected acceptance fails closed
        result = _failure(
            "release_bound_target_workload_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )
        assert_evidence_redacted(result, env)
        return result


def _run_actual_load(
    env: Mapping[str, str],
    admitted: Mapping[str, Any],
    plan: Sequence[LoadRequest],
    *,
    engine_builder: EngineBuilder | None = None,
) -> dict[str, Any]:
    builder = engine_builder or _build_service_engine
    engines = {
        service_id: builder(service_id, database_env, env)
        for service_id, database_env in DATABASE_TARGETS.items()
    }
    runtime = ProtectedLiveOperationRuntime(engines, env)
    started = time.monotonic()
    try:
        load_result = run_bounded_load(admitted, plan, runtime, paced=True)
    finally:
        elapsed = max(0.0, time.monotonic() - started)
        cleanup = runtime.cleanup()
        statistics = runtime.statistics()
        runtime.close()
    planned_seconds = float(plan[-1].scheduled_offset_seconds) if plan else 0.0
    return {
        "status": (
            "PASS"
            if load_result.get("status") == "PASS"
            and cleanup.get("status") == "PASS"
            else "FAIL"
        ),
        "load_result": load_result,
        "elapsed_seconds": round(elapsed, 6),
        "planned_seconds": planned_seconds,
        "measurement_window_reached": elapsed >= planned_seconds,
        "statistics": statistics,
        "cleanup": cleanup,
    }


def _build_service_engine(
    service_id: str,
    database_env: str,
    env: Mapping[str, str],
) -> Engine:
    database_url = str(env.get(database_env) or "")
    if not database_url:
        raise ValueError(f"missing protected database binding: {database_env}")
    settings = database_pool_settings(service_id, workload="worker", environ=env)
    return build_engine(database_url, pool_settings=settings)


def _run_journey_sentinel(
    env: Mapping[str, str], phase: str
) -> Mapping[str, Any]:
    ingestion_result = dict(
        ingestion.run_smoke({**env, ingestion.SMOKE_ENV: "1"})
    )
    if ingestion_result.get("status") != "PASS":
        return {
            "status": "FAIL",
            "phase": phase,
            "failure_code": "authenticated_ingestion_sentinel_failed",
        }
    provider_result = dict(
        live_providers.run_platform_release_candidate_live_providers(
            {**env, live_providers.ENABLE_ENV: "1", "NEX_MO_PROVIDER_MODE": "live"}
        )
    )
    passed = provider_result.get("status") == "PASS"
    return {
        "status": "PASS" if passed else "FAIL",
        "phase": phase,
        "failure_code": None if passed else "grounded_provider_sentinel_failed",
        "authenticated_ingestion_evidence_digest": _digest(ingestion_result),
        "grounded_provider_evidence_digest": _digest(provider_result),
    }


def _load_predecessor(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    binding = _mapping(value.get("release_binding"))
    if value.get("status") != "PASS":
        raise ValueError("S1490 predecessor evidence did not pass")
    if not str(binding.get("release_candidate_id") or "").startswith("rc:s149:"):
        raise ValueError("S1490 release candidate binding is invalid")
    if _DIGEST.fullmatch(str(binding.get("release_set_digest") or "")) is None:
        raise ValueError("S1490 release set digest is invalid")
    return value


def _evaluate(
    *,
    predecessor: Mapping[str, Any],
    admitted: Mapping[str, Any],
    plan_summary: Mapping[str, Any],
    pre_sentinel: Mapping[str, Any],
    workload: Mapping[str, Any],
    post_sentinel: Mapping[str, Any],
) -> dict[str, Any]:
    release_binding = _mapping(predecessor.get("release_binding"))
    load_result = _mapping(workload.get("load_result"))
    metrics = _mapping(load_result.get("metrics"))
    statistics = _mapping(workload.get("statistics"))
    operation_counts = _int_mapping(statistics.get("operation_counts"))
    operation_outcomes = {
        name: _int_mapping(value)
        for name, value in _mapping(
            statistics.get("operation_outcome_counts")
        ).items()
    }
    provider_counts = _int_mapping(statistics.get("provider_call_counts"))
    cleanup = _mapping(workload.get("cleanup"))
    checks = {
        "s1490_release_candidate_bound": predecessor.get("status") == "PASS"
        and _DIGEST.fullmatch(str(release_binding.get("release_set_digest") or ""))
        is not None,
        "protected_live_plan_admitted": plan_summary.get("status") == "PASS"
        and admitted.get("admission") == "ADMITTED",
        "pre_workload_journeys_passed": pre_sentinel.get("status") == "PASS",
        "target_workload_passed": workload.get("status") == "PASS"
        and load_result.get("status") == "PASS",
        "target_request_count_exact": metrics.get("request_count") == 7_200,
        "operation_mix_exact": operation_counts == PROTECTED_LIVE_OPERATION_COUNTS,
        "provider_call_caps_respected": provider_counts
        == PROTECTED_LIVE_PROVIDER_CALL_CAPS,
        "provider_operations_all_succeeded": (
            _mapping(operation_outcomes.get("hybrid_retrieval")).get("SUCCESS")
            == PROTECTED_LIVE_OPERATION_COUNTS["hybrid_retrieval"]
            and _mapping(operation_outcomes.get("grounded_generation")).get(
                "SUCCESS"
            )
            == PROTECTED_LIVE_OPERATION_COUNTS["grounded_generation"]
        ),
        "measurement_window_reached": workload.get("measurement_window_reached")
        is True,
        "zero_isolation_violations": metrics.get("isolation_violation_count") == 0,
        "zero_duplicate_side_effects": metrics.get("duplicate_side_effect_count") == 0,
        "zero_rehearsal_residue": cleanup.get("status") == "PASS"
        and cleanup.get("residue_count") == 0,
        "post_workload_journeys_passed": post_sentinel.get("status") == "PASS",
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1491",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "release_bound_target_workload_failed",
        "release_binding": {
            "release_candidate_id": release_binding.get("release_candidate_id"),
            "release_set_digest": release_binding.get("release_set_digest"),
            "s1490_evidence_digest": _digest(predecessor),
            "workload_digest": admitted.get("workload_digest"),
        },
        "checks": checks,
        "profile": {
            "profile_id": admitted.get("profile_id"),
            "workload_class": admitted.get("workload_class"),
            "concurrency": admitted.get("concurrency"),
            "target_rps": admitted.get("target_rps"),
            "measurement_seconds": admitted.get("measurement_seconds"),
            "request_count": plan_summary.get("request_count"),
            "operation_counts": plan_summary.get("operation_counts"),
            "provider_call_caps": plan_summary.get("provider_call_caps"),
        },
        "journey_sentinels": {
            "pre": _sentinel_projection(pre_sentinel),
            "post": _sentinel_projection(post_sentinel),
        },
        "workload": {
            "status": workload.get("status"),
            "elapsed_seconds": workload.get("elapsed_seconds"),
            "planned_seconds": workload.get("planned_seconds"),
            "metrics": metrics,
            "outcome_counts": load_result.get("outcome_counts"),
            "database_call_counts": statistics.get("database_call_counts"),
            "provider_call_counts": provider_counts,
            "operation_outcome_counts": operation_outcomes,
        },
        "cleanup": {
            "status": cleanup.get("status"),
            "deleted_row_count": cleanup.get("deleted_row_count"),
            "residue_count": cleanup.get("residue_count"),
        },
        "execution_scope": {
            "topology": "single_host_docker_compose_release_candidate",
            "postgres": "actual_five_test_databases",
            "providers": "actual_remote_embedding_reranking_generation",
            "business_journeys": "actual_pre_and_post_sentinels",
            "load_probes": "actual_database_and_provider_boundaries",
            "production_contacted": False,
            "production_capacity_claimed": False,
        },
        "redaction": {
            "status": "PASS",
            "credentials_included": False,
            "endpoint_urls_included": False,
            "private_payloads_included": False,
            "per_request_records_included": False,
        },
        "next_slice": "1492" if passed else "blocked",
    }


def _sentinel_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "status",
            "phase",
            "failure_code",
            "authenticated_ingestion_evidence_digest",
            "grounded_provider_evidence_digest",
        )
        if key in value
    }


def _pool_saturation(engine: Engine) -> float:
    size = getattr(engine.pool, "size", lambda: 0)()
    checked_out = getattr(engine.pool, "checkedout", lambda: 0)()
    if not isinstance(size, int) or size <= 0:
        return 0.0
    return min(1.0, max(0.0, float(checked_out) / size))


def _failure(code: str, diagnostics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1491",
        "status": "FAIL",
        "failure_code": code,
        "next_slice": "blocked",
    }
    if diagnostics:
        result["diagnostics"] = dict(diagnostics)
    return result


def assert_evidence_redacted(
    evidence: Mapping[str, Any], environ: Mapping[str, str]
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    protected = {
        str(environ.get(key) or "").strip()
        for key in PROTECTED_ENV_KEYS
        if str(environ.get(key) or "").strip()
    }
    if any(value in serialized for value in protected):
        raise ValueError("S149 target workload evidence contains protected value")


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int_mapping(value: object) -> dict[str, int]:
    return {
        str(key): item
        for key, item in _mapping(value).items()
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s149_release_bound_target_workload=skipped"
    checks = _mapping(result.get("checks"))
    workload = _mapping(result.get("workload"))
    metrics = _mapping(workload.get("metrics"))
    return (
        "s149_release_bound_target_workload="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"requests={metrics.get('request_count', 0)}/7200 "
        f"residue={_mapping(result.get('cleanup')).get('residue_count', -1)} "
        f"next={result.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--predecessor-report", type=Path, default=PREDECESSOR_REPORT)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    result = run_s149_release_bound_target_workload(
        execute=args.execute,
        predecessor_report=args.predecessor_report,
        report_path=args.report_path,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
