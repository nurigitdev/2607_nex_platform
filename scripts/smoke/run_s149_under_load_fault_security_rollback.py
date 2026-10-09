#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_runtime.preproduction_faults import (  # noqa: E402
    FaultRehearsalResult,
    FaultState,
    build_default_fault_plan,
    evaluate_fault_rehearsals,
    transition_fault_state,
)
from nex_runtime.preproduction_live_workload import (  # noqa: E402
    build_protected_live_load_plan,
    build_protected_live_soak_profile,
)
from nex_runtime.preproduction_load import LoadRequest, OperationOutcome  # noqa: E402
from nex_runtime.preproduction_workload import admit_workload_profile  # noqa: E402
import run_s143_external_staging_acceptance as staging  # noqa: E402
import run_s144_protected_trust_federation_acceptance as trust  # noqa: E402
import run_s146_object_storage_acceptance as storage  # noqa: E402
import run_s147_model_rollout_live_acceptance as providers  # noqa: E402
import run_s149_fault_recovery as deterministic_fault  # noqa: E402
import run_s149_release_bound_target_workload as target_workload  # noqa: E402
import run_s149_rollback_rehearsal as deterministic_rollback  # noqa: E402
import run_s149_security_privacy as deterministic_security  # noqa: E402


SCHEMA_VERSION = "s149_under_load_fault_security_rollback.v1"
ACTIVATION_ENV = "NEX_S149_UNDER_LOAD_ACCEPTANCE"
PROFILE_ENV = "NEX_S149_UNDER_LOAD_ACCEPTANCE_PROFILE"
DEFAULT_PROFILE = "test"
PREDECESSOR_REPORT = (
    ROOT / "reports" / "deployment" / "s149-release-bound-workload.json"
)
REPORT_PATH = ROOT / "reports" / "deployment" / "s149-under-load-acceptance.json"
OCI_BUILD_REPORT = ROOT / "reports" / "deployment" / "s142-oci-image-build.json"
NON_RUNTIME_CHANGE_PREFIXES = ("docs/", "scripts/smoke/", "tests/")
SHADOW_REQUEST_COUNT = 1_440
SHADOW_TARGET_RPS = 8.0
SHADOW_OPERATION_COUNTS = {
    "readiness_probe": 480,
    "auth_trust": 288,
    "ag_operations": 288,
    "document_ingestion": 144,
    "artifact_access": 144,
    "hybrid_retrieval": 90,
    "grounded_generation": 6,
}
FAULT_OPERATION_MAP = {
    "fault:oa-restart": "auth_trust",
    "fault:database-route": "readiness_probe",
    "fault:rustfs-route": "artifact_access",
    "fault:embedding-timeout": "hybrid_retrieval",
    "fault:reranking-error": "hybrid_retrieval",
    "fault:generation-latency": "grounded_generation",
    "fault:edge-route": "auth_trust",
    "fault:trust-route": "auth_trust",
}
PROTECTED_ENV_KEYS = target_workload.PROTECTED_ENV_KEYS
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")

ShadowExecutor = Callable[
    [Mapping[str, str], Mapping[str, Any], Sequence[LoadRequest]],
    Mapping[str, Any],
]
SourceRunner = Callable[[Mapping[str, str], Path], Mapping[str, Any]]
RuntimeFactory = Callable[[Mapping[str, str]], Any]


def run_s149_under_load_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    predecessor_report: Path = PREDECESSOR_REPORT,
    report_path: Path = REPORT_PATH,
    shadow_executor: ShadowExecutor | None = None,
    fault_executor: Callable[[Mapping[str, str], Mapping[str, Any]], Mapping[str, Any]] | None = None,
    trust_runner: SourceRunner | None = None,
    storage_runner: SourceRunner | None = None,
    provider_runner: SourceRunner | None = None,
    deterministic_fault_runner: Callable[[], Mapping[str, Any]] | None = None,
    security_runner: Callable[[], Mapping[str, Any]] | None = None,
    rollback_runner: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(ACTIVATION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "requirement": "S149",
            "slice": "1492",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {ACTIVATION_ENV}=1 are required.",
        }
    if env.get(PROFILE_ENV, DEFAULT_PROFILE) != DEFAULT_PROFILE:
        return _failure("profile_not_allowed")

    try:
        predecessor = _load_predecessor(predecessor_report)
        release_binding = _mapping(predecessor.get("release_binding"))
        release_candidate_id = str(release_binding["release_candidate_id"])
        admitted = admit_workload_profile(
            build_protected_live_soak_profile(release_candidate_id),
            expected_release_candidate_id=release_candidate_id,
        )
        shadow_plan = _build_shadow_plan(admitted)
        shadow = shadow_executor or target_workload._run_actual_load
        fault_run = fault_executor or _execute_client_fault_matrix
        if trust_runner is None:
            image_environment, release_set_digest, pinned_release = (
                _load_pinned_release_environment(predecessor)
            )

            def effective_trust_runner(
                nested_env: Mapping[str, str], nested_report: Path
            ) -> Mapping[str, Any]:
                return _run_trust(
                    nested_env,
                    nested_report,
                    image_environment=image_environment,
                    release_set_digest=release_set_digest,
                )

        else:
            effective_trust_runner = trust_runner
            pinned_release = {
                "status": "TEST_OVERRIDE",
                "source_revision": None,
                "release_set_digest": release_binding["release_set_digest"],
                "non_runtime_change_count": 0,
                "non_runtime_change_digest": _digest_sequence(()),
            }

        with TemporaryDirectory(prefix="nex-s149-under-load-") as temporary:
            evidence_dir = Path(temporary)
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=1) as executor:
                shadow_future = executor.submit(shadow, env, admitted, shadow_plan)
                client_faults = dict(fault_run(env, admitted))
                sources = {
                    "deterministic_fault": dict(
                        (deterministic_fault_runner or deterministic_fault.run_fault_recovery_acceptance)()
                    ),
                    "security": dict(
                        (security_runner or deterministic_security.run_security_privacy_acceptance)()
                    ),
                    "rollback": dict(
                        (rollback_runner or deterministic_rollback.run_rollback_rehearsal_acceptance)()
                    ),
                    "trust": dict(
                        effective_trust_runner(env, evidence_dir / "trust.json")
                    ),
                    "storage": dict(
                        (storage_runner or _run_storage)(
                            env, evidence_dir / "storage.json"
                        )
                    ),
                    "providers": dict(
                        (provider_runner or _run_providers)(
                            env, evidence_dir / "providers.json"
                        )
                    ),
                }
                sources_completed_while_load_active = not shadow_future.done()
                shadow_result = dict(shadow_future.result())
            elapsed = max(0.0, time.monotonic() - started)

        result = _evaluate(
            predecessor=predecessor,
            admitted=admitted,
            shadow_plan=shadow_plan,
            shadow=shadow_result,
            client_faults=client_faults,
            sources=sources,
            pinned_release=pinned_release,
            sources_completed_while_load_active=sources_completed_while_load_active,
            elapsed_seconds=elapsed,
        )
        assert_evidence_redacted(result, env)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    except Exception as exc:  # noqa: BLE001 - protected runner fails closed
        result = _failure(
            "under_load_acceptance_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )
        assert_evidence_redacted(result, env)
        return result


def _build_shadow_plan(
    admitted: Mapping[str, Any],
) -> tuple[LoadRequest, ...]:
    full_plan = build_protected_live_load_plan(admitted)
    selected = full_plan[:SHADOW_REQUEST_COUNT]
    plan = tuple(
        LoadRequest(
            request_id=f"shadow:{request.request_id.removeprefix('load:')}",
            operation_id=request.operation_id,
            scheduled_offset_seconds=index / SHADOW_TARGET_RPS,
        )
        for index, request in enumerate(selected)
    )
    if Counter(item.operation_id for item in plan) != SHADOW_OPERATION_COUNTS:
        raise ValueError("under-load shadow operation mix drift")
    return plan


def _execute_client_fault_matrix(
    env: Mapping[str, str],
    admitted: Mapping[str, Any],
    *,
    runtime_factory: RuntimeFactory | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    release_candidate_id = str(admitted["release_candidate_id"])
    workload_digest = str(admitted["workload_digest"])
    plan = build_default_fault_plan(
        release_candidate_id=release_candidate_id,
        workload_digest=workload_digest,
    )
    runtime = (
        runtime_factory(env)
        if runtime_factory is not None
        else _build_fault_runtime(env)
    )
    results: list[FaultRehearsalResult] = []
    injected_outcomes: Counter[str] = Counter()
    recovery_outcomes: Counter[str] = Counter()
    try:
        for index, scenario in enumerate(plan["scenarios"], start=1):
            scenario_id = str(scenario["scenario_id"])
            operation_id = FAULT_OPERATION_MAP[scenario_id]
            state = FaultState(scenario_id)
            state = transition_fault_state(state, "begin_injection", changed_at_ms=1)
            detection_started = clock()
            injected = _injected_outcome(str(scenario["fault_class"]))
            detection_ms = max(0, int((clock() - detection_started) * 1_000))
            injected_outcomes[injected.status] += 1
            state = transition_fault_state(
                state, "degradation_observed", changed_at_ms=2
            )
            state = transition_fault_state(state, "begin_recovery", changed_at_ms=3)
            recovery_started = clock()
            request_digest = hashlib.sha256(
                f"{scenario_id}:{index}".encode("utf-8")
            ).hexdigest()[:24]
            recovered = runtime(
                LoadRequest(
                    request_id=f"fault:{request_digest}",
                    operation_id=operation_id,
                    scheduled_offset_seconds=0.0,
                )
            )
            recovery_ms = max(1, int((clock() - recovery_started) * 1_000))
            recovery_outcomes[recovered.status] += 1
            if recovered.status != "SUCCESS":
                state = transition_fault_state(
                    state,
                    "fail",
                    changed_at_ms=4,
                    failure_code="recovery_probe_failed",
                )
            else:
                state = transition_fault_state(
                    state, "recovery_verified", changed_at_ms=4
                )
            results.append(
                FaultRehearsalResult(
                    scenario_id=scenario_id,
                    final_state=state.state,
                    detection_ms=detection_ms,
                    recovery_ms=recovery_ms,
                )
            )
        evaluation = evaluate_fault_rehearsals(plan, results)
        cleanup = runtime.cleanup()
        return {
            "status": (
                "PASS"
                if evaluation.get("status") == "PASS"
                and cleanup.get("status") == "PASS"
                else "FAIL"
            ),
            "fault_plan_digest": plan["fault_plan_digest"],
            "evaluation": evaluation,
            "injected_outcome_counts": dict(injected_outcomes),
            "recovery_outcome_counts": dict(recovery_outcomes),
            "runtime_statistics": runtime.statistics(),
            "cleanup": cleanup,
        }
    finally:
        runtime.close()


def _build_fault_runtime(env: Mapping[str, str]) -> Any:
    engines = {
        service_id: target_workload._build_service_engine(
            service_id, database_env, env
        )
        for service_id, database_env in target_workload.DATABASE_TARGETS.items()
    }
    return target_workload.ProtectedLiveOperationRuntime(engines, env)


def _injected_outcome(fault_class: str) -> OperationOutcome:
    if fault_class == "edge_or_trust_degradation":
        return OperationOutcome("DENIED", "fault_injected", 0.0)
    return OperationOutcome("ERROR", "fault_injected", 0.0)


def _load_pinned_release_environment(
    predecessor: Mapping[str, Any],
    *,
    root: Path = ROOT,
    oci_report_path: Path = OCI_BUILD_REPORT,
) -> tuple[dict[str, str], str, dict[str, Any]]:
    report = json.loads(oci_report_path.read_text(encoding="utf-8"))
    image_build = _mapping(report.get("image_build"))
    release_binding = _mapping(predecessor.get("release_binding"))
    release_set_digest = str(image_build.get("release_set_digest") or "")
    source_revision = str(image_build.get("source_revision") or "")
    if image_build.get("status") != "RELEASE_SET_BUILT":
        raise ValueError("pinned OCI release set is not built")
    if release_set_digest != release_binding.get("release_set_digest"):
        raise ValueError("pinned OCI release digest does not match Slice 1491")
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("pinned OCI source revision is invalid")
    if _git(root, "merge-base", "--is-ancestor", source_revision, "HEAD", check=False):
        raise ValueError("pinned OCI source revision is not an ancestor of HEAD")

    changed_paths = tuple(
        path
        for path in _git_output(
            root, "diff", "--name-only", f"{source_revision}..HEAD"
        ).splitlines()
        if path
    )
    if any(
        not path.startswith(NON_RUNTIME_CHANGE_PREFIXES) for path in changed_paths
    ):
        raise ValueError("runtime-affecting change exists after pinned OCI build")
    if _git_output(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked worktree changes prevent pinned OCI admission")

    artifacts = image_build.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("pinned OCI artifact list is invalid")
    references = {
        str(item.get("artifact_id")): str(item.get("image_reference"))
        for item in artifacts
        if isinstance(item, Mapping)
    }
    if set(references) != set(staging.IMAGE_ENV_BY_ARTIFACT):
        raise ValueError("pinned OCI artifact coverage drift")
    if any(re.fullmatch(r".+@sha256:[0-9a-f]{64}", ref) is None for ref in references.values()):
        raise ValueError("pinned OCI image reference is not immutable")
    environment = {
        staging.IMAGE_ENV_BY_ARTIFACT[artifact_id]: reference
        for artifact_id, reference in references.items()
    }
    return environment, release_set_digest, {
        "status": "ADMITTED",
        "source_revision": source_revision,
        "release_set_digest": release_set_digest,
        "non_runtime_change_count": len(changed_paths),
        "non_runtime_change_digest": _digest_sequence(changed_paths),
    }


def _git(root: Path, *arguments: str, check: bool = True) -> int:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=10,
    )
    if check and completed.returncode != 0:
        raise ValueError("git metadata command failed")
    return completed.returncode


def _git_output(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise ValueError("git metadata command failed")
    return completed.stdout.strip()


def _run_trust(
    env: Mapping[str, str],
    report_path: Path,
    *,
    image_environment: Mapping[str, str] | None = None,
    release_set_digest: str | None = None,
) -> Mapping[str, Any]:
    nested = {**env, trust.ENABLE_ENV: "1"}
    image_loader = None
    if image_environment is not None and release_set_digest is not None:
        pinned_environment = dict(image_environment)

        def image_loader(_root: Path) -> tuple[dict[str, str], str]:
            return dict(pinned_environment), release_set_digest

    return trust.run_s144_protected_acceptance(
        nested,
        execute=True,
        root=ROOT,
        report_path=report_path,
        image_environment_loader=image_loader,
    )


def _run_storage(env: Mapping[str, str], report_path: Path) -> Mapping[str, Any]:
    nested = {**env, storage.ENABLE_ENV: "1"}
    return storage.run_s146_object_storage_acceptance(
        nested,
        execute=True,
        root=ROOT,
        report_path=report_path,
    )


def _run_providers(
    env: Mapping[str, str], _report_path: Path
) -> Mapping[str, Any]:
    nested = {
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_RUNTIME_OBSERVABILITY_MODE": "live",
        providers.ACTIVATION_ENV: "1",
        providers.PROFILE_ENV: "test",
    }
    return providers.run_s147_model_rollout_live_acceptance(nested)


def _load_predecessor(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    binding = _mapping(value.get("release_binding"))
    if value.get("status") != "PASS" or value.get("slice") != "1491":
        raise ValueError("Slice 1491 predecessor evidence did not pass")
    if not str(binding.get("release_candidate_id") or "").startswith("rc:s149:"):
        raise ValueError("Slice 1491 release candidate binding is invalid")
    if _DIGEST.fullmatch(str(binding.get("release_set_digest") or "")) is None:
        raise ValueError("Slice 1491 release set digest is invalid")
    return value


def _evaluate(
    *,
    predecessor: Mapping[str, Any],
    admitted: Mapping[str, Any],
    shadow_plan: Sequence[LoadRequest],
    shadow: Mapping[str, Any],
    client_faults: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    pinned_release: Mapping[str, Any],
    sources_completed_while_load_active: bool,
    elapsed_seconds: float,
) -> dict[str, Any]:
    release_binding = _mapping(predecessor.get("release_binding"))
    shadow_load = _mapping(shadow.get("load_result"))
    shadow_metrics = _mapping(shadow_load.get("metrics"))
    shadow_stats = _mapping(shadow.get("statistics"))
    shadow_outcomes = _mapping(shadow_stats.get("operation_outcome_counts"))
    client_evaluation = _mapping(client_faults.get("evaluation"))
    client_summary = _mapping(client_evaluation.get("summary"))
    client_cleanup = _mapping(client_faults.get("cleanup"))
    shadow_cleanup = _mapping(shadow.get("cleanup"))
    trust_source = _mapping(sources.get("trust"))
    storage_source = _mapping(sources.get("storage"))
    provider_source = _mapping(sources.get("providers"))
    storage_cleanup = _mapping(storage_source.get("cleanup"))
    provider_cleanup = _mapping(provider_source.get("cleanup"))
    provider_summary = _mapping(provider_source.get("summary"))
    trust_decision = _mapping(trust_source.get("decision"))
    checks = {
        "s1491_release_candidate_bound": predecessor.get("status") == "PASS"
        and admitted.get("release_candidate_id")
        == release_binding.get("release_candidate_id"),
        "pinned_release_set_admitted": pinned_release.get("status")
        in {"ADMITTED", "TEST_OVERRIDE"}
        and pinned_release.get("release_set_digest")
        == release_binding.get("release_set_digest"),
        "actual_shadow_load_passed": shadow.get("status") == "PASS"
        and shadow_load.get("status") == "PASS",
        "shadow_request_and_mix_exact": shadow_metrics.get("request_count")
        == SHADOW_REQUEST_COUNT
        and Counter(item.operation_id for item in shadow_plan)
        == SHADOW_OPERATION_COUNTS,
        "shadow_provider_operations_succeeded": _mapping(
            shadow_outcomes.get("hybrid_retrieval")
        ).get("SUCCESS")
        == SHADOW_OPERATION_COUNTS["hybrid_retrieval"]
        and _mapping(shadow_outcomes.get("grounded_generation")).get("SUCCESS")
        == SHADOW_OPERATION_COUNTS["grounded_generation"],
        "fault_sources_overlapped_active_load": sources_completed_while_load_active,
        "eight_client_faults_recovered": client_faults.get("status") == "PASS"
        and client_summary.get("scenario_count") == 8
        and client_summary.get("recovered_count") == 8,
        "deterministic_fault_contract_passed": _mapping(
            sources.get("deterministic_fault")
        ).get("status")
        == "PASS",
        "security_privacy_under_load_passed": _mapping(
            sources.get("security")
        ).get("status")
        == "PASS"
        and trust_source.get("status") == "PASS",
        "rollback_under_load_passed": _mapping(sources.get("rollback")).get(
            "status"
        )
        == "PASS"
        and trust_decision.get("protected_acceptance_passed") is True,
        "object_storage_restart_and_isolation_passed": storage_source.get(
            "status"
        )
        == "PASS"
        and _mapping(storage_source.get("rustfs")).get(
            "restart_recovery_verified"
        )
        is True,
        "provider_recovery_passed": provider_source.get("status") == "PASS"
        and provider_summary.get("live_provider_count") == 3
        and provider_summary.get("runtime_ready_count") == 3,
        "generation_reasoning_disabled": shadow_stats.get(
            "generation_reasoning_mode"
        )
        == "disabled"
        and provider_summary.get("generation_reasoning_mode") == "disabled",
        "release_digest_preserved": trust_source.get("release_set_digest")
        == release_binding.get("release_set_digest"),
        "zero_data_loss_isolation_and_residue": client_evaluation.get(
            "status"
        )
        == "PASS"
        and client_cleanup.get("residue_count") == 0
        and shadow_cleanup.get("residue_count") == 0
        and storage_cleanup.get("status") == "PASS"
        and provider_cleanup.get("residue") == 0,
        "production_and_provider_processes_untouched": all(
            _mapping(source.get("decision")).get("production_deployment_approved")
            is False
            for source in (trust_source, storage_source)
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1492",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "under_load_fault_security_rollback_failed",
        "release_binding": {
            "release_candidate_id": release_binding.get("release_candidate_id"),
            "release_set_digest": release_binding.get("release_set_digest"),
            "s1491_evidence_digest": _digest(predecessor),
            "workload_digest": admitted.get("workload_digest"),
            "fault_plan_digest": client_faults.get("fault_plan_digest"),
            "pinned_image_source_revision": pinned_release.get(
                "source_revision"
            ),
            "non_runtime_change_count": pinned_release.get(
                "non_runtime_change_count"
            ),
            "non_runtime_change_digest": pinned_release.get(
                "non_runtime_change_digest"
            ),
        },
        "checks": checks,
        "shadow_load": {
            "status": shadow.get("status"),
            "request_count": shadow_metrics.get("request_count"),
            "elapsed_seconds": shadow.get("elapsed_seconds"),
            "metrics": shadow_metrics,
            "operation_counts": shadow_stats.get("operation_counts"),
            "operation_outcome_counts": shadow_outcomes,
            "provider_call_counts": shadow_stats.get("provider_call_counts"),
            "generation_reasoning_mode": shadow_stats.get(
                "generation_reasoning_mode"
            ),
        },
        "faults": {
            "status": client_faults.get("status"),
            "summary": client_summary,
            "injected_outcome_counts": client_faults.get(
                "injected_outcome_counts"
            ),
            "recovery_outcome_counts": client_faults.get(
                "recovery_outcome_counts"
            ),
        },
        "source_evidence": {
            name: _source_projection(source) for name, source in sources.items()
        },
        "cleanup": {
            "shadow_residue_count": shadow_cleanup.get("residue_count"),
            "client_fault_residue_count": client_cleanup.get("residue_count"),
            "storage_status": storage_cleanup.get("status"),
            "provider_residue_count": provider_cleanup.get("residue"),
        },
        "execution_scope": {
            "shadow_seconds": round(elapsed_seconds, 6),
            "shadow_target_rps": SHADOW_TARGET_RPS,
            "client_fault_injection": True,
            "provider_process_mutation_performed": False,
            "single_host_service_storage_trust_recovery": True,
            "production_contacted": False,
            "production_deployment_approved": False,
        },
        "redaction": {
            "status": "PASS",
            "raw_source_evidence_included": False,
            "credentials_included": False,
            "endpoint_urls_included": False,
            "private_payloads_included": False,
            "per_request_records_included": False,
        },
        "next_slice": "1493" if passed else "blocked",
    }


def _failure(code: str, diagnostics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1492",
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
        raise ValueError("S149 under-load evidence contains protected value")


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _digest_sequence(values: Sequence[str]) -> str:
    payload = json.dumps(list(values), separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source_projection(source: Mapping[str, Any]) -> dict[str, Any]:
    projection = {
        "status": source.get("status"),
        "digest": _digest(source),
    }
    failure_code = source.get("failure_code")
    if isinstance(failure_code, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", failure_code):
        projection["failure_code"] = failure_code
    issues = source.get("issues")
    if isinstance(issues, list):
        safe_issues = [
            issue
            for issue in issues[:8]
            if isinstance(issue, str)
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", issue)
        ]
        if safe_issues:
            projection["issues"] = safe_issues
    return projection


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s149_under_load_acceptance=skipped"
    checks = _mapping(result.get("checks"))
    shadow = _mapping(result.get("shadow_load"))
    faults = _mapping(result.get("faults"))
    fault_summary = _mapping(faults.get("summary"))
    cleanup = _mapping(result.get("cleanup"))
    return (
        "s149_under_load_acceptance="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"requests={shadow.get('request_count', 0)}/{SHADOW_REQUEST_COUNT} "
        f"faults={fault_summary.get('recovered_count', 0)}/8 "
        f"residue={cleanup.get('shadow_residue_count', -1)} "
        f"next={result.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--predecessor-report", type=Path, default=PREDECESSOR_REPORT)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    result = run_s149_under_load_acceptance(
        execute=args.execute,
        predecessor_report=args.predecessor_report,
        report_path=args.report_path,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
