#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "services/_shared"),
    str(ROOT / "services/nex-oa"),
    str(ROOT / "services/nex-eos"),
    str(ROOT / "scripts/smoke"),
]

from nex_eos import (
    ProjectMembershipInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
)
from nex_oa.credentials import SqlAlchemyOaCredentialRegistry
from nex_oa.memberships import SqlAlchemyOaTenantMembershipRegistry
from nex_oa.subjects import SqlAlchemyOaSubjectRegistry
from nex_runtime import load_env_file
from nex_runtime.demo_database import (
    DEMO_TENANT_ID,
    DemoDatabaseGuardError,
    admit_demo_tenant_fixture_plan,
    build_demo_tenant_fixture_plan,
    inspect_demo_database_targets,
    load_demo_backup_set_manifest,
    resolve_demo_database_targets,
)
from nex_runtime.demo_fixture import load_demo_business_fixture
from nex_runtime.demo_tenant import (
    inspect_demo_tenant_database,
    reset_demo_tenant_database,
)
from nex_runtime.semantic_hashes import (
    semantic_sha256_hash_ref,
)
from p8_golden_a_fixture import (
    seed_golden_a_fixture,
    validate_golden_a_fixture,
)

DEMO_FIXTURE_SCHEMA_VERSION = "p8_demo_fixture.v1"
DEMO_FIXTURE_EXECUTION_SCHEMA_VERSION = "p8_demo_fixture_execution.v1"
DEFAULT_FIXTURE = ROOT / "scripts/deployment/data/p8_demo_vo00_fixture.v1.json"
DEFAULT_REPORT = ROOT / "reports/deployment/p8-demo-tenant-fixture.json"
_FIELDS = {
    "schema_version",
    "fixture_id",
    "fixture_hash",
    "base_fixture",
    "tenant",
    "login_accounts",
    "project_memberships",
}


def load_demo_fixture(
    path: Path = DEFAULT_FIXTURE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoDatabaseGuardError("demo_fixture_unreadable") from exc
    if not isinstance(raw, Mapping) or set(raw) != _FIELDS:
        raise DemoDatabaseGuardError("demo_fixture_document_invalid")
    base_ref = raw.get("base_fixture")
    if not isinstance(base_ref, Mapping):
        raise DemoDatabaseGuardError("demo_fixture_base_invalid")
    relative = Path(str(base_ref.get("path", "")))
    base_path = (ROOT / relative).resolve()
    if not base_path.is_relative_to(ROOT.resolve()) or not base_path.is_file():
        raise DemoDatabaseGuardError("demo_fixture_base_path_invalid")
    record, business_fixture = load_demo_business_fixture(
        path,
        base_fixture_path=base_path,
    )
    validate_golden_a_fixture(
        business_fixture,
        expected_tenant_id=DEMO_TENANT_ID,
    )
    _validate_accounts_and_memberships(record, business_fixture)
    return record, business_fixture


def run_demo_tenant_fixture(
    environ: Mapping[str, str],
    *,
    action: str,
    confirmation: str,
    backup_manifest_path: Path,
    fixture_path: Path = DEFAULT_FIXTURE,
    database_root: Path = ROOT / "database",
    connect: Any = psycopg.connect,
) -> dict[str, Any]:
    document, business_fixture = load_demo_fixture(fixture_path)
    targets = resolve_demo_database_targets(environ)
    inspections = inspect_demo_database_targets(
        targets,
        database_root=database_root,
        connect=connect,
    )
    backup = load_demo_backup_set_manifest(backup_manifest_path)
    plan = build_demo_tenant_fixture_plan(
        document,
        action=action,
        confirmation=confirmation,
        backup_id=str(backup["backup_id"]),
    )
    admission = admit_demo_tenant_fixture_plan(plan, inspections, backup)
    engines = {
        target.target.service_id: create_engine(
            target.database_url,
            poolclass=NullPool,
        )
        for target in targets
    }
    try:
        normalized_action = action.upper()
        if normalized_action == "RESET":
            operations = [
                reset_demo_tenant_database(
                    engines[target.target.service_id],
                    service_id=target.target.service_id,
                    expected_database_name=target.target.expected_database_name,
                    expected_role_name=target.target.expected_role_name,
                )
                for target in targets
            ]
            execution_state = "RESET"
        else:
            before = _inspect_all(engines, targets)
            if sum(item["row_count"] for item in before) == 0:
                _seed_fixture(
                    document,
                    business_fixture,
                    environ=environ,
                    oa_engine=engines["nex-oa"],
                    eos_engine=engines["nex-eos"],
                )
                execution_state = "SEEDED"
            else:
                _require_expected_state(before, document)
                _verify_seed_identity(
                    document,
                    business_fixture,
                    oa_engine=engines["nex-oa"],
                    eos_engine=engines["nex-eos"],
                )
                execution_state = "ALREADY_PRESENT"
            operations = _inspect_all(engines, targets)
            _require_expected_state(operations, document)
    finally:
        for engine in engines.values():
            engine.dispose()

    report_without_hash = {
        "schema_version": DEMO_FIXTURE_EXECUTION_SCHEMA_VERSION,
        "status": "PASS",
        "action": action.upper(),
        "execution_state": execution_state,
        "tenant_id": DEMO_TENANT_ID,
        "fixture_id": document["fixture_id"],
        "fixture_hash": document["fixture_hash"],
        "business_fixture_hash": business_fixture["fixture_hash"],
        "plan_hash": admission["plan_hash"],
        "backup_id": admission["backup_id"],
        "backup_set_hash": admission["backup_set_hash"],
        "service_count": len(operations),
        "operations": operations,
        "mutation_scope": "TENANT_ONLY",
        "credentials_included": False,
        "password_values_included": False,
    }
    return {
        **report_without_hash,
        "evidence_hash": semantic_sha256_hash_ref(report_without_hash),
    }


def _seed_fixture(
    document: Mapping[str, Any],
    business_fixture: Mapping[str, Any],
    *,
    environ: Mapping[str, str],
    oa_engine: Any,
    eos_engine: Any,
) -> None:
    oa_factory = sessionmaker(bind=oa_engine, expire_on_commit=False)
    eos_factory = sessionmaker(bind=eos_engine, expire_on_commit=False)
    subjects = SqlAlchemyOaSubjectRegistry(oa_factory)
    memberships = SqlAlchemyOaTenantMembershipRegistry(
        oa_factory,
        subject_registry=subjects,
    )
    organization = SqlAlchemyEosOrganizationRepository(eos_factory)
    projects = SqlAlchemyEosProjectRepository(eos_factory)
    accounts = SqlAlchemyEosAccountRepository(eos_factory)
    seed_golden_a_fixture(
        business_fixture,
        memberships=memberships,
        organization=organization,
        projects=projects,
        accounts=accounts,
        expected_tenant_id=DEMO_TENANT_ID,
    )

    credentials = SqlAlchemyOaCredentialRegistry(
        oa_factory,
        subject_registry=subjects,
    )
    principals = {item["subject_id"]: item for item in business_fixture["principals"]}
    for account in document["login_accounts"]:
        password = environ.get(account["password_env"], "")
        if not isinstance(password, str) or not password:
            raise DemoDatabaseGuardError("demo_fixture_password_missing")
        principal = principals[account["subject_id"]]
        credentials.ensure_credential(
            {
                "tenant_id": DEMO_TENANT_ID,
                "tenant_display_name": document["tenant"]["display_name"],
                "subject_id": account["subject_id"],
                "employee_id": account["employee_id"],
                "password": password,
                "subject_display_name": principal["display_name"],
                "credential_metadata": {"fixture_id": document["fixture_id"]},
            }
        )

    project_memberships = SqlAlchemyEosProjectMembershipRepository(eos_factory)
    projects_by_key = business_fixture["projects"]
    creator = business_fixture["scenario"]["requester_subject_id"]
    for item in document["project_memberships"]:
        project_memberships.add_membership(
            ProjectMembershipInput(
                tenant_id=DEMO_TENANT_ID,
                project_membership_id=item["project_membership_id"],
                project_id=projects_by_key[item["project_key"]]["project_id"],
                subject_id=item["subject_id"],
                member_role=item["member_role"],
                created_by_subject_id=creator,
            )
        )


def _inspect_all(
    engines: Mapping[str, Any], targets: Sequence[Any]
) -> list[dict[str, Any]]:
    return [
        inspect_demo_tenant_database(
            engines[target.target.service_id],
            service_id=target.target.service_id,
            expected_database_name=target.target.expected_database_name,
            expected_role_name=target.target.expected_role_name,
        )
        for target in targets
    ]


def _require_expected_state(
    inspections: Sequence[Mapping[str, Any]],
    document: Mapping[str, Any],
) -> None:
    principal_count = len(document["login_accounts"])
    member_count = len(document["project_memberships"])
    expected = {
        "nex-oa": {
            "oa_tenants": 1,
            "oa_subjects": principal_count,
            "oa_tenant_memberships": principal_count,
            "oa_local_credentials": principal_count,
        },
        "nex-eos": {
            "eos_nvt_project": 1,
            "eos_project": 2,
            "eos_project_member": member_count,
            "eos_account": 2,
            "eos_org_unit": 4,
            "eos_position": 1,
            "eos_position_assignment": 1,
        },
    }
    for inspection in inspections:
        actual = {
            table: count for table, count in inspection["table_counts"].items() if count
        }
        if actual != expected.get(inspection["service_id"], {}):
            raise DemoDatabaseGuardError("demo_fixture_existing_state_conflict")


def _verify_seed_identity(
    document: Mapping[str, Any],
    business_fixture: Mapping[str, Any],
    *,
    oa_engine: Any,
    eos_engine: Any,
) -> None:
    employee_ids = sorted(
        item["employee_id"].lower() for item in document["login_accounts"]
    )
    membership_ids = sorted(
        item["project_membership_id"] for item in document["project_memberships"]
    )
    project_ids = sorted(
        business_fixture["projects"][key]["project_id"] for key in ("mother", "child")
    )
    with oa_engine.connect() as connection:
        actual_employee_ids = sorted(
            connection.execute(
                text(
                    "SELECT normalized_employee_id FROM oa_local_credentials "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": DEMO_TENANT_ID},
            ).scalars()
        )
    with eos_engine.connect() as connection:
        actual_membership_ids = sorted(
            str(item)
            for item in connection.execute(
                text(
                    "SELECT project_membership_id FROM eos_project_member "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": DEMO_TENANT_ID},
            ).scalars()
        )
        actual_project_ids = sorted(
            str(item)
            for item in connection.execute(
                text("SELECT project_id FROM eos_project WHERE tenant_id = :tenant_id"),
                {"tenant_id": DEMO_TENANT_ID},
            ).scalars()
        )
    if (
        actual_employee_ids != employee_ids
        or actual_membership_ids != membership_ids
        or actual_project_ids != project_ids
    ):
        raise DemoDatabaseGuardError("demo_fixture_identity_mismatch")


def _validate_accounts_and_memberships(
    document: Mapping[str, Any],
    business_fixture: Mapping[str, Any],
) -> None:
    principals = {item["subject_id"] for item in business_fixture["principals"]}
    accounts = document.get("login_accounts")
    memberships = document.get("project_memberships")
    if not isinstance(accounts, list) or not isinstance(memberships, list):
        raise DemoDatabaseGuardError("demo_fixture_principal_binding_invalid")
    if {item.get("subject_id") for item in accounts} != principals:
        raise DemoDatabaseGuardError("demo_fixture_login_accounts_invalid")
    if any(
        set(item) != {"subject_id", "employee_id", "password_env"}
        or not isinstance(item["password_env"], str)
        or not item["password_env"].startswith("NEX_DEMO_")
        for item in accounts
    ):
        raise DemoDatabaseGuardError("demo_fixture_login_accounts_invalid")
    if any(
        set(item)
        != {"project_membership_id", "project_key", "subject_id", "member_role"}
        or item["project_key"] not in {"mother", "child"}
        or item["subject_id"] not in principals
        or item["member_role"] not in {"OWNER", "MANAGER", "MEMBER", "VIEWER"}
        for item in memberships
    ):
        raise DemoDatabaseGuardError("demo_fixture_project_memberships_invalid")


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(report), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def summary_line(report: Mapping[str, Any]) -> str:
    rows = sum(
        item.get("row_count", item.get("rows_after", 0))
        for item in report["operations"]
    )
    return (
        f"status={report['status']} action={report['action']} "
        f"state={report['execution_state']} tenant={report['tenant_id']} "
        f"services={report['service_count']} rows={rows}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the VO00 P8 Demo tenant fixture."
    )
    parser.add_argument("--action", choices=("SEED", "RESET"), required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--backup-manifest", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.env_file is not None:
        load_env_file(args.env_file)
    try:
        report = run_demo_tenant_fixture(
            os.environ,
            action=args.action,
            confirmation=args.confirmation,
            backup_manifest_path=args.backup_manifest,
            fixture_path=args.fixture,
        )
        write_report(args.report, report)
    except (DemoDatabaseGuardError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.summary:
        print(summary_line(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
