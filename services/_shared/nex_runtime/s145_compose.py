from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any

import yaml

from .postgres_backup import build_logical_backup_plan, execute_logical_backup
from .postgres_backup_catalog import build_backup_catalog
from .postgres_backup_worker import run_postgres_backup_worker
from .postgres_resilience import load_postgres_resilience_policy


S145_COMPOSE_SCHEMA_VERSION = "s145_postgres_operations_compose.v1"
S145_OVERRIDE_PATH = "deployment/compose/s145-postgres-operations.override.yaml"
S145_CONTAINERFILE_PATH = "deployment/oci/postgres-operator.Containerfile"
POSTGRES_BASE_DIGEST = (
    "postgres:16.9-bookworm@"
    "sha256:253815cf7579ffa05e1673d92e78d37273e61be0e4414e9a1449337d7925be94"
)


class S145ComposeError(ValueError):
    pass


def validate_s145_compose_assets(root: Path) -> dict[str, Any]:
    try:
        compose_text = (root / S145_OVERRIDE_PATH).read_text(encoding="utf-8")
        compose = yaml.safe_load(compose_text)
        containerfile = (root / S145_CONTAINERFILE_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise S145ComposeError("S145 Compose assets are unreadable") from exc
    if not isinstance(compose, Mapping):
        raise S145ComposeError("S145 Compose document is invalid")
    services = compose.get("services")
    if not isinstance(services, Mapping) or set(services) != {
        "postgres-backup-operator"
    }:
        raise S145ComposeError("S145 operator service coverage drift")
    operator = services["postgres-backup-operator"]
    if not isinstance(operator, Mapping):
        raise S145ComposeError("S145 operator service is invalid")
    forbidden = ("/var/run/docker.sock", "privileged: true", "network_mode: host")
    if any(marker in compose_text for marker in forbidden):
        raise S145ComposeError("S145 operator privilege boundary drift")
    if (
        operator.get("profiles") != ["postgres-operations"]
        or operator.get("user") != "65532:65532"
        or operator.get("read_only") is not True
        or operator.get("cap_drop") != ["ALL"]
        or operator.get("security_opt") != ["no-new-privileges:true"]
        or operator.get("restart") != "no"
    ):
        raise S145ComposeError("S145 operator hardening drift")
    image = str(operator.get("image") or "")
    if "${NEX_POSTGRES_OPERATOR_IMAGE:?" not in image:
        raise S145ComposeError("S145 operator image is not immutable-gated")
    environment = operator.get("environment")
    required_environment = {
        "NEX_POSTGRES_BACKUP_ROOT": "/var/lib/nex-backup",
        "NEX_POSTGRES_BACKUP_STATE_ROOT": "/var/lib/nex-state",
        "NEX_POSTGRES_WAL_ARCHIVE_ROOT": "/var/lib/nex-backup/wal",
        "NEX_POSTGRES_SERVICE_FILE_SOURCE": "/run/secrets/postgres_backup_services",
        "NEX_POSTGRES_PASSFILE_SOURCE": "/run/secrets/postgres_backup_passfile",
        "NEX_POSTGRES_SEPARATE_MOUNT_VERIFIED": "1",
    }
    if not isinstance(environment, Mapping) or dict(environment) != required_environment:
        raise S145ComposeError("S145 operator environment drift")
    volumes = operator.get("volumes")
    if not isinstance(volumes, list) or len(volumes) != 2:
        raise S145ComposeError("S145 operator storage mount drift")
    targets = {
        item.get("target")
        for item in volumes
        if isinstance(item, Mapping) and item.get("type") == "bind"
    }
    if targets != {"/var/lib/nex-backup", "/var/lib/nex-state"}:
        raise S145ComposeError("S145 operator storage mount drift")
    if operator.get("secrets") != [
        "postgres_backup_services",
        "postgres_backup_passfile",
    ]:
        raise S145ComposeError("S145 operator credential mount drift")
    secrets = compose.get("secrets")
    if not isinstance(secrets, Mapping) or set(secrets) != {
        "postgres_backup_services",
        "postgres_backup_passfile",
    }:
        raise S145ComposeError("S145 operator secret definition drift")
    if compose.get("networks") != {"service": {"driver": "bridge"}}:
        raise S145ComposeError("S145 operator network definition drift")
    container_markers = (
        f"ARG POSTGRES_BASE_IMAGE={POSTGRES_BASE_DIGEST}",
        "FROM ${NEX_PYTHON_RUNTIME_IMAGE} AS python-runtime",
        'io.nex-platform.artifact-class="postgres-recovery-tool"',
        "USER 65532:65532",
        'ENTRYPOINT ["python", "/app/scripts/db/run_postgres_backup_operator.py"]',
    )
    if any(marker not in containerfile for marker in container_markers):
        raise S145ComposeError("S145 operator Containerfile drift")
    return {
        "schema_version": S145_COMPOSE_SCHEMA_VERSION,
        "state": "VALID",
        "orchestrator": "docker-compose-single-host",
        "profile": "postgres-operations",
        "operator_service_count": 1,
        "bind_mount_count": 2,
        "credential_source_count": 2,
        "postgres_major": 16,
        "non_root": True,
        "application_release_set_changed": False,
    }


def run_deterministic_backup_rehearsal(root: Path) -> dict[str, Any]:
    policy = load_postgres_resilience_policy(root / "deployment/postgres/s145-policy.yaml")
    with tempfile.TemporaryDirectory(prefix="nex-s145-compose-") as temp:
        base = Path(temp)
        backup_root = base / "backup"
        service_directories = tuple(
            backup_root / target.service_id for target in policy.targets
        )
        times = iter(
            datetime(2026, 10, 8, 0, 0, second, tzinfo=timezone.utc)
            for second in range(40)
        )

        def executor(_attempt: int) -> dict[str, str]:
            states: dict[str, str] = {}
            for target in policy.targets:
                plan = build_logical_backup_plan(
                    policy=policy,
                    target=target,
                    backup_id="20261008T000000Z-1234abcd",
                    backup_root=backup_root,
                    pg_dump_bin=Path("/usr/bin/pg_dump"),
                    service_file=base / "pg_service.conf",
                    passfile=base / "pgpass",
                    parent_environ={"PATH": "/usr/bin"},
                )

                def runner(_command, **kwargs):
                    kwargs["stdout"].write(f"PGDMP-{target.service_id}".encode())
                    return SimpleNamespace(returncode=0)

                execute_logical_backup(plan, runner=runner, clock=lambda: next(times))
                states[target.service_id] = "CREATED"
            return states

        result = run_postgres_backup_worker(
            run_id="20261008T000000Z-1234abcd",
            state_root=base / "state",
            service_directories=service_directories,
            executor=executor,
            clock=lambda: next(times),
        )
        catalogs = tuple(
            build_backup_catalog(directory, service_id=target.service_id)
            for directory, target in zip(service_directories, policy.targets, strict=True)
        )
        if result.state != "SUCCEEDED" or any(
            len(catalog.entries) != 1 or catalog.issues
            for catalog in catalogs
        ):
            raise S145ComposeError("S145 deterministic backup rehearsal failed")
        return {
            "schema_version": "s145_deterministic_backup_rehearsal.v1",
            "state": "PASS",
            "service_count": len(catalogs),
            "archive_count": sum(len(catalog.entries) for catalog in catalogs),
            "attempt_count": result.attempt_count,
            "credential_values_persisted": False,
            "actual_postgres_contacted": False,
        }
