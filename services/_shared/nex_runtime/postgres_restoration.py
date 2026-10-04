from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import re
from typing import Any

import psycopg

from .database import psycopg_database_url
from .postgres_orchestration import POSTGRES_SERVICE_ORDER
from .postgres_targets import (
    PostgresTargetConfigError,
    ResolvedPostgresTestTarget,
    resolve_postgres_test_targets,
)


RESTORATION_PHASES = ("WRITE", "RESTORE", "CLEANUP", "ABSENCE")
SENTINEL_EVENT_TYPE = "platform.postgres.restart.sentinel"
_SAFE_RUN_ID = re.compile(r"^s133-[a-z0-9][a-z0-9-]{0,62}$")


class PostgresRestorationError(RuntimeError):
    def __init__(self, failure_code: str, service_id: str | None = None) -> None:
        self.failure_code = failure_code
        self.service_id = service_id
        super().__init__(failure_code)


@dataclass(frozen=True)
class PostgresRestorationSentinel:
    run_id: str
    service_id: str
    event_id: str


@dataclass(frozen=True)
class PostgresRestorationBatchResult:
    phase: str
    service_count: int
    record_count: int

    def to_public_projection(self) -> dict[str, Any]:
        return {
            "schema_version": "platform_postgres_restoration_batch.v1",
            "requirement": "S133",
            "profile": "test",
            "phase": self.phase,
            "service_count": self.service_count,
            "record_count": self.record_count,
        }


SentinelOperator = Callable[
    [ResolvedPostgresTestTarget, str, PostgresRestorationSentinel], bool
]
ConnectFactory = Callable[..., Any]


class PlatformPostgresRestorationStore:
    def __init__(
        self,
        targets: tuple[ResolvedPostgresTestTarget, ...],
        *,
        operator: SentinelOperator,
    ) -> None:
        self._targets = targets
        self._operator = operator

    @classmethod
    def build(
        cls,
        environ: Mapping[str, str],
        *,
        connect: ConnectFactory = psycopg.connect,
        operator: SentinelOperator | None = None,
    ) -> PlatformPostgresRestorationStore:
        try:
            targets = resolve_postgres_test_targets(
                environ, service_ids=POSTGRES_SERVICE_ORDER
            )
        except PostgresTargetConfigError as exc:
            raise PostgresRestorationError("configuration_invalid") from exc
        selected = operator or (
            lambda target, phase, sentinel: _execute_postgres_sentinel_operation(
                target,
                phase,
                sentinel,
                connect=connect,
            )
        )
        return cls(targets, operator=selected)

    def write(self, run_id: str) -> PostgresRestorationBatchResult:
        sentinels = self._sentinels(run_id)
        completed: list[
            tuple[ResolvedPostgresTestTarget, PostgresRestorationSentinel]
        ] = []
        try:
            for target, sentinel in zip(self._targets, sentinels, strict=True):
                if not self._operator(target, "WRITE", sentinel):
                    raise ValueError("sentinel_not_written")
                completed.append((target, sentinel))
        except Exception as exc:
            for target, sentinel in reversed(completed):
                try:
                    self._operator(target, "CLEANUP", sentinel)
                except Exception:
                    continue
            service_id = sentinels[len(completed)].service_id
            raise PostgresRestorationError(
                "sentinel_write_failed", service_id
            ) from exc
        return self._result("WRITE", len(completed))

    def restore(self, run_id: str) -> PostgresRestorationBatchResult:
        return self._run_phase(run_id, "RESTORE", "sentinel_restore_failed")

    def cleanup(self, run_id: str) -> PostgresRestorationBatchResult:
        return self._run_phase(run_id, "CLEANUP", "sentinel_cleanup_failed")

    def confirm_absence(self, run_id: str) -> PostgresRestorationBatchResult:
        return self._run_phase(run_id, "ABSENCE", "sentinel_cleanup_incomplete")

    def _run_phase(
        self,
        run_id: str,
        phase: str,
        failure_code: str,
    ) -> PostgresRestorationBatchResult:
        sentinels = self._sentinels(run_id)
        completed = 0
        for target, sentinel in zip(self._targets, sentinels, strict=True):
            try:
                if not self._operator(target, phase, sentinel):
                    raise ValueError("sentinel_operation_failed")
            except Exception as exc:
                raise PostgresRestorationError(
                    failure_code, sentinel.service_id
                ) from exc
            completed += 1
        return self._result(phase, completed)

    def _sentinels(
        self, run_id: str
    ) -> tuple[PostgresRestorationSentinel, ...]:
        if not isinstance(run_id, str) or not _SAFE_RUN_ID.fullmatch(run_id):
            raise PostgresRestorationError("run_id_invalid")
        return tuple(
            PostgresRestorationSentinel(
                run_id=run_id,
                service_id=target.target.service_id,
                event_id=f"{run_id}:{target.target.service_id}",
            )
            for target in self._targets
        )

    def _result(self, phase: str, record_count: int) -> PostgresRestorationBatchResult:
        return PostgresRestorationBatchResult(
            phase=phase,
            service_count=len(self._targets),
            record_count=record_count,
        )


def _execute_postgres_sentinel_operation(
    target: ResolvedPostgresTestTarget,
    phase: str,
    sentinel: PostgresRestorationSentinel,
    *,
    connect: ConnectFactory,
) -> bool:
    if phase not in RESTORATION_PHASES:
        raise ValueError("restoration_phase_invalid")
    with connect(
        psycopg_database_url(target.database_url), autocommit=False
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            if cursor.fetchone() != (
                target.target.expected_database_name,
                target.target.expected_role_name,
            ):
                raise ValueError("database_identity_mismatch")
            if phase == "WRITE":
                cursor.execute(
                    """
                    INSERT INTO service_operational_events (
                        event_id, service_id, event_type, severity, message, details
                    ) VALUES (%s, %s, %s, 'INFO', %s, %s::jsonb)
                    """,
                    (
                        sentinel.event_id,
                        sentinel.service_id,
                        SENTINEL_EVENT_TYPE,
                        "S133 restart restoration sentinel",
                        json.dumps(
                            {"run_id": sentinel.run_id, "restart_iteration": 0},
                            sort_keys=True,
                        ),
                    ),
                )
                connection.commit()
                return cursor.rowcount == 1
            if phase == "RESTORE":
                cursor.execute(
                    """
                    SELECT service_id, event_type, severity, message, details
                    FROM service_operational_events
                    WHERE event_id = %s
                    """,
                    (sentinel.event_id,),
                )
                return cursor.fetchone() == (
                    sentinel.service_id,
                    SENTINEL_EVENT_TYPE,
                    "INFO",
                    "S133 restart restoration sentinel",
                    {"run_id": sentinel.run_id, "restart_iteration": 0},
                )
            if phase == "CLEANUP":
                cursor.execute(
                    "DELETE FROM service_operational_events WHERE event_id = %s",
                    (sentinel.event_id,),
                )
                connection.commit()
                return cursor.rowcount == 1
            cursor.execute(
                "SELECT count(*) FROM service_operational_events WHERE event_id = %s",
                (sentinel.event_id,),
            )
            return cursor.fetchone() == (0,)
