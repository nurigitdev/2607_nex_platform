from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.engine import make_url

from .postgres_resilience import PostgresResiliencePolicy
from .postgres_targets import ResolvedPostgresTestTarget


RECOVERY_ACCEPTANCE_SCHEMA_VERSION = "postgres_recovery_acceptance.v1"


class PostgresRecoveryAcceptanceError(RuntimeError):
    pass


class Cursor(Protocol):
    def execute(self, query: str) -> Any: ...
    def fetchone(self) -> Any: ...
    def fetchall(self) -> Any: ...


@dataclass(frozen=True)
class DatabaseRecoveryFingerprint:
    service_id: str
    database_name: str
    migration_digest: str
    migration_count: int
    table_count: int
    required_extensions: tuple[str, ...]


def write_recovery_libpq_files(
    *,
    resolved_targets: Iterable[ResolvedPostgresTestTarget],
    policy: PostgresResiliencePolicy,
    destination: Path,
    recovery_socket: Path,
    recovery_port: int,
) -> tuple[Path, Path]:
    targets = tuple(resolved_targets)
    by_service = {target.target.service_id: target for target in targets}
    if set(by_service) != {target.service_id for target in policy.targets}:
        raise PostgresRecoveryAcceptanceError("recovery_target_coverage_invalid")
    if not recovery_socket.is_absolute() or not 1024 <= recovery_port <= 65535:
        raise PostgresRecoveryAcceptanceError("recovery_endpoint_invalid")
    if destination.is_symlink():
        raise PostgresRecoveryAcceptanceError("recovery_credential_root_symlink")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    service_path = destination / "pg_service.conf"
    passfile_path = destination / "pgpass"
    service_lines: list[str] = []
    pass_lines: list[str] = []
    for policy_target in policy.targets:
        resolved = by_service[policy_target.service_id]
        url = make_url(resolved.database_url)
        host = _safe_value(url.host or "127.0.0.1")
        port = int(url.port or 5432)
        database = _safe_value(url.database or "")
        username = _safe_value(url.username or "")
        password = url.password
        if not database or not username or password is None:
            raise PostgresRecoveryAcceptanceError("recovery_source_url_invalid")
        service_lines.extend(
            _service_section(
                policy_target.libpq_service,
                host=host,
                port=port,
                database=database,
                username=username,
            )
        )
        recovery_service = f"{policy_target.libpq_service}-recovery"
        service_lines.extend(
            _service_section(
                recovery_service,
                host=str(recovery_socket),
                port=recovery_port,
                database=database,
                username="postgres",
            )
        )
        pass_lines.append(
            ":".join(
                _passfile_escape(value)
                for value in (host, str(port), database, username, password)
            )
        )
    service_lines.extend(
        _service_section(
            policy.cluster_libpq_service,
            host=str(recovery_socket),
            port=recovery_port,
            database="postgres",
            username="postgres",
        )
    )
    _write_private(service_path, "\n".join(service_lines) + "\n")
    _write_private(passfile_path, "\n".join(pass_lines) + "\n")
    return service_path, passfile_path


def read_database_fingerprint(
    connection: Any,
    *,
    service_id: str,
    expected_database_name: str,
    required_extensions: Iterable[str | tuple[str, str]],
) -> DatabaseRecoveryFingerprint:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        identity = cursor.fetchone()
        if not identity or identity[0] != expected_database_name:
            raise PostgresRecoveryAcceptanceError("recovery_database_identity_invalid")
        cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
        migrations = tuple(str(row[0]) for row in cursor.fetchall())
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        table_row = cursor.fetchone()
        cursor.execute(
            "SELECT extname FROM pg_extension "
            "WHERE extname IN ('pgcrypto', 'vector') ORDER BY extname"
        )
        extensions = tuple(str(row[0]) for row in cursor.fetchall())
    required = tuple(
        sorted(
            item[0] if isinstance(item, tuple) else item
            for item in required_extensions
        )
    )
    if not migrations or not table_row or int(table_row[0]) <= 0:
        raise PostgresRecoveryAcceptanceError("recovery_database_fingerprint_invalid")
    if not set(required).issubset(extensions):
        raise PostgresRecoveryAcceptanceError("recovery_extension_missing")
    digest = hashlib.sha256("\n".join(migrations).encode("utf-8")).hexdigest()
    return DatabaseRecoveryFingerprint(
        service_id=service_id,
        database_name=expected_database_name,
        migration_digest=digest,
        migration_count=len(migrations),
        table_count=int(table_row[0]),
        required_extensions=required,
    )


def compare_recovery_fingerprints(
    sources: Mapping[str, DatabaseRecoveryFingerprint],
    restored: Mapping[str, DatabaseRecoveryFingerprint],
) -> None:
    if set(sources) != set(restored) or not sources:
        raise PostgresRecoveryAcceptanceError("recovery_fingerprint_coverage_invalid")
    for service_id, source in sources.items():
        if source != restored[service_id]:
            raise PostgresRecoveryAcceptanceError("recovery_fingerprint_mismatch")


def recovery_fingerprints_public_projection(
    fingerprints: Mapping[str, DatabaseRecoveryFingerprint],
) -> dict[str, Any]:
    records = tuple(fingerprints[key] for key in sorted(fingerprints))
    return {
        "schema_version": RECOVERY_ACCEPTANCE_SCHEMA_VERSION,
        "database_count": len(records),
        "migration_count": sum(item.migration_count for item in records),
        "table_count": sum(item.table_count for item in records),
        "required_extension_count": sum(
            len(item.required_extensions) for item in records
        ),
        "migration_digests": {
            item.service_id: item.migration_digest for item in records
        },
        "database_urls_exposed": False,
    }


def _service_section(
    name: str, *, host: str, port: int, database: str, username: str
) -> list[str]:
    return [
        f"[{_safe_value(name)}]",
        f"host={_safe_value(host)}",
        f"port={port}",
        f"dbname={_safe_value(database)}",
        f"user={_safe_value(username)}",
        "connect_timeout=10",
        "",
    ]


def _safe_value(value: str) -> str:
    if not value or any(character in value for character in "\r\n"):
        raise PostgresRecoveryAcceptanceError("recovery_libpq_value_invalid")
    return value


def _passfile_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def _write_private(path: Path, value: str) -> None:
    if path.exists() or path.is_symlink():
        raise PostgresRecoveryAcceptanceError("recovery_credential_file_exists")
    with path.open("x", encoding="utf-8") as output:
        os.chmod(path, 0o600)
        output.write(value)
        output.flush()
        os.fsync(output.fileno())
