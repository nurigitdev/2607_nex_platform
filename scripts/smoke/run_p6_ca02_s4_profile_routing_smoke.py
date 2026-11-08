#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5
import run_p6_s3_postgres_smoke as p6_s3
from nex_ae_api.nsl_backend_profiles import (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
)
from nex_ae_api.nsl_read_backends import (
    NSLReadBackendError,
    NSLReadBackendRouter,
    NSLReadExecutionService,
)
from nex_runtime import load_env_file, redact_database_url
from run_migrations import MigrationError, run_service_migrations

SCHEMA_VERSION = "p6_ca02_s4_profile_routing_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_CA02_S4_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2205_ae_nsl_dual_profile"


class _ProbeBackend:
    def __init__(self, profile: str) -> None:
        self.backend_profile = profile
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "backend_profile": self.backend_profile,
            "nsl_execution_id": kwargs["request"]["nsl_execution_id"],
            "attempt_no": kwargs["attempt_no"],
        }


class _ProbeRuns:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def get(self, **_kwargs: Any) -> None:
        return None

    def save(self, *, record: dict[str, Any]) -> dict[str, Any]:
        self.saved.append(record)
        return record


def run_p6_ca02_s4_profile_routing_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S4",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not p5_s5._target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )
        profile_evidence: dict[str, dict[str, Any]] = {}
        for profile in (
            NSL_V01_PROCESS_ISOLATED_BACKEND,
            NSL_V01_IN_PROCESS_BACKEND,
        ):
            result = p5_s5._execute_postgres_smoke(
                database_url,
                verifier=partial(
                    p6_s3._verify_nsl_binding,
                    backend_profile=profile,
                    activate_executor=True,
                    post_bind_verifier=partial(
                        _verify_profile_route, expected_profile=profile
                    ),
                ),
            )
            profile_evidence[profile] = result
        checks = {
            "migration_current": (
                REQUIRED_MIGRATION in migration.planned
                and migration.planned[-1] == REQUIRED_MIGRATION
                and len(migration.planned)
                == len(migration.applied) + len(migration.skipped)
            ),
            "process_isolated_route_passed": profile_evidence[
                NSL_V01_PROCESS_ISOLATED_BACKEND
            ]["status"]
            == "PASS",
            "in_process_route_passed": profile_evidence[
                NSL_V01_IN_PROCESS_BACKEND
            ]["status"]
            == "PASS",
            "process_isolated_cleanup_complete": profile_evidence[
                NSL_V01_PROCESS_ISOLATED_BACKEND
            ]["cleanup_counts"]["remaining"]
            == 0,
            "in_process_cleanup_complete": profile_evidence[
                NSL_V01_IN_PROCESS_BACKEND
            ]["cleanup_counts"]["remaining"]
            == 0,
        }
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S4",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "remote_provider_required": False,
            "profile": "test",
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "migration": {
                "planned_count": len(migration.planned),
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
                "latest_version": migration.planned[-1],
            },
            "checks": checks,
            "profile_checks": {
                profile: evidence["checks"]
                for profile, evidence in profile_evidence.items()
            },
        }
    except (
        MigrationError,
        NSLReadBackendError,
        SQLAlchemyError,
        OSError,
        RuntimeError,
        ValueError,
        p6_s3.NSLStepExecutionError,
        p6_s3.SkillArtifactGatewayError,
        p5_s5.AgentContextError,
        p5_s5.AgentExecutionError,
        p5_s5.AgentIdentityRepositoryError,
        p5_s5.AgentPlanError,
        p5_s5.CapabilitySnapshotError,
        p5_s5.ExecutablePlanError,
        p5_s5.PlanValidationError,
        p5_s5.RuntimePolicyError,
        p5_s5.WorkIntentError,
    ) as exc:
        return _failure(
            "execution_failed",
            p5_s5._redact_detail(str(exc), database_url=database_url),
        )


def _verify_profile_route(
    fixture: Mapping[str, Any], *, expected_profile: str
) -> dict[str, bool]:
    backends = {
        NSL_V01_IN_PROCESS_BACKEND: _ProbeBackend(NSL_V01_IN_PROCESS_BACKEND),
        NSL_V01_PROCESS_ISOLATED_BACKEND: _ProbeBackend(
            NSL_V01_PROCESS_ISOLATED_BACKEND
        ),
    }
    router = NSLReadBackendRouter(backends)
    runs = _ProbeRuns()
    service = NSLReadExecutionService(
        bindings=fixture["repository"],
        artifacts=fixture["artifact_repository"],
        backend=router,
        runs=runs,  # type: ignore[arg-type]
    )
    record = service.execute_bound(
        tenant_id=str(fixture["tenant_id"]),
        executable_step_id=str(fixture["step_id"]),
        attempt_no=1,
        expected_backend_profile=expected_profile,
    )
    other_profile = (
        NSL_V01_PROCESS_ISOLATED_BACKEND
        if expected_profile == NSL_V01_IN_PROCESS_BACKEND
        else NSL_V01_IN_PROCESS_BACKEND
    )
    no_fallback = False
    try:
        NSLReadExecutionService(
            bindings=fixture["repository"],
            artifacts=fixture["artifact_repository"],
            backend=NSLReadBackendRouter({other_profile: backends[other_profile]}),
            runs=_ProbeRuns(),  # type: ignore[arg-type]
        ).execute_bound(
            tenant_id=str(fixture["tenant_id"]),
            executable_step_id=str(fixture["step_id"]),
            attempt_no=2,
            expected_backend_profile=expected_profile,
        )
    except NSLReadBackendError as exc:
        no_fallback = (
            exc.error_code == "ae.nsl_backend_profile_unavailable"
            and exc.retryable is True
        )
    restarted = fixture["repository"].get(
        tenant_id=str(fixture["tenant_id"]),
        executable_step_id=str(fixture["step_id"]),
    )
    return {
        "durable_profile_routed_exactly": (
            record["backend_profile"] == expected_profile
            and len(backends[expected_profile].calls) == 1
            and len(backends[other_profile].calls) == 0
        ),
        "compiled_and_persisted_profile_agree": (
            fixture["bound"]["binding"]["backend_profile"] == expected_profile
            and restarted["binding"]["backend_profile"] == expected_profile
        ),
        "profile_unavailable_has_no_fallback": no_fallback,
        "router_advertises_exact_profiles": router.backend_profiles
        == (
            NSL_V01_IN_PROCESS_BACKEND,
            NSL_V01_PROCESS_ISOLATED_BACKEND,
        ),
        "probe_run_saved_once": len(runs.saved) == 1,
    }


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-CA02-S4",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    migration = evidence.get("migration") or {}
    return (
        "p6_ca02_s4_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"latest={migration.get('latest_version', 'not-run')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_ca02_s4_profile_routing_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
