#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
):
    sys.path.insert(0, str(path))

from nex_ae_api.nsl_backend_profiles import NSL_V01_IN_PROCESS_BACKEND
from nex_ae_api.nsl_read_backends import build_v01_in_process_backend
from nex_runtime import load_env_file

SCHEMA_VERSION = "p6_ca02_s3_in_process_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_CA02_S3_IN_PROCESS_SMOKE"
NSL_SOURCE_ENV = "NEX_AE_P6_CA02_S3_NSL_SOURCE"
DEFAULT_LOCK = ROOT / "deployment/locks/nsl-v0.1-wheel.json"
DEFAULT_WHEEL = (
    ROOT
    / "reports/deployment/p6-ca02-nsl-wheel"
    / "nex_skill_language-0.1.0-py3-none-any.whl"
)
EXAMPLES = ROOT / "docs/transition/P6/contracts/examples"


class _WorkerSession:
    def __init__(self, worker: object, audit: object) -> None:
        self.worker = worker
        self._audit = audit

    def evidence_refs(self) -> list[str]:
        events = list(getattr(self._audit, "events", ()))
        refs = {f"NSL:AUDIT:{event.event_hash}" for event in events}
        refs.update(
            f"NSL:SNAPSHOT:{event.payload['snapshot_ref']}"
            for event in events
            if isinstance(event.payload, Mapping) and event.payload.get("snapshot_ref")
        )
        if not events or not any(ref.startswith("NSL:SNAPSHOT:") for ref in refs):
            raise RuntimeError("in-process NSL execution omitted required evidence")
        return sorted(refs)


class _InstalledWheelWorkerFactory:
    def __init__(self, source_root: Path, artifact: Mapping[str, Any]) -> None:
        self._source_root = source_root
        self._artifact = dict(artifact)
        self.session_count = 0

    def __call__(self, artifact_handle: str, progress: object) -> _WorkerSession:
        from nsl.adapters.ed25519 import Ed25519PackageSigner, Ed25519TrustStore
        from nsl.api import (
            RuntimeEngine,
            SkillExecutionWorker,
            VerifiedPackageSkillResolver,
            WorkerEvidencePolicy,
        )
        from nsl.audit import InMemoryAuditSink, InMemorySnapshotStore
        from nsl.compiler import NslCompiler
        from nsl.nsp import NspBuilder
        from nsl.nsp_verification import NspVerificationPolicy, NspVerifier
        from nsl.security import RuntimeEnvironment
        from nsl.vertical_slice import build_mock_executor, build_tool_catalog

        catalog = build_tool_catalog()
        source = (self._source_root / "examples/project_budget_check.ns").read_text(
            encoding="utf-8"
        )
        compilation = NslCompiler(catalog).compile(source)
        if compilation.nso_bytes is None:
            raise RuntimeError("source-backed NSL fixture did not compile")
        signer = Ed25519PackageSigner("publisher.p6-golden-1", bytes(range(1, 33)))
        package = NspBuilder().build((compilation.nso_bytes,), signer=signer)
        trust = Ed25519TrustStore({signer.key_id: signer.public_key_bytes})
        verified = NspVerifier(
            policy=NspVerificationPolicy(RuntimeEnvironment.PRODUCTION),
            signature_verifier=trust,
        ).verify(package.data)
        if (
            artifact_handle != self._artifact["backend_artifact_handle"]
            or verified.package_hash != self._artifact["package_hash"]
            or verified.skills[0].skill.semantic_hash
            != self._artifact["skill_semantic_hash"]
        ):
            raise RuntimeError("source-backed NSL artifact identity drifted")
        audit = InMemoryAuditSink()
        snapshots = InMemorySnapshotStore()
        worker = SkillExecutionWorker(
            runtime=RuntimeEngine(catalog),
            resolver=VerifiedPackageSkillResolver((verified,)),
            tools=build_mock_executor(catalog),
            audit_sink=audit,
            snapshot_store=snapshots,
            progress_sink=progress,
            evidence_policy=WorkerEvidencePolicy.SNAPSHOT_REQUIRED,
        )
        self.session_count += 1
        return _WorkerSession(worker, audit)


def run_p6_ca02_s3_in_process_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S3",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_installed_wheel": False,
        }
    source_value = env.get(NSL_SOURCE_ENV, "")
    if not source_value:
        return _failure("nsl_source_missing", f"{NSL_SOURCE_ENV} is required.")
    try:
        source_root = Path(source_value).resolve(strict=True)
        lock = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
        artifact = _example("p6-golden-verified-artifact-v1.json")
        request = _example("p6-golden-skill-execution-request-v1.json")
        context = _example("p6-golden-context-projection-v1.json")
        package = _installed_package_evidence(source_root, lock)
        factory = _InstalledWheelWorkerFactory(source_root, artifact)
        adapter = build_v01_in_process_backend(factory)
        first = adapter.execute(
            request=request,
            context_projection=context,
            artifact=artifact,
            attempt_no=1,
            started_at=_utc_now(),
        )
        second = adapter.execute(
            request=request,
            context_projection=context,
            artifact=artifact,
            attempt_no=2,
            started_at=_utc_now(),
        )
        checks = {
            "admitted_wheel_digest": package["wheel_sha256"] == lock["wheel_sha256"],
            "installed_version_exact": package["package_version"]
            == lock["package_version"],
            "dependency_version_exact": package["cryptography_version"]
            == lock["locked_cryptography_version"],
            "public_api_complete": package["public_api_complete"],
            "runtime_import_is_not_checkout": package["runtime_import_is_not_checkout"],
            "in_process_profile_exact": first["backend_profile"]
            == second["backend_profile"]
            == NSL_V01_IN_PROCESS_BACKEND,
            "terminal_result_complete": first["isolation_status"]
            == second["isolation_status"]
            == "COMPLETED"
            and first["runtime_status"] == second["runtime_status"] == "COMPLETED",
            "identity_stable_across_attempts": first["nsl_execution_id"]
            == second["nsl_execution_id"]
            == request["nsl_execution_id"]
            and first["business_operation_id"]
            == second["business_operation_id"]
            == request["business_operation_id"],
            "fresh_session_per_execution": factory.session_count == 2,
            "progress_and_snapshot_evidence": _has_complete_evidence(first)
            and _has_complete_evidence(second),
        }
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S3",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_installed_wheel": True,
            "backend_profile": adapter.backend_profile,
            "timeout_semantics": adapter.timeout_semantics,
            "package": package,
            "checks": checks,
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "session_count": factory.session_count,
            "remote_provider_required": False,
        }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _failure("execution_failed", str(exc))


def _installed_package_evidence(
    source_root: Path, lock: Mapping[str, Any]
) -> dict[str, Any]:
    required_lock_fields = {
        "schema_version",
        "repository",
        "distribution",
        "package_version",
        "source_revision",
        "wheel_filename",
        "wheel_sha256",
        "requires_python",
        "requirements",
        "platform_cryptography_requirement",
        "locked_cryptography_version",
        "platform_lock_sha256",
        "public_api_symbols",
    }
    if set(lock) != required_lock_fields:
        raise RuntimeError("NSL wheel admission lock fields drifted")
    if not DEFAULT_WHEEL.is_file() or DEFAULT_WHEEL.name != lock["wheel_filename"]:
        raise RuntimeError("admitted NSL wheel is unavailable")
    revision = _git_output(source_root, "rev-parse", "HEAD")
    if revision != lock["source_revision"]:
        raise RuntimeError("NSL source revision does not match admission lock")
    if _git_output(source_root, "status", "--porcelain"):
        raise RuntimeError("NSL source checkout must be clean for protected evidence")
    from nsl import api

    api_file = Path(api.__file__).resolve()
    public_symbols = list(lock["public_api_symbols"])
    return {
        "distribution": lock["distribution"],
        "package_version": importlib.metadata.version(lock["distribution"]),
        "source_revision": revision,
        "wheel_sha256": _sha256_ref(DEFAULT_WHEEL.read_bytes()),
        "cryptography_version": importlib.metadata.version("cryptography"),
        "public_api_complete": all(hasattr(api, name) for name in public_symbols),
        "runtime_import_path": str(api_file),
        "runtime_import_is_not_checkout": not api_file.is_relative_to(source_root),
    }


def _has_complete_evidence(record: Mapping[str, Any]) -> bool:
    states = [item.get("state") for item in record.get("progress_events", ())]
    refs = record.get("evidence_refs", ())
    return states == ["STARTED", "SKILL_RESOLVED", "RUNNING", "COMPLETED"] and any(
        str(ref).startswith("NSL:SNAPSHOT:") for ref in refs
    )


def _git_output(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _example(name: str) -> dict[str, Any]:
    value = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{name} must contain an object")
    return value


def _sha256_ref(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-CA02-S3",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_installed_wheel": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        f"p6_ca02_s3_in_process={str(evidence.get('status', 'FAIL')).lower()} "
        f"actual_installed_wheel={str(bool(evidence.get('actual_installed_wheel'))).lower()} "
        f"checks={evidence.get('checks_passed', 0)}/{evidence.get('checks_total', 0)} "
        f"profile={evidence.get('backend_profile', 'not-run')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run P6-CA02-S3 in-process smoke")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_env_file(ROOT / ".env")
    evidence = run_p6_ca02_s3_in_process_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
