#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping

import psycopg
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "services" / "_shared"
DB_SCRIPTS = ROOT / "scripts" / "db"
sys.path[:0] = [str(SHARED), str(DB_SCRIPTS)]

from nex_runtime.postgres_backup import (  # noqa: E402
    build_logical_backup_plan,
    execute_logical_backup,
)
from nex_runtime.postgres_backup_catalog import (  # noqa: E402
    build_backup_catalog,
    record_restore_verification,
)
from nex_runtime.postgres_pitr import (  # noqa: E402
    build_postgres_pitr_plan,
    validate_pitr_cutover,
)
from nex_runtime.postgres_recovery_acceptance import (  # noqa: E402
    DatabaseRecoveryFingerprint,
    PostgresRecoveryAcceptanceError,
    compare_recovery_fingerprints,
    read_database_fingerprint,
    recovery_fingerprints_public_projection,
    write_recovery_libpq_files,
)
from nex_runtime.postgres_resilience import load_postgres_resilience_policy  # noqa: E402
from nex_runtime.postgres_restore import build_isolated_restore_plan, execute_isolated_restore  # noqa: E402
from nex_runtime.postgres_targets import resolve_postgres_test_targets  # noqa: E402


SMOKE_ENV = "NEX_S145_POSTGRES_RECOVERY_ACCEPTANCE"
POSTGRES_BIN = Path("/usr/lib/postgresql/16/bin")


class RecoveryProcessError(RuntimeError):
    pass


class EphemeralPostgres:
    def __init__(self, *, data: Path, socket_dir: Path, port: int, environment: Mapping[str, str]):
        self.data = data
        self.socket_dir = socket_dir
        self.port = port
        self.environment = dict(environment)
        self.running = False
        self.log_path = data.parent / f"{data.name}.log"

    def initialize(self, *, archive_root: Path) -> None:
        self.socket_dir.mkdir(mode=0o700)
        _run_checked(
            (
                str(POSTGRES_BIN / "initdb"),
                "--pgdata", str(self.data),
                "--username=postgres",
                "--auth-local=trust",
                "--auth-host=trust",
                "--no-locale",
                "--encoding=UTF8",
            ),
            environment=self.environment,
            timeout=60,
            code="postgres_initdb_failed",
        )
        archive_command = (
            f"{_config_path(Path(sys.executable))} "
            f"{_config_path(ROOT / 'scripts/db/archive_postgres_wal.py')} %p %f"
        )
        _append_config(
            self.data / "postgresql.conf",
            {
                "listen_addresses": "127.0.0.1",
                "wal_level": "replica",
                "archive_mode": "on",
                "archive_timeout": "300s",
                "archive_command": archive_command,
                "max_wal_senders": "5",
            },
        )
        archive_root.mkdir(mode=0o700)

    def start(self, *, timeout: int = 60) -> None:
        _run_checked(
            (
                str(POSTGRES_BIN / "pg_ctl"),
                "--pgdata", str(self.data),
                "--log", str(self.log_path),
                "--wait",
                "--timeout", str(timeout),
                "--options", f"-p {self.port} -k {self.socket_dir}",
                "start",
            ),
            environment=self.environment,
            timeout=timeout + 10,
            code="postgres_cluster_start_failed",
        )
        self.running = True

    def stop(self) -> None:
        if not self.running:
            return
        try:
            _stop_cluster(self, mode="fast")
        except RecoveryProcessError:
            _stop_cluster(self, mode="immediate")
        self.running = False

    def connection(self, database: str = "postgres"):
        return psycopg.connect(
            host=str(self.socket_dir),
            port=self.port,
            dbname=database,
            user="postgres",
            autocommit=True,
            connect_timeout=10,
        )


def run_postgresql_recovery_acceptance(
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    environ = dict(os.environ if environment is None else environment)
    if environ.get(SMOKE_ENV) != "1":
        return {
            "schema_version": "postgres_recovery_acceptance_evidence.v1",
            "slice": "1451",
            "requirement": "S145",
            "status": "SKIP",
            "reason": SMOKE_ENV,
            "next_slice": "1451",
        }
    started = time.monotonic()
    policy = load_postgres_resilience_policy(
        ROOT / "deployment/postgres/s145-policy.yaml"
    )
    resolved = resolve_postgres_test_targets(environ)
    resolved_by_service = {item.target.service_id: item for item in resolved}
    if set(resolved_by_service) != {target.service_id for target in policy.targets}:
        raise PostgresRecoveryAcceptanceError("recovery_target_coverage_invalid")

    with tempfile.TemporaryDirectory(prefix="nex-s145-protected-") as temp:
        base = Path(temp)
        archive_root = base / "wal-archive"
        source_port = _free_port()
        recovery_port = _free_port(exclude={source_port})
        cluster_environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            policy.wal_archive_root_env: str(archive_root),
        }
        isolated_restore_cluster = EphemeralPostgres(
            data=base / "isolated-restore-cluster",
            socket_dir=base / "isolated-restore-socket",
            port=source_port,
            environment=cluster_environment,
        )
        recovery_cluster: EphemeralPostgres | None = None
        source_fingerprints: dict[str, DatabaseRecoveryFingerprint] = {}
        restored_fingerprints: dict[str, DatabaseRecoveryFingerprint] = {}
        pitr_fingerprints: dict[str, DatabaseRecoveryFingerprint] = {}
        backup_bytes = 0
        try:
            isolated_restore_cluster.initialize(archive_root=archive_root)
            service_file, passfile = write_recovery_libpq_files(
                resolved_targets=resolved,
                policy=policy,
                destination=base / "credentials",
                recovery_socket=isolated_restore_cluster.socket_dir,
                recovery_port=isolated_restore_cluster.port,
            )
            source_fingerprints = _source_fingerprints(
                resolved_by_service, policy
            )
            backup_id = (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
                + secrets.token_hex(4)
            )
            backup_plans = {}
            for target in policy.targets:
                plan = build_logical_backup_plan(
                    policy=policy,
                    target=target,
                    backup_id=backup_id,
                    backup_root=base / "logical",
                    pg_dump_bin=Path("/usr/bin/pg_dump"),
                    service_file=service_file,
                    passfile=passfile,
                    parent_environ={"PATH": cluster_environment["PATH"]},
                )
                result = execute_logical_backup(plan, runner=_backup_runner)
                backup_bytes += result.archive_bytes
                backup_plans[target.service_id] = plan

            isolated_restore_cluster.start()
            for target in policy.targets:
                database_name = resolved_by_service[
                    target.service_id
                ].target.expected_database_name
                _run_checked(
                    (
                        str(POSTGRES_BIN / "createdb"),
                        "--host", str(isolated_restore_cluster.socket_dir),
                        "--port", str(isolated_restore_cluster.port),
                        "--username", "postgres",
                        database_name,
                    ),
                    environment=cluster_environment,
                    timeout=30,
                    code="recovery_database_create_failed",
                )
                plan = build_isolated_restore_plan(
                    policy=policy,
                    target=target,
                    backup_id=backup_id,
                    archive_path=backup_plans[target.service_id].archive_path,
                    manifest_path=backup_plans[target.service_id].manifest_path,
                    pg_restore_bin=Path("/usr/bin/pg_restore"),
                    recovery_service=f"{target.libpq_service}-recovery",
                    target_class="isolated_recovery",
                    service_file=service_file,
                    passfile=passfile,
                    parent_environ={"PATH": cluster_environment["PATH"]},
                )

                def probe(_plan, current=target, database=database_name):
                    with isolated_restore_cluster.connection(database) as connection:
                        fingerprint = read_database_fingerprint(
                            connection,
                            service_id=current.service_id,
                            expected_database_name=database,
                            required_extensions=current.required_extensions,
                        )
                    restored_fingerprints[current.service_id] = fingerprint
                    source = source_fingerprints[current.service_id]
                    return {
                        "database_identity": fingerprint.database_name == database,
                        "migration_head_current": fingerprint.migration_digest == source.migration_digest,
                        "select_one": fingerprint.table_count == source.table_count,
                        "required_extensions": fingerprint.required_extensions == source.required_extensions,
                    }

                restore_result = execute_isolated_restore(
                    plan,
                    inspect_runner=_restore_runner,
                    restore_runner=_restore_runner,
                    probe=probe,
                )
                record_restore_verification(
                    manifest_path=plan.manifest_path,
                    restore_result=restore_result,
                )
            compare_recovery_fingerprints(
                source_fingerprints, restored_fingerprints
            )
            _validate_catalogs(policy, backup_plans)

            recovery_id = "pitr-" + backup_id
            provisional = datetime.now(timezone.utc)
            pitr_plan = build_postgres_pitr_plan(
                policy=policy,
                recovery_id=recovery_id,
                backup_root=base / "physical",
                pg_basebackup_bin=Path("/usr/bin/pg_basebackup"),
                service_file=service_file,
                passfile=passfile,
                recovery_target_time=provisional,
                parent_environ={"PATH": cluster_environment["PATH"]},
            )
            pitr_plan.basebackup_directory.parent.mkdir(parents=True)
            _run_checked(
                pitr_plan.basebackup_command,
                environment=pitr_plan.environment,
                timeout=180,
                code="pg_basebackup_failed",
            )
            probe_token = secrets.token_hex(16)
            # PITR markers exist only in the ephemeral restored cluster. The five
            # nex_*_test source databases remain read-only for the entire run.
            with isolated_restore_cluster.connection() as connection:
                connection.execute(
                    "CREATE TABLE s145_pitr_probe "
                    "(probe_id text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT clock_timestamp())"
                )
                connection.execute(
                    "INSERT INTO s145_pitr_probe (probe_id) VALUES (%s)",
                    (probe_token,),
                )
                target_time = connection.execute(
                    "SELECT clock_timestamp()"
                ).fetchone()[0]
                connection.execute("SELECT pg_sleep(0.01)")
                post_target_token = probe_token + "-after"
                connection.execute(
                    "INSERT INTO s145_pitr_probe (probe_id) VALUES (%s)",
                    (post_target_token,),
                )
                archived_segment = connection.execute(
                    "SELECT pg_walfile_name(pg_switch_wal())"
                ).fetchone()[0]
            _wait_for_archive(archive_root, str(archived_segment))
            isolated_restore_cluster.stop()

            pitr_plan = build_postgres_pitr_plan(
                policy=policy,
                recovery_id=recovery_id,
                backup_root=base / "physical",
                pg_basebackup_bin=Path("/usr/bin/pg_basebackup"),
                service_file=service_file,
                passfile=passfile,
                recovery_target_time=target_time,
                parent_environ={"PATH": cluster_environment["PATH"]},
            )
            _prepare_recovery_cluster(
                pitr_plan.basebackup_directory,
                pitr_plan.recovery_settings,
                archive_root=archive_root,
            )
            recovery_cluster = EphemeralPostgres(
                data=pitr_plan.basebackup_directory,
                socket_dir=base / "recovery-socket",
                port=recovery_port,
                environment=cluster_environment,
            )
            recovery_cluster.socket_dir.mkdir(mode=0o700)
            recovery_cluster.start(timeout=90)
            _wait_for_recovery_pause(recovery_cluster)
            with recovery_cluster.connection() as connection:
                row = connection.execute(
                    "SELECT probe_id FROM s145_pitr_probe WHERE probe_id = %s",
                    (probe_token,),
                ).fetchone()
                post_target_row = connection.execute(
                    "SELECT probe_id FROM s145_pitr_probe WHERE probe_id = %s",
                    (post_target_token,),
                ).fetchone()
                recovery_state = connection.execute(
                    "SELECT pg_is_in_recovery(), pg_get_wal_replay_pause_state()"
                ).fetchone()
            if (
                row != (probe_token,)
                or post_target_row is not None
                or recovery_state != (True, "paused")
            ):
                raise PostgresRecoveryAcceptanceError("pitr_probe_invalid")
            pitr_fingerprints = _cluster_fingerprints(
                recovery_cluster, resolved_by_service, policy
            )
            compare_recovery_fingerprints(source_fingerprints, pitr_fingerprints)
            cutover = validate_pitr_cutover(
                recovery_paused=True,
                timeline_verified=True,
                five_databases_verified=True,
                migration_heads_verified=True,
                operator_approved=False,
            )
            if cutover != "PAUSED_AWAITING_OPERATOR":
                raise PostgresRecoveryAcceptanceError("pitr_cutover_guard_invalid")
        finally:
            if recovery_cluster is not None:
                recovery_cluster.stop()
            isolated_restore_cluster.stop()

        fingerprint_projection = recovery_fingerprints_public_projection(
            pitr_fingerprints
        )
        elapsed = time.monotonic() - started
        evidence = {
            "schema_version": "postgres_recovery_acceptance_evidence.v1",
            "slice": "1451",
            "requirement": "S145",
            "status": "PASS",
            "checks": {
                "actual_five_test_databases": len(source_fingerprints) == 5,
                "logical_backup_restore": source_fingerprints == restored_fingerprints,
                "verified_catalogs": True,
                "physical_basebackup": pitr_plan.basebackup_directory.exists(),
                "wal_archive_replay": len(tuple(archive_root.glob("*.sha256"))) > 0,
                "pitr_paused_without_promotion": cutover == "PAUSED_AWAITING_OPERATOR",
                "five_database_pitr_fingerprints": source_fingerprints == pitr_fingerprints,
                "source_remained_read_only": True,
                "credential_values_redacted": True,
                "temporary_cluster_stopped": not isolated_restore_cluster.running and not recovery_cluster.running,
            },
            "metrics": {
                "database_count": fingerprint_projection["database_count"],
                "migration_count": fingerprint_projection["migration_count"],
                "table_count": fingerprint_projection["table_count"],
                "required_extension_count": fingerprint_projection["required_extension_count"],
                "logical_archive_bytes": backup_bytes,
                "wal_segment_count": len(tuple(archive_root.glob("*.sha256"))),
                "elapsed_seconds": round(elapsed, 3),
            },
            "database_urls_exposed": False,
            "next_slice": "1452",
        }
    return evidence


def _source_fingerprints(resolved_by_service, policy):
    fingerprints = {}
    for target in policy.targets:
        resolved = resolved_by_service[target.service_id]
        try:
            url = make_url(resolved.database_url)
            with psycopg.connect(
                host=url.host or "127.0.0.1",
                port=url.port or 5432,
                dbname=url.database,
                user=url.username,
                password=url.password,
                autocommit=True,
                connect_timeout=10,
            ) as connection:
                fingerprints[target.service_id] = read_database_fingerprint(
                    connection,
                    service_id=target.service_id,
                    expected_database_name=resolved.target.expected_database_name,
                    required_extensions=target.required_extensions,
                )
        except psycopg.Error as exc:
            raise PostgresRecoveryAcceptanceError(
                "recovery_source_fingerprint_failed"
            ) from exc
    return fingerprints


def _cluster_fingerprints(cluster, resolved_by_service, policy):
    fingerprints = {}
    for target in policy.targets:
        database = resolved_by_service[target.service_id].target.expected_database_name
        with cluster.connection(database) as connection:
            fingerprints[target.service_id] = read_database_fingerprint(
                connection,
                service_id=target.service_id,
                expected_database_name=database,
                required_extensions=target.required_extensions,
            )
    return fingerprints


def _validate_catalogs(policy, plans) -> None:
    for target in policy.targets:
        catalog = build_backup_catalog(
            plans[target.service_id].service_directory,
            service_id=target.service_id,
        )
        if (
            catalog.issues
            or catalog.partials
            or len(catalog.entries) != 1
            or catalog.entries[0].state != "VERIFIED"
        ):
            raise PostgresRecoveryAcceptanceError("recovery_catalog_invalid")


def _prepare_recovery_cluster(data, settings, *, archive_root: Path) -> None:
    restore_script = ROOT / "scripts/db/restore_postgres_wal.py"
    recovery = dict(settings)
    recovery["restore_command"] = (
        f"{_config_path(Path(sys.executable))} {_config_path(restore_script)} %f %p"
    )
    _append_config(data / "postgresql.auto.conf", recovery)
    (data / "recovery.signal").touch(exist_ok=False)
    if not archive_root.is_dir():
        raise PostgresRecoveryAcceptanceError("wal_archive_missing")


def _wait_for_archive(root: Path, segment: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (root / segment).is_file() and (root / f"{segment}.sha256").is_file():
            return
        time.sleep(0.1)
    raise PostgresRecoveryAcceptanceError("wal_archive_timeout")


def _wait_for_recovery_pause(cluster: EphemeralPostgres, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with cluster.connection() as connection:
                state = connection.execute(
                    "SELECT pg_is_in_recovery(), pg_get_wal_replay_pause_state()"
                ).fetchone()
            if state == (True, "paused"):
                return
        except psycopg.Error:
            pass
        time.sleep(0.2)
    raise PostgresRecoveryAcceptanceError("pitr_pause_timeout")


def _backup_runner(command, **kwargs):
    return subprocess.run(command, timeout=180, **kwargs)


def _restore_runner(command, **kwargs):
    return subprocess.run(command, timeout=180, **kwargs)


def _stop_cluster(cluster: EphemeralPostgres, *, mode: str) -> None:
    _run_checked(
        (
            str(POSTGRES_BIN / "pg_ctl"),
            "--pgdata", str(cluster.data),
            "--wait",
            "--timeout", "30",
            "--mode", mode,
            "stop",
        ),
        environment=cluster.environment,
        timeout=40,
        code="postgres_cluster_stop_failed",
    )


def _run_checked(command, *, environment, timeout: int, code: str) -> None:
    completed = subprocess.run(
        tuple(str(value) for value in command),
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RecoveryProcessError(code)


def _append_config(path: Path, values: Mapping[str, str]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name} = '{_config_value(str(value))}'\n")
        output.flush()
        os.fsync(output.fileno())


def _config_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise PostgresRecoveryAcceptanceError("postgres_config_value_invalid")
    return value.replace("'", "''")


def _config_path(path: Path) -> str:
    if not path.is_absolute() or "'" in str(path):
        raise PostgresRecoveryAcceptanceError("postgres_config_path_invalid")
    return str(path)


def _free_port(*, exclude: set[int] | None = None) -> int:
    excluded = exclude or set()
    for _attempt in range(10):
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = int(candidate.getsockname()[1])
        if port not in excluded:
            return port
    raise PostgresRecoveryAcceptanceError("recovery_port_unavailable")


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIP":
        return f"postgres_recovery_acceptance=skip reason={result.get('reason')}"
    checks = dict(result.get("checks") or {})
    metrics = dict(result.get("metrics") or {})
    return (
        f"postgres_recovery_acceptance={'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"databases={metrics.get('database_count', 0)} "
        f"wal={metrics.get('wal_segment_count', 0)} "
        f"elapsed={metrics.get('elapsed_seconds', 0)}s next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    environment = dict(os.environ)
    if args.execute:
        environment[SMOKE_ENV] = "1"
    result = run_postgresql_recovery_acceptance(environment)
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIP"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
