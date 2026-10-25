from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .database import psycopg_database_url, required_database_url
from .postgres_backup import (
    SAFE_BACKUP_ID,
    LogicalBackupResult,
    backup_result_public_projection,
    build_service_logical_backup_plan,
    execute_logical_backup,
)
from .semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DEMO_DATABASE_ADMISSION_SCHEMA_VERSION = "p8_demo_database_admission.v1"
DEMO_BACKUP_SET_SCHEMA_VERSION = "p8_demo_pre_migration_backup_set.v1"
DEMO_TENANT_FIXTURE_PLAN_SCHEMA_VERSION = "p8_demo_tenant_fixture_plan.v1"
DEMO_TENANT_ID = "p8-golden-a"
DEMO_DATABASE_BACKUP_CONFIRMATION = "BACKUP_P8_DEMO_DEV_DATABASES"
DEMO_FIXTURE_CONFIRMATIONS = {
    "SEED": "SEED_P8_GOLDEN_A_TENANT",
    "RESET": "RESET_P8_GOLDEN_A_TENANT",
}
_SAFE_LIBPQ_QUERY_OPTIONS = frozenset(
    {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout"}
)


class DemoDatabaseGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoDatabaseTarget:
    service_id: str
    database_env: str
    expected_database_name: str
    expected_role_name: str


@dataclass(frozen=True)
class ResolvedDemoDatabaseTarget:
    target: DemoDatabaseTarget
    database_url: str = field(repr=False)
    drivername: str
    host: str
    port: int


@dataclass(frozen=True)
class DemoDatabaseInspection:
    service_id: str
    database_name: str
    role_name: str
    identity_state: str
    migration_state: str
    expected_migrations: tuple[str, ...]
    applied_migrations: tuple[str, ...]
    missing_migrations: tuple[str, ...]
    extra_migrations: tuple[str, ...]
    source_inventory_hash: str


@dataclass(frozen=True)
class DemoBackupSetResult:
    schema_version: str
    backup_id: str
    state: str
    manifest_path: Path
    targets: tuple[LogicalBackupResult, ...]
    set_hash: str


@dataclass(frozen=True)
class DemoTenantFixturePlan:
    schema_version: str
    action: str
    tenant_id: str
    fixture_id: str
    fixture_hash: str
    backup_id: str
    service_ids: tuple[str, ...]
    fixture_owner_service_ids: tuple[str, ...]
    mutation_scope: str
    tenant_predicate_required: bool
    plan_hash: str


DEMO_DATABASE_TARGETS = (
    DemoDatabaseTarget("nex-oa", "NEX_OA_DATABASE_URL", "nex_oa_dev", "nex_oa_user"),
    DemoDatabaseTarget("nex-ag", "NEX_AG_DATABASE_URL", "nex_ag_dev", "nex_ag_user"),
    DemoDatabaseTarget(
        "nex-ae-api", "NEX_AE_DATABASE_URL", "nex_ae_dev", "nex_ae_user"
    ),
    DemoDatabaseTarget("nex-cx", "NEX_CX_DATABASE_URL", "nex_cx_dev", "nex_cx_user"),
    DemoDatabaseTarget("nex-mo", "NEX_MO_DATABASE_URL", "nex_mo_dev", "nex_mo_user"),
    DemoDatabaseTarget("nex-wc", "NEX_WC_DATABASE_URL", "nex_wc_dev", "nex_wc_user"),
    DemoDatabaseTarget(
        "nex-eos", "NEX_EOS_DATABASE_URL", "nex_eos_dev", "nex_eos_user"
    ),
)


def resolve_demo_database_targets(
    environ: Mapping[str, str],
    *,
    service_ids: Iterable[str] | None = None,
) -> tuple[ResolvedDemoDatabaseTarget, ...]:
    selected = tuple(
        (target.service_id for target in DEMO_DATABASE_TARGETS)
        if service_ids is None
        else service_ids
    )
    if not selected:
        raise DemoDatabaseGuardError("demo_service_selection_empty")
    if len(set(selected)) != len(selected):
        raise DemoDatabaseGuardError("demo_service_selection_duplicate")
    by_service = {target.service_id: target for target in DEMO_DATABASE_TARGETS}
    if any(service_id not in by_service for service_id in selected):
        raise DemoDatabaseGuardError("demo_service_unknown")

    resolved = tuple(
        _resolve_target(by_service[service_id], environ) for service_id in selected
    )
    bindings = [
        (item.host, item.port, item.target.expected_database_name) for item in resolved
    ]
    if len(set(bindings)) != len(bindings):
        raise DemoDatabaseGuardError("demo_database_binding_duplicate")
    return resolved


def inspect_demo_database_targets(
    targets: Sequence[ResolvedDemoDatabaseTarget],
    *,
    database_root: Path,
    connect: Callable[..., Any],
) -> tuple[DemoDatabaseInspection, ...]:
    if not targets:
        raise DemoDatabaseGuardError("demo_database_targets_empty")
    return tuple(
        _inspect_target(target, database_root=database_root, connect=connect)
        for target in targets
    )


def demo_database_admission_public_projection(
    inspections: Sequence[DemoDatabaseInspection],
) -> dict[str, Any]:
    records = tuple(inspections)
    if not records:
        raise DemoDatabaseGuardError("demo_database_inspections_empty")
    return {
        "schema_version": DEMO_DATABASE_ADMISSION_SCHEMA_VERSION,
        "profile": "dev",
        "state": "ADMITTED"
        if all(item.identity_state == "ADMITTED" for item in records)
        else "BLOCKED",
        "service_count": len(records),
        "migration_current_count": sum(
            item.migration_state == "CURRENT" for item in records
        ),
        "targets": [
            {
                "service_id": item.service_id,
                "database_name": item.database_name,
                "role_name": item.role_name,
                "identity_state": item.identity_state,
                "migration_state": item.migration_state,
                "expected_migration_count": len(item.expected_migrations),
                "applied_migration_count": len(item.applied_migrations),
                "missing_migrations": list(item.missing_migrations),
                "extra_migrations": list(item.extra_migrations),
                "source_inventory_hash": item.source_inventory_hash,
            }
            for item in records
        ],
        "database_urls_exposed": False,
    }


def execute_demo_pre_migration_backup_set(
    targets: Sequence[ResolvedDemoDatabaseTarget],
    inspections: Sequence[DemoDatabaseInspection],
    *,
    backup_id: str,
    backup_root: Path,
    pg_dump_bin: Path,
    confirmation: str,
    runner: Callable[..., Any],
    parent_environ: Mapping[str, str] | None = None,
) -> DemoBackupSetResult:
    _require_complete_admitted_set(targets, inspections)
    if confirmation != DEMO_DATABASE_BACKUP_CONFIRMATION:
        raise DemoDatabaseGuardError("demo_backup_confirmation_invalid")
    if not SAFE_BACKUP_ID.fullmatch(backup_id):
        raise DemoDatabaseGuardError("demo_backup_id_invalid")
    if not backup_root.is_absolute() or backup_root.is_symlink():
        raise DemoDatabaseGuardError("demo_backup_root_invalid")

    with TemporaryDirectory(prefix="nex-p8-demo-pg-") as temporary:
        credential_root = Path(temporary)
        service_file = credential_root / "pg_service.conf"
        passfile = credential_root / ".pgpass"
        service_names = write_demo_backup_credentials(
            targets, service_file=service_file, passfile=passfile
        )
        results = []
        for target in targets:
            plan = build_service_logical_backup_plan(
                service_id=target.target.service_id,
                libpq_service=service_names[target.target.service_id],
                backup_id=backup_id,
                backup_root=backup_root,
                pg_dump_bin=pg_dump_bin,
                service_file=service_file,
                passfile=passfile,
                compression="gzip:6",
                postgres_major=16,
                parent_environ=parent_environ,
            )
            results.append(execute_logical_backup(plan, runner=runner))

    projected_targets = [
        {
            **backup_result_public_projection(result),
            "archive_name": result.archive_name,
        }
        for result in results
    ]
    inspection_by_service = {item.service_id: item for item in inspections}
    manifest_without_hash = {
        "schema_version": DEMO_BACKUP_SET_SCHEMA_VERSION,
        "backup_id": backup_id,
        "state": "CREATED",
        "service_count": len(results),
        "targets": [
            {
                **record,
                "database_name": next(
                    target.target.expected_database_name
                    for target in targets
                    if target.target.service_id == record["service_id"]
                ),
                "role_name": next(
                    target.target.expected_role_name
                    for target in targets
                    if target.target.service_id == record["service_id"]
                ),
                "source_inventory_hash": inspection_by_service[
                    record["service_id"]
                ].source_inventory_hash,
                "migration_state": inspection_by_service[
                    record["service_id"]
                ].migration_state,
                "applied_migrations": list(
                    inspection_by_service[record["service_id"]].applied_migrations
                ),
                "missing_migrations": list(
                    inspection_by_service[record["service_id"]].missing_migrations
                ),
                "extra_migrations": list(
                    inspection_by_service[record["service_id"]].extra_migrations
                ),
            }
            for record in projected_targets
        ],
    }
    set_hash = semantic_sha256_hash_ref(manifest_without_hash)
    manifest = {**manifest_without_hash, "set_hash": set_hash}
    manifest_path = backup_root / f"{backup_id}.manifest.json"
    _write_json_atomic(manifest_path, manifest)
    return DemoBackupSetResult(
        schema_version=DEMO_BACKUP_SET_SCHEMA_VERSION,
        backup_id=backup_id,
        state="CREATED",
        manifest_path=manifest_path,
        targets=tuple(results),
        set_hash=set_hash,
    )


def demo_backup_set_public_projection(result: DemoBackupSetResult) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "backup_id": result.backup_id,
        "state": result.state,
        "service_count": len(result.targets),
        "set_hash": result.set_hash,
        "targets": [backup_result_public_projection(item) for item in result.targets],
        "credential_material_exposed": False,
    }


def write_demo_backup_credentials(
    targets: Sequence[ResolvedDemoDatabaseTarget],
    *,
    service_file: Path,
    passfile: Path,
) -> dict[str, str]:
    if not service_file.is_absolute() or not passfile.is_absolute():
        raise DemoDatabaseGuardError("demo_backup_credential_path_invalid")
    if service_file.exists() or passfile.exists():
        raise DemoDatabaseGuardError("demo_backup_credential_file_exists")
    services: dict[str, str] = {}
    service_lines: list[str] = []
    pass_lines: list[str] = []
    for target in targets:
        parsed = make_url(target.database_url)
        service_name = f"p8-demo-{target.target.service_id}"
        services[target.target.service_id] = service_name
        service_lines.extend(
            (
                f"[{service_name}]",
                f"host={_libpq_value(target.host)}",
                f"port={target.port}",
                f"dbname={_libpq_value(target.target.expected_database_name)}",
                f"user={_libpq_value(target.target.expected_role_name)}",
            )
        )
        for name, value in parsed.query.items():
            if name in _SAFE_LIBPQ_QUERY_OPTIONS and isinstance(value, str):
                service_lines.append(f"{name}={_libpq_value(value)}")
        service_lines.append("")
        if parsed.password is not None:
            pass_lines.append(
                ":".join(
                    _pgpass_value(str(value))
                    for value in (
                        target.host,
                        target.port,
                        target.target.expected_database_name,
                        target.target.expected_role_name,
                        parsed.password,
                    )
                )
            )
    _write_secret_file(service_file, "\n".join(service_lines))
    _write_secret_file(passfile, "\n".join(pass_lines) + ("\n" if pass_lines else ""))
    return services


def build_demo_tenant_fixture_plan(
    fixture: Mapping[str, Any],
    *,
    action: str,
    confirmation: str,
    backup_id: str,
) -> DemoTenantFixturePlan:
    normalized_action = action.strip().upper() if isinstance(action, str) else ""
    expected_confirmation = DEMO_FIXTURE_CONFIRMATIONS.get(normalized_action)
    if expected_confirmation is None:
        raise DemoDatabaseGuardError("demo_fixture_action_invalid")
    if confirmation != expected_confirmation:
        raise DemoDatabaseGuardError("demo_fixture_confirmation_invalid")
    if not SAFE_BACKUP_ID.fullmatch(backup_id):
        raise DemoDatabaseGuardError("demo_fixture_backup_id_invalid")
    if not isinstance(fixture, Mapping):
        raise DemoDatabaseGuardError("demo_fixture_invalid")
    tenant = fixture.get("tenant")
    if not isinstance(tenant, Mapping) or tenant.get("tenant_id") != DEMO_TENANT_ID:
        raise DemoDatabaseGuardError("demo_fixture_tenant_invalid")
    fixture_id = fixture.get("fixture_id")
    if not isinstance(fixture_id, str) or not fixture_id.strip():
        raise DemoDatabaseGuardError("demo_fixture_id_invalid")
    try:
        fixture_hash = validate_hash_ref(fixture.get("fixture_hash"))
    except ValueError as exc:
        raise DemoDatabaseGuardError("demo_fixture_hash_invalid") from exc
    canonical = dict(fixture)
    canonical.pop("fixture_hash", None)
    if semantic_sha256_hash_ref(canonical) != fixture_hash:
        raise DemoDatabaseGuardError("demo_fixture_hash_mismatch")
    values = {
        "schema_version": DEMO_TENANT_FIXTURE_PLAN_SCHEMA_VERSION,
        "action": normalized_action,
        "tenant_id": DEMO_TENANT_ID,
        "fixture_id": fixture_id,
        "fixture_hash": fixture_hash,
        "backup_id": backup_id,
        "service_ids": tuple(target.service_id for target in DEMO_DATABASE_TARGETS),
        "fixture_owner_service_ids": ("nex-oa", "nex-eos"),
        "mutation_scope": "TENANT_ONLY",
        "tenant_predicate_required": True,
    }
    return DemoTenantFixturePlan(
        **values,
        plan_hash=semantic_sha256_hash_ref(values),
    )


def admit_demo_tenant_fixture_plan(
    plan: DemoTenantFixturePlan,
    inspections: Sequence[DemoDatabaseInspection],
    backup_set: DemoBackupSetResult | Mapping[str, Any],
) -> dict[str, Any]:
    records = tuple(inspections)
    service_ids = tuple(item.service_id for item in records)
    expected_ids = tuple(target.service_id for target in DEMO_DATABASE_TARGETS)
    if service_ids != expected_ids:
        raise DemoDatabaseGuardError("demo_fixture_database_set_incomplete")
    if any(item.migration_state != "CURRENT" for item in records):
        raise DemoDatabaseGuardError("demo_fixture_migrations_not_current")
    backup = validate_demo_backup_set_manifest(
        _backup_set_payload(backup_set), expected_backup_id=plan.backup_id
    )
    return {
        **demo_tenant_fixture_plan_public_projection(plan),
        "state": "READY",
        "migration_current_count": len(records),
        "backup_set_hash": backup["set_hash"],
    }


def demo_tenant_fixture_plan_public_projection(
    plan: DemoTenantFixturePlan,
) -> dict[str, Any]:
    return {
        **asdict(plan),
        "confirmation_exposed": False,
        "whole_database_reset_allowed": False,
    }


def validate_demo_backup_set_manifest(
    payload: Mapping[str, Any],
    *,
    expected_backup_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise DemoDatabaseGuardError("demo_backup_set_manifest_invalid")
    record = dict(payload)
    supplied_hash = record.pop("set_hash", None)
    try:
        validated_hash = validate_hash_ref(supplied_hash)
    except ValueError as exc:
        raise DemoDatabaseGuardError("demo_backup_set_hash_invalid") from exc
    if semantic_sha256_hash_ref(record) != validated_hash:
        raise DemoDatabaseGuardError("demo_backup_set_hash_mismatch")
    backup_id = record.get("backup_id")
    if (
        record.get("schema_version") != DEMO_BACKUP_SET_SCHEMA_VERSION
        or record.get("state") != "CREATED"
        or not isinstance(backup_id, str)
        or not SAFE_BACKUP_ID.fullmatch(backup_id)
    ):
        raise DemoDatabaseGuardError("demo_backup_set_manifest_invalid")
    if expected_backup_id is not None and backup_id != expected_backup_id:
        raise DemoDatabaseGuardError("demo_backup_set_id_mismatch")
    targets = record.get("targets")
    if not isinstance(targets, list):
        raise DemoDatabaseGuardError("demo_backup_set_manifest_invalid")
    service_ids = tuple(
        item.get("service_id") if isinstance(item, Mapping) else None
        for item in targets
    )
    expected_services = tuple(target.service_id for target in DEMO_DATABASE_TARGETS)
    if (
        record.get("service_count") != len(expected_services)
        or service_ids != expected_services
    ):
        raise DemoDatabaseGuardError("demo_backup_set_services_incomplete")
    return {**record, "set_hash": validated_hash}


def load_demo_backup_set_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoDatabaseGuardError("demo_backup_set_manifest_unreadable") from exc
    return validate_demo_backup_set_manifest(payload)


def _resolve_target(
    target: DemoDatabaseTarget,
    environ: Mapping[str, str],
) -> ResolvedDemoDatabaseTarget:
    try:
        database_url = required_database_url(target.database_env, environ)
        parsed = make_url(database_url)
    except (ValueError, SQLAlchemyError) as exc:
        raise DemoDatabaseGuardError("demo_database_url_missing_or_invalid") from exc
    if not parsed.drivername.startswith("postgresql"):
        raise DemoDatabaseGuardError("demo_database_driver_invalid")
    if parsed.database != target.expected_database_name:
        raise DemoDatabaseGuardError("demo_database_name_mismatch")
    if parsed.username != target.expected_role_name:
        raise DemoDatabaseGuardError("demo_database_role_mismatch")
    if not parsed.host:
        raise DemoDatabaseGuardError("demo_database_host_missing")
    return ResolvedDemoDatabaseTarget(
        target=target,
        database_url=database_url,
        drivername=parsed.drivername,
        host=parsed.host,
        port=parsed.port or 5432,
    )


def _inspect_target(
    target: ResolvedDemoDatabaseTarget,
    *,
    database_root: Path,
    connect: Callable[..., Any],
) -> DemoDatabaseInspection:
    expected, inventory_hash = _source_migration_inventory(
        target.target.service_id, database_root=database_root
    )
    with (
        connect(
            psycopg_database_url(target.database_url), autocommit=True
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT current_database(), current_user, pg_is_in_recovery(), "
            "to_regclass('public.schema_migrations')"
        )
        row = cursor.fetchone()
        if row is None or len(row) != 4:
            raise DemoDatabaseGuardError("demo_database_identity_unreadable")
        database_name, role_name, in_recovery, migration_table = row
        if (database_name, role_name) != (
            target.target.expected_database_name,
            target.target.expected_role_name,
        ):
            raise DemoDatabaseGuardError("demo_database_live_identity_mismatch")
        if bool(in_recovery):
            raise DemoDatabaseGuardError("demo_database_replica_not_admitted")
        applied: tuple[str, ...] = ()
        if migration_table is not None:
            cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
            applied = tuple(str(item[0]) for item in cursor.fetchall())
    missing = tuple(sorted(set(expected) - set(applied)))
    extra = tuple(sorted(set(applied) - set(expected)))
    migration_state = (
        "DRIFT" if extra else ("CURRENT" if not missing else "MIGRATION_REQUIRED")
    )
    return DemoDatabaseInspection(
        service_id=target.target.service_id,
        database_name=target.target.expected_database_name,
        role_name=target.target.expected_role_name,
        identity_state="ADMITTED",
        migration_state=migration_state,
        expected_migrations=expected,
        applied_migrations=applied,
        missing_migrations=missing,
        extra_migrations=extra,
        source_inventory_hash=inventory_hash,
    )


def _source_migration_inventory(
    service_id: str, *, database_root: Path
) -> tuple[tuple[str, ...], str]:
    directory = database_root / service_id / "migrations"
    if not directory.is_dir():
        raise DemoDatabaseGuardError("demo_migration_directory_missing")
    records = []
    for path in sorted(directory.glob("*.sql")):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DemoDatabaseGuardError("demo_migration_inventory_unreadable") from exc
        records.append({"version": path.stem, "content": content})
    if not records:
        raise DemoDatabaseGuardError("demo_migration_inventory_empty")
    versions = tuple(record["version"] for record in records)
    if len(set(versions)) != len(versions):
        raise DemoDatabaseGuardError("demo_migration_inventory_duplicate")
    return versions, semantic_sha256_hash_ref(
        {"service_id": service_id, "migrations": records}
    )


def _require_complete_admitted_set(
    targets: Sequence[ResolvedDemoDatabaseTarget],
    inspections: Sequence[DemoDatabaseInspection],
) -> None:
    expected = tuple(target.service_id for target in DEMO_DATABASE_TARGETS)
    target_ids = tuple(item.target.service_id for item in targets)
    inspection_ids = tuple(item.service_id for item in inspections)
    if target_ids != expected or inspection_ids != expected:
        raise DemoDatabaseGuardError("demo_backup_database_set_incomplete")
    if any(item.identity_state != "ADMITTED" for item in inspections):
        raise DemoDatabaseGuardError("demo_backup_identity_not_admitted")


def _backup_set_payload(
    backup_set: DemoBackupSetResult | Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(backup_set, Mapping):
        return backup_set
    try:
        return json.loads(backup_set.manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoDatabaseGuardError("demo_backup_set_manifest_unreadable") from exc


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists() or path.is_symlink():
        raise DemoDatabaseGuardError("demo_backup_set_manifest_exists")
    partial = path.with_name(f".{path.name}.partial")
    try:
        with partial.open("x", encoding="utf-8") as output:
            os.chmod(partial, 0o600)
            json.dump(dict(payload), output, ensure_ascii=True, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _write_secret_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x", encoding="utf-8") as output:
        os.chmod(path, 0o600)
        output.write(content)


def _libpq_value(value: str) -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise DemoDatabaseGuardError("demo_backup_credential_value_invalid")
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _pgpass_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise DemoDatabaseGuardError("demo_backup_credential_value_invalid")
    return value.replace("\\", "\\\\").replace(":", "\\:")
