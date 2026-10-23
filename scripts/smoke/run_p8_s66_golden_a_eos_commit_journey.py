#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-eos",
    ROOT / "services" / "nex-oa",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_ae_web_credential_login_playwright_postgres_smoke as browser_runtime
import run_p8_s06_nsl_compatibility as p8_s06
import run_p8_s53_approval_resume_postgres as p8_s53
import run_p8_s65_golden_a_approval_journey as p8_s65
from nex_ae_api.golden_a_planning import (
    build_golden_a_canonical_write_payload,
)
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    create_eos_app,
)
from nex_oa.authorization_service import OA_AUTHORIZATION_READ_SCOPE
from nex_oa.memberships import SqlAlchemyOaTenantMembershipRegistry
from nex_oa.subjects import SqlAlchemyOaSubjectRegistry
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref
from p8_golden_a_fixture import (
    load_golden_a_fixture,
    reset_golden_a_fixture,
    seed_golden_a_fixture,
)
from run_migrations import run_service_migrations

SCHEMA_VERSION = "p8_s66_golden_a_eos_commit_journey.v1"
SMOKE_ENV = "NEX_P8_S66_GOLDEN_A_COMMIT_LIVE"
EOS_DATABASE_ENV = "NEX_EOS_TEST_DATABASE_URL"
DEFAULT_REPORT = Path("/tmp/nex-p8-s66-golden-a-eos-commit.json")
DEFAULT_PLATFORM_LOCK = ROOT / "deployment/locks/python-production.lock"
WORKER = ROOT / "scripts/smoke/p8_s66_eos_commit_worker.py"
EXPECTED_DATABASES = {
    **p8_s65.EXPECTED_DATABASES,
    EOS_DATABASE_ENV: ("nex_eos_user", "nex_eos_test"),
}
_EOS_MUTATION_TABLES = (
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
)


class P8S66SmokeError(RuntimeError):
    pass


def run_p8_s66_golden_a_eos_commit_journey(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    source: Path = p8_s65.DEFAULT_SOURCE,
    lock_path: Path = p8_s65.DEFAULT_LOCK,
    wheel_directory: Path = p8_s65.DEFAULT_WHEEL_DIRECTORY,
    python_bin: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S66",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
            "actual_postgres": False,
            "actual_remote_provider": False,
        }
    database_urls = {key: env.get(key, "") for key in EXPECTED_DATABASES}
    try:
        for key, (role, database) in EXPECTED_DATABASES.items():
            p8_s65._require_database_target(
                database_urls[key], role=role, database=database, label=key
            )
        s65 = p8_s65.run_p8_s65_golden_a_approval_journey(
            {**env, p8_s65.SMOKE_ENV: "1"},
            execute=True,
            source=source,
            lock_path=lock_path,
            wheel_directory=wheel_directory,
            python_bin=python_bin,
        )
        if s65.get("status") != "PASS":
            raise P8S66SmokeError("P8-S65 live approval prerequisite failed")
        eos_migration = run_service_migrations(
            "nex-eos",
            database_url=database_urls[EOS_DATABASE_ENV],
            profile="test",
        )
        commit = _execute_commit(
            env=env,
            source=source,
            lock_path=lock_path,
            wheel_directory=wheel_directory,
            python_bin=python_bin,
            ae_database_url=database_urls[p8_s65.AE_DATABASE_ENV],
            oa_database_url=database_urls[p8_s65.OA_DATABASE_ENV],
            eos_database_url=database_urls[EOS_DATABASE_ENV],
            s65=s65,
        )
        checks = {
            "s65_live_approval_passed": s65["status"] == "PASS",
            "eos_migrations_current": (
                len(eos_migration.planned)
                == len(eos_migration.applied) + len(eos_migration.skipped)
            ),
            **commit["checks"],
        }
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S66",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "s65": {
                "status": s65["status"],
                "payload_hash": s65["approval"]["payload_hash"],
                "approval_status": s65["approval"]["approval_status"],
                "resume_state": s65["approval"]["resume_state"],
                "model_ref": s65["provider"]["model_ref"],
            },
            "eos_migration": p8_s65._migration_summary(eos_migration),
            **{key: value for key, value in commit.items() if key != "checks"},
            "checks": checks,
            "checks_passed": sum(bool(value) for value in checks.values()),
            "checks_total": len(checks),
            "decision": {
                "p8_s66_closed": all(checks.values()),
                "next_slice": "P8-S67",
            },
        }
        p8_s65._assert_redacted(evidence, env)
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected gate records safe failure.
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S66",
            "status": "FAIL",
            "actual_postgres": False,
            "actual_remote_provider": False,
            "failure_code": getattr(exc, "error_code", type(exc).__name__),
            "detail": p8_s65._redact(str(exc), *database_urls.values()),
            "decision": {"p8_s66_closed": False},
        }
        p8_s65._assert_redacted(evidence, env)
        return evidence


def _execute_commit(  # pragma: no cover - actual PostgreSQL/OA/EOS gate.
    *,
    env: Mapping[str, str],
    source: Path,
    lock_path: Path,
    wheel_directory: Path,
    python_bin: str,
    ae_database_url: str,
    oa_database_url: str,
    eos_database_url: str,
    s65: Mapping[str, Any],
    exactly_once: bool = False,
) -> dict[str, Any]:
    fixture = load_golden_a_fixture()
    tenant_id = fixture["tenant"]["tenant_id"]
    approval = s65["approval"]
    platform_evidence = approval["platform_approval_evidence"]
    write_identity = approval["write_identity"]
    payload = build_golden_a_canonical_write_payload(fixture)
    expected_hash = nsl_write_payload_hash_ref(payload)
    if expected_hash != approval["payload_hash"]:
        raise P8S66SmokeError("S65 approval hash differs from Golden A payload")

    ae_engine = create_engine(ae_database_url, poolclass=NullPool)
    oa_engine = create_engine(oa_database_url, poolclass=NullPool)
    eos_engine = create_engine(eos_database_url, poolclass=NullPool)
    oa_factory = sessionmaker(bind=oa_engine, expire_on_commit=False)
    oa_server = None
    eos_server = None
    eos_runtime = None
    commit: dict[str, Any] | None = None
    try:
        _cleanup_ae(ae_engine, tenant_id)
        _cleanup_eos_mutations(eos_engine, tenant_id)
        reset_golden_a_fixture(fixture, oa_engine=oa_engine, eos_engine=eos_engine)
        oa_app = p8_s65._build_oa_app(oa_database_url)
        oa_server = browser_runtime.start_api_server(
            oa_app, browser_runtime.find_free_port()
        )
        eos_to_oa_token = p8_s65._service_token(
            "nex-eos", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
        )
        ae_to_oa_token = p8_s65._service_token(
            "nex-ae-api", "nex-oa", OA_AUTHORIZATION_READ_SCOPE
        )
        ae_to_eos_token = p8_s65._service_token("nex-ae-api", "nex-eos")
        eos_app = create_eos_app(
            environ={
                "NEX_EOS_SERVICE_ID": "nex-eos",
                "NEX_PROFILE": "test",
                "NEX_VERSION": "2.1.0-p8-s66",
                "NEX_BUILD_SHA": "p8s66protected",
                "NEX_EOS_DATABASE_URL": eos_database_url,
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
                "NEX_OA_BASE_URL": oa_server.url,
                "NEX_EOS_TO_OA_SERVICE_TOKEN": eos_to_oa_token,
            }
        )
        eos_runtime = eos_app.state.eos_database_runtime
        if eos_runtime is None or eos_app.state.eos_voucher_command_service is None:
            raise P8S66SmokeError("EOS governed voucher service is unavailable")
        seed_golden_a_fixture(
            fixture,
            memberships=SqlAlchemyOaTenantMembershipRegistry(
                oa_factory,
                subject_registry=SqlAlchemyOaSubjectRegistry(oa_factory),
            ),
            organization=eos_app.state.eos_organization,
            projects=eos_app.state.eos_projects,
            accounts=eos_app.state.eos_accounts,
        )
        eos_server = browser_runtime.start_api_server(
            eos_app, browser_runtime.find_free_port()
        )

        with ae_engine.connect() as connection:
            ae_identity = tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            )
        with eos_engine.connect() as connection:
            eos_identity = tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            )

        lock = p8_s06._load_object(lock_path, "NSL v0.2 wheel lock")
        with TemporaryDirectory(prefix="p8-s66-nsl-v02-") as temporary:
            temporary_root = Path(temporary)
            target = temporary_root / "site-packages"
            wheel = wheel_directory / str(lock["wheel_filename"])
            p8_s06._install_wheel(python_bin, wheel, target, env)
            worker_env = p8_s53._worker_environment(env, target)
            worker_env.update(
                {
                    "NEX_P8_S66_WORKER_AE_DATABASE_URL": ae_database_url,
                    "NEX_P8_S66_WORKER_OA_BASE_URL": oa_server.url,
                    "NEX_P8_S66_WORKER_EOS_BASE_URL": eos_server.url,
                    "NEX_P8_S66_WORKER_AE_TO_OA_SERVICE_TOKEN": ae_to_oa_token,
                    "NEX_P8_S66_WORKER_AE_TO_EOS_SERVICE_TOKEN": ae_to_eos_token,
                }
            )
            approval_path = temporary_root / "approval-evidence.json"
            approval_path.write_text(
                json.dumps(
                    {
                        "platform_approval_evidence": platform_evidence,
                        "write_identity": write_identity,
                        "expected_payload_hash": expected_hash,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            worker_command = [
                python_bin,
                str(WORKER),
                "--source",
                str(source),
                "--lock",
                str(lock_path),
                "--platform-lock",
                str(DEFAULT_PLATFORM_LOCK),
                "--approval-evidence",
                str(approval_path),
            ]
            if exactly_once:
                worker_command.append("--exactly-once-variants")
            worker = p8_s53._run_json(
                tuple(worker_command),
                env=worker_env,
                operation=(
                    "execute isolated NSL v0.2 Golden A exactly-once worker"
                    if exactly_once
                    else "execute isolated NSL v0.2 Golden A EOS commit worker"
                ),
            )
        counts = _eos_mutation_counts(eos_engine, tenant_id)
        ae_counts = _ae_counts(ae_engine, tenant_id)
        checks = {
            "actual_ae_database": ae_identity == ("nex_ae_test", "nex_ae_user"),
            "actual_eos_database": eos_identity == ("nex_eos_test", "nex_eos_user"),
            "actual_nsl_skill_v11": (
                worker["skill"]["skill_id"] == fixture["admission"]["skill_id"]
                and worker["skill"]["skill_version"]
                == fixture["admission"]["exact_skill_version"]
                and worker["skill"]["semantic_hash"]
                == fixture["admission"]["skill_semantic_hash"]
            ),
            "approved_payload_hash_reused": (
                worker["payload_hash"]
                == expected_hash
                == worker["write_request_payload_hash"]
                == worker["outcome_payload_hash"]
                == worker["verification_payload_hash"]
            ),
            "approval_lineage_reused": (
                worker["approval_request_id"]
                == platform_evidence["approval_request_id"]
            ),
            "fresh_oa_runtime_policy": worker["fresh_oa_runtime_policy_calls"]
            == (3 if exactly_once else 1),
            "eos_committed_once": counts
            == {
                "eos_voucher_draft_attachment": 0,
                "eos_voucher_draft_line": 2,
                "eos_voucher_draft": 1,
                "eos_outbox": 1,
                "eos_idempotency": 1,
                "eos_business_operation": 1,
            },
            "ae_write_evidence_durable": ae_counts
            == {
                "idempotency": 1,
                "write_evidence": worker["expected_write_evidence_count"],
            },
            "post_write_verified": worker["verification_status"] == "VERIFIED",
        }
        if exactly_once:
            variants = worker.get("retry_variants", {})
            checks["ack_loss_reconciled"] = (
                variants.get("ack_loss_after_commit", {}).get("observed_commit_state")
                == "UNKNOWN_COMMIT_STATE"
                and variants.get("ack_loss_after_commit", {}).get(
                    "reconciled_commit_state"
                )
                == "COMMITTED"
            )
            checks["worker_and_publication_retry_reused"] = all(
                variants.get(name, {}).get("reservation") == "REUSED"
                and variants.get(name, {}).get("commit_state") == "COMMITTED"
                and variants.get(name, {}).get("verification_status") == "VERIFIED"
                for name in ("ae_worker_retry", "result_publication_retry")
            )
        commit = {
            "checks": checks,
            "payload_hash": worker["payload_hash"],
            "business_operation_id": worker["business_operation_id"],
            "approval_request_id": worker["approval_request_id"],
            "commit_state": worker["commit_state"],
            "voucher_ref": worker["voucher_ref"],
            "verification_status": worker["verification_status"],
            "verification_evidence_ref": worker["verification_evidence_ref"],
            "eos_mutation_counts": counts,
            "ae_evidence_counts": ae_counts,
            "nsl_release_admission_hash": worker["release_admission_hash"],
        }
        if exactly_once:
            commit["retry_variants"] = worker["retry_variants"]
    finally:
        _cleanup_ae(ae_engine, tenant_id)
        _cleanup_eos_mutations(eos_engine, tenant_id)
        residue = reset_golden_a_fixture(
            fixture, oa_engine=oa_engine, eos_engine=eos_engine
        )
        if commit is not None:
            commit["checks"]["zero_residue"] = (
                all(value == 0 for value in _ae_counts(ae_engine, tenant_id).values())
                and all(
                    value == 0
                    for value in _eos_mutation_counts(eos_engine, tenant_id).values()
                )
                and all(
                    value == 0
                    for service in residue.values()
                    for value in service.values()
                )
            )
        if oa_server is not None:
            oa_server.stop()
        if eos_server is not None:
            eos_server.stop()
        if eos_runtime is not None:
            eos_runtime.dispose()
        ae_engine.dispose()
        oa_engine.dispose()
        eos_engine.dispose()
    if commit is None:
        raise P8S66SmokeError("Golden A EOS commit evidence is unavailable")
    return commit


def _cleanup_ae(engine: Any, tenant_id: str) -> None:
    with engine.begin() as connection:
        for table_name in ("ae_nsl_write_evidence", "ae_nsl_idem_evidence"):
            connection.execute(
                text(f"DELETE FROM {table_name} WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )


def _cleanup_eos_mutations(engine: Any, tenant_id: str) -> None:
    with engine.begin() as connection:
        for table in _EOS_MUTATION_TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == tenant_id))


def _eos_mutation_counts(engine: Any, tenant_id: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table.name: int(
                connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.tenant_id == tenant_id)
                ).scalar_one()
            )
            for table in _EOS_MUTATION_TABLES
        }


def _ae_counts(engine: Any, tenant_id: str) -> dict[str, int]:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                text(
                    "SELECT 'idempotency' AS kind, count(*) AS total "
                    "FROM ae_nsl_idem_evidence WHERE tenant_id = :tenant_id "
                    "UNION ALL SELECT 'write_evidence', count(*) "
                    "FROM ae_nsl_write_evidence WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).all()
        )


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks", {})
    passed = sum(bool(value) for value in checks.values())
    return (
        "p8_s66_golden_a_eos_commit="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"provider={str(bool(evidence.get('actual_remote_provider'))).lower()} "
        f"checks={passed}/{len(checks)} "
        f"commit={evidence.get('commit_state', '-')} "
        f"verification={evidence.get('verification_status', '-')}"
    )


def write_report(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the protected P8-S66 Golden A EOS commit journey."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source", type=Path, default=p8_s65.DEFAULT_SOURCE)
    parser.add_argument("--lock", type=Path, default=p8_s65.DEFAULT_LOCK)
    parser.add_argument(
        "--wheel-directory", type=Path, default=p8_s65.DEFAULT_WHEEL_DIRECTORY
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    evidence = run_p8_s66_golden_a_eos_commit_journey(
        execute=args.execute,
        source=args.source,
        lock_path=args.lock,
        wheel_directory=args.wheel_directory,
        python_bin=args.python,
    )
    write_report(args.report, evidence)
    print(summary_line(evidence))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
