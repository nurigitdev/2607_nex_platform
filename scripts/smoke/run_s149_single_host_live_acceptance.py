#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "scripts" / "smoke"):
    sys.path.insert(0, str(path))

from run_s143_external_staging_acceptance import (
    run_s143_external_staging_acceptance,
)
from run_s146_object_storage_acceptance import (
    run_s146_object_storage_acceptance,
)
from run_s147_model_rollout_live_acceptance import (
    run_s147_model_rollout_live_acceptance,
)

SCHEMA_VERSION = "s149_single_host_live_acceptance.v1"
ACTIVATION_ENV = "NEX_S149_SINGLE_HOST_LIVE_ACCEPTANCE"
PROFILE_ENV = "NEX_S149_SINGLE_HOST_LIVE_ACCEPTANCE_PROFILE"
DEFAULT_PROFILE = "test"
REPORT_PATH = ROOT / "reports" / "deployment" / "s149-single-host-live-acceptance.json"
DATABASE_ENV_KEYS = tuple(
    f"NEX_{service}_TEST_DATABASE_URL" for service in ("OA", "AE", "CX", "MO", "AG")
)
PROTECTED_ENV_KEYS = (
    *DATABASE_ENV_KEYS,
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_MODELS_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_DGX_SSH_TARGET",
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")

ProtectedRunner = Callable[[Mapping[str, str], Path], Mapping[str, Any]]


def run_s149_single_host_live_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    report_path: Path = REPORT_PATH,
    topology_runner: ProtectedRunner | None = None,
    object_storage_runner: ProtectedRunner | None = None,
    provider_runner: ProtectedRunner | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(ACTIVATION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "requirement": "S149",
            "slice": "1490",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {ACTIVATION_ENV}=1 are required.",
        }
    if env.get(PROFILE_ENV, DEFAULT_PROFILE) != DEFAULT_PROFILE:
        return _failure("profile_not_allowed")

    try:
        with TemporaryDirectory(prefix="nex-s149-live-") as temporary:
            evidence_dir = Path(temporary)
            topology = dict(
                (topology_runner or _run_topology)(env, evidence_dir / "topology.json")
            )
            if topology.get("status") != "PASS":
                return _nested_failure("topology", topology, env)
            object_storage = dict(
                (object_storage_runner or _run_object_storage)(
                    env, evidence_dir / "object-storage.json"
                )
            )
            if object_storage.get("status") != "PASS":
                return _nested_failure("object_storage", object_storage, env)
            providers = dict(
                (provider_runner or _run_providers)(env, evidence_dir / "providers.json")
            )
            if providers.get("status") != "PASS":
                return _nested_failure("providers", providers, env)

        result = _evaluate(topology, object_storage, providers)
        assert_evidence_redacted(result, env)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    except Exception as exc:  # noqa: BLE001 - protected acceptance fails closed
        result = _failure(
            "single_host_live_acceptance_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )
        assert_evidence_redacted(result, env)
        return result


def _run_topology(env: Mapping[str, str], report_path: Path) -> Mapping[str, Any]:
    nested = {**env, "NEX_S143_EXTERNAL_STAGING_ACCEPTANCE": "1"}
    return run_s143_external_staging_acceptance(
        nested,
        execute=True,
        root=ROOT,
        report_path=report_path,
    )


def _run_object_storage(
    env: Mapping[str, str], report_path: Path
) -> Mapping[str, Any]:
    nested = {**env, "NEX_S146_PROTECTED_ACCEPTANCE": "1"}
    return run_s146_object_storage_acceptance(
        nested,
        execute=True,
        root=ROOT,
        report_path=report_path,
    )


def _run_providers(env: Mapping[str, str], _report_path: Path) -> Mapping[str, Any]:
    nested = {
        **env,
        "NEX_MO_MODEL_ROLLOUT_LIVE_ACCEPTANCE": "1",
        "NEX_MO_MODEL_ROLLOUT_LIVE_ACCEPTANCE_PROFILE": "test",
    }
    return run_s147_model_rollout_live_acceptance(nested)


def _evaluate(
    topology: Mapping[str, Any],
    object_storage: Mapping[str, Any],
    providers: Mapping[str, Any],
) -> dict[str, Any]:
    topology_services = _mapping(topology.get("services"))
    topology_postgres = _mapping(topology.get("postgres_migration"))
    topology_providers = _mapping(topology.get("providers"))
    capability_map = _mapping(topology_providers.get("capabilities"))
    storage_postgres = _mapping(object_storage.get("postgres"))
    storage_rustfs = _mapping(object_storage.get("rustfs"))
    storage_cleanup = _mapping(object_storage.get("cleanup"))
    storage_adapters = _mapping(object_storage.get("adapters"))
    cross_bucket = _mapping(storage_rustfs.get("cross_bucket_denied"))
    provider_summary = _mapping(providers.get("summary"))
    provider_cleanup = _mapping(providers.get("cleanup"))
    release_set_digest = str(topology.get("release_set_digest") or "")
    checks = {
        "immutable_release_set_bound": _DIGEST.fullmatch(release_set_digest) is not None,
        "five_test_database_migrations_current": topology_postgres.get("status") == "PASS"
        and topology_postgres.get("service_count") == 5,
        "six_runtime_services_ready_across_generations": all(
            topology_services.get(name) == 6
            for name in ("initial_ready_count", "rotated_ready_count", "rollback_ready_count")
        ),
        "compose_provider_routes_ready": topology_providers.get("status") == "PASS"
        and set(capability_map) == {"embedding", "reranking", "generation"}
        and all(_mapping(item).get("status") == "PASS" for item in capability_map.values()),
        "rustfs_postgres_metadata_current": storage_postgres.get("status") == "PASS"
        and storage_postgres.get("migration_service_count") == 5,
        "rustfs_owner_adapters_round_trip": storage_adapters.get("status") == "PASS"
        and storage_adapters.get("postgres_payload_bytes_written") is False,
        "rustfs_restart_recovery_verified": storage_rustfs.get("restart_recovery_verified")
        is True,
        "rustfs_owner_isolation_verified": cross_bucket.get("cx_to_ae_denied") is True
        and cross_bucket.get("ae_to_cx_denied") is True,
        "rustfs_zero_residue_cleanup": storage_cleanup.get("status") == "PASS"
        and storage_cleanup.get("named_volume_removed") is True,
        "three_remote_provider_capabilities_live": provider_summary.get(
            "live_provider_count"
        )
        == 3
        and provider_summary.get("runtime_ready_count") == 3,
        "provider_model_identity_matched": provider_summary.get(
            "live_model_match_count"
        )
        == 3,
        "generation_reasoning_disabled": provider_summary.get(
            "generation_reasoning_mode"
        )
        == "disabled",
        "provider_rehearsal_zero_residue": provider_cleanup.get("residue") == 0,
        "production_resources_not_targeted": all(
            _mapping(item.get("decision")).get("production_contacted") is False
            and _mapping(item.get("decision")).get("production_deployment_approved")
            is False
            for item in (topology, object_storage)
        ),
    }
    passed = all(checks.values())
    release_candidate_id = (
        f"rc:s149:{release_set_digest.removeprefix('sha256:')[:16]}"
        if _DIGEST.fullmatch(release_set_digest)
        else "rc:s149:invalid"
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1490",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "single_host_live_acceptance_failed",
        "profile": DEFAULT_PROFILE,
        "release_binding": {
            "release_candidate_id": release_candidate_id,
            "release_set_digest": release_set_digest,
            "topology_evidence_digest": _digest(topology),
            "object_storage_evidence_digest": _digest(object_storage),
            "provider_evidence_digest": _digest(providers),
        },
        "checks": checks,
        "summary": {
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "test_database_count": 5,
            "runtime_service_count": 6,
            "object_storage_owner_count": 2,
            "live_provider_count": _nonnegative_int(
                provider_summary.get("live_provider_count")
            ),
            "residue_count": _nonnegative_int(provider_cleanup.get("residue")),
        },
        "external_notification": {
            "status": "EXTERNAL_NOT_ACTIVATED",
            "s150_requirement": "time_bounded_p1_waiver_and_local_compensating_control",
        },
        "execution_scope": {
            "topology": "single_host_docker_compose",
            "postgres": "actual_five_test_databases",
            "object_storage": "actual_ephemeral_rustfs_with_restart",
            "providers": "actual_three_remote_capabilities",
            "provider_process_mutation_performed": False,
            "production_contacted": False,
            "production_deployment_approved": False,
        },
        "redaction": {
            "status": "PASS",
            "raw_nested_evidence_included": False,
            "credentials_included": False,
            "endpoint_urls_included": False,
            "private_payloads_included": False,
        },
        "next_slice": "1491" if passed else "blocked",
    }


def _nested_failure(
    boundary: str,
    nested: Mapping[str, Any],
    env: Mapping[str, str],
) -> dict[str, Any]:
    result = _failure(
        f"{boundary}_acceptance_failed",
        {
            "boundary": boundary,
            "nested_status": str(nested.get("status") or "UNKNOWN"),
            "nested_failure_code": str(nested.get("failure_code") or "not_reported"),
        },
    )
    assert_evidence_redacted(result, env)
    return result


def _failure(code: str, diagnostics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "requirement": "S149",
        "slice": "1490",
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
        raise ValueError("S149 live evidence contains protected value")


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s149_single_host_live_acceptance=skipped"
    summary = _mapping(result.get("summary"))
    return (
        f"s149_single_host_live_acceptance={str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"databases={summary.get('test_database_count', 0)}/5 "
        f"services={summary.get('runtime_service_count', 0)}/6 "
        f"providers={summary.get('live_provider_count', 0)}/3 "
        f"residue={summary.get('residue_count', -1)} "
        f"next={result.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    result = run_s149_single_host_live_acceptance(
        execute=args.execute,
        report_path=args.report_path,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
