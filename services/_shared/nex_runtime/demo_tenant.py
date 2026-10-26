from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .demo_database import DEMO_TENANT_ID, DemoDatabaseGuardError
from .semantic_hashes import semantic_sha256_hash_ref

DEMO_TENANT_RESET_SCHEMA_VERSION = "p8_demo_tenant_reset.v1"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_TENANT_COLUMNS = ("tenant_id", "tenant_ref_id")


@dataclass(frozen=True)
class TenantScopedTable:
    table_name: str
    tenant_columns: tuple[str, ...]


def build_tenant_delete_order(
    table_names: Iterable[str],
    foreign_keys: Iterable[tuple[str, str]],
) -> tuple[str, ...]:
    tables = tuple(sorted({_identifier(item) for item in table_names}))
    table_set = set(tables)
    edges = {
        (child, parent)
        for child, parent in foreign_keys
        if child in table_set and parent in table_set and child != parent
    }
    outgoing = {table: set() for table in tables}
    incoming_count = {table: 0 for table in tables}
    for child, parent in edges:
        outgoing[child].add(parent)
        incoming_count[parent] += 1

    ready = sorted(table for table, count in incoming_count.items() if count == 0)
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for parent in sorted(outgoing[current]):
            incoming_count[parent] -= 1
            if incoming_count[parent] == 0:
                ready.append(parent)
                ready.sort()
    if len(ordered) != len(tables):
        raise DemoDatabaseGuardError("demo_tenant_foreign_key_cycle")
    return tuple(ordered)


def inspect_demo_tenant_database(
    engine: Engine,
    *,
    service_id: str,
    expected_database_name: str,
    expected_role_name: str,
    tenant_id: str = DEMO_TENANT_ID,
) -> dict[str, Any]:
    with engine.connect() as connection:
        _assert_identity(
            connection,
            expected_database_name=expected_database_name,
            expected_role_name=expected_role_name,
        )
        tables = _tenant_tables(connection)
        counts = _tenant_counts(connection, tables, tenant_id=tenant_id)
    payload = {
        "service_id": service_id,
        "database_name": expected_database_name,
        "role_name": expected_role_name,
        "tenant_id": tenant_id,
        "tenant_table_count": len(tables),
        "row_count": sum(counts.values()),
        "table_counts": counts,
    }
    return {**payload, "inventory_hash": semantic_sha256_hash_ref(payload)}


def reset_demo_tenant_database(
    engine: Engine,
    *,
    service_id: str,
    expected_database_name: str,
    expected_role_name: str,
    tenant_id: str = DEMO_TENANT_ID,
) -> dict[str, Any]:
    if tenant_id != DEMO_TENANT_ID:
        raise DemoDatabaseGuardError("demo_tenant_reset_scope_invalid")
    with engine.begin() as connection:
        _assert_identity(
            connection,
            expected_database_name=expected_database_name,
            expected_role_name=expected_role_name,
        )
        tables = _tenant_tables(connection)
        order = build_tenant_delete_order(
            (item.table_name for item in tables),
            _tenant_foreign_keys(connection),
        )
        by_name = {item.table_name: item for item in tables}
        before = _tenant_counts(connection, tables, tenant_id=tenant_id)
        deleted: dict[str, int] = {}
        for table_name in order:
            table = by_name[table_name]
            result = connection.execute(
                text(
                    f'DELETE FROM "{table_name}" WHERE '
                    + _tenant_predicate(table.tenant_columns)
                ),
                {"tenant_id": tenant_id},
            )
            deleted[table_name] = int(result.rowcount or 0)
        after = _tenant_counts(connection, tables, tenant_id=tenant_id)
        if any(after.values()):
            raise DemoDatabaseGuardError("demo_tenant_reset_residue_detected")
    payload = {
        "schema_version": DEMO_TENANT_RESET_SCHEMA_VERSION,
        "service_id": service_id,
        "database_name": expected_database_name,
        "role_name": expected_role_name,
        "tenant_id": tenant_id,
        "mutation_scope": "TENANT_ONLY",
        "delete_order": list(order),
        "rows_before": sum(before.values()),
        "rows_deleted": sum(deleted.values()),
        "rows_after": sum(after.values()),
        "table_counts_before": before,
        "table_rows_deleted": deleted,
        "table_counts_after": after,
    }
    return {**payload, "evidence_hash": semantic_sha256_hash_ref(payload)}


def _tenant_tables(connection: Any) -> tuple[TenantScopedTable, ...]:
    rows = connection.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND column_name IN ('tenant_id', 'tenant_ref_id') "
            "ORDER BY table_name, column_name"
        )
    ).all()
    grouped: dict[str, list[str]] = {}
    for table_name, column_name in rows:
        table = _identifier(str(table_name))
        column = str(column_name)
        if column not in _TENANT_COLUMNS:
            raise DemoDatabaseGuardError("demo_tenant_column_invalid")
        grouped.setdefault(table, []).append(column)
    return tuple(
        TenantScopedTable(table_name=table, tenant_columns=tuple(columns))
        for table, columns in grouped.items()
    )


def _tenant_foreign_keys(connection: Any) -> tuple[tuple[str, str], ...]:
    rows = connection.execute(
        text(
            "SELECT child.relname, parent.relname "
            "FROM pg_constraint constraint_record "
            "JOIN pg_class child ON child.oid = constraint_record.conrelid "
            "JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace "
            "JOIN pg_class parent ON parent.oid = constraint_record.confrelid "
            "JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace "
            "WHERE constraint_record.contype = 'f' "
            "AND child_ns.nspname = 'public' AND parent_ns.nspname = 'public' "
            "ORDER BY child.relname, parent.relname"
        )
    ).all()
    return tuple((_identifier(str(child)), _identifier(str(parent))) for child, parent in rows)


def _tenant_counts(
    connection: Any,
    tables: Sequence[TenantScopedTable],
    *,
    tenant_id: str,
) -> dict[str, int]:
    return {
        table.table_name: int(
            connection.execute(
                text(
                    f'SELECT count(*) FROM "{table.table_name}" WHERE '
                    + _tenant_predicate(table.tenant_columns)
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
        for table in tables
    }


def _tenant_predicate(columns: Sequence[str]) -> str:
    if not columns:
        raise DemoDatabaseGuardError("demo_tenant_columns_empty")
    return " OR ".join(f'"{_identifier(column)}" = :tenant_id' for column in columns)


def _assert_identity(
    connection: Any,
    *,
    expected_database_name: str,
    expected_role_name: str,
) -> None:
    row = connection.execute(text("SELECT current_database(), current_user")).one()
    if tuple(row) != (expected_database_name, expected_role_name):
        raise DemoDatabaseGuardError("demo_tenant_database_identity_mismatch")


def _identifier(value: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise DemoDatabaseGuardError("demo_tenant_identifier_invalid")
    return value
