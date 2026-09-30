from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_mo.provider_telemetry_persistence import (
    PROVIDER_TELEMETRY_CAPABILITIES,
    DurableProviderTelemetryRecord,
    ProviderTelemetryMutation,
)


class ProviderTelemetryRepositoryError(RuntimeError):
    pass


class SqlAlchemyDurableProviderTelemetryRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def apply(
        self,
        mutation: ProviderTelemetryMutation,
    ) -> DurableProviderTelemetryRecord:
        params = _mutation_params(mutation)
        session = self._session_factory()
        try:
            try:
                session.execute(text(_UPSERT_SQL), params)
                row = (
                    session.execute(
                        text(_SELECT_SQL + " WHERE telemetry_key = :telemetry_key"),
                        {"telemetry_key": params["telemetry_key"]},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise ProviderTelemetryRepositoryError(
                        "provider telemetry upsert did not return a durable record"
                    )
                record = DurableProviderTelemetryRecord.from_mapping(row)
                session.commit()
                return record
            except Exception:
                session.rollback()
                raise
        except ProviderTelemetryRepositoryError:
            raise
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise ProviderTelemetryRepositoryError(
                "provider telemetry persistence is unavailable"
            ) from exc
        finally:
            session.close()

    def list_records(
        self,
        *,
        capability: str | None = None,
    ) -> list[DurableProviderTelemetryRecord]:
        if capability is not None and capability not in PROVIDER_TELEMETRY_CAPABILITIES:
            raise ProviderTelemetryRepositoryError(
                "unsupported provider telemetry capability filter"
            )
        where = " WHERE capability = :capability" if capability is not None else ""
        params = {"capability": capability} if capability is not None else {}
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(
                            _SELECT_SQL
                            + where
                            + " ORDER BY capability ASC, deployment_id ASC"
                        ),
                        params,
                    )
                    .mappings()
                    .all()
                )
            return [DurableProviderTelemetryRecord.from_mapping(row) for row in rows]
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as exc:
            raise ProviderTelemetryRepositoryError(
                "provider telemetry persistence is unavailable"
            ) from exc

    def clear(self) -> int:
        session = self._session_factory()
        try:
            try:
                result = session.execute(text("DELETE FROM mo_provider_telemetry"))
                deleted = int(result.rowcount or 0)
                session.commit()
                return deleted
            except Exception:
                session.rollback()
                raise
        except SQLAlchemyError as exc:
            raise ProviderTelemetryRepositoryError(
                "provider telemetry persistence is unavailable"
            ) from exc
        finally:
            session.close()


def _mutation_params(mutation: ProviderTelemetryMutation) -> dict[str, Any]:
    params = mutation.to_params()
    params["telemetry_key"] = mutation.identity.storage_key()
    params["last_observed_at"] = (
        mutation.observed_at if mutation.request_increment else None
    )
    params["last_retry_at"] = (
        mutation.observed_at if mutation.retry_increment else None
    )
    return params


_SELECT_SQL = """
SELECT capability,
       request_shape,
       deployment_id,
       model_revision,
       request_count,
       success_count,
       failure_count,
       retryable_failure_count,
       degraded_count,
       attempt_count,
       retry_count,
       last_outcome,
       last_observed_at,
       last_latency_ms,
       last_status_code,
       last_error_code,
       last_failure_kind,
       last_upstream_status_code,
       last_retry_at,
       last_retry_delay_ms,
       last_retry_failure_kind
FROM mo_provider_telemetry
"""


_UPSERT_SQL = """
INSERT INTO mo_provider_telemetry (
    telemetry_key,
    capability,
    request_shape,
    deployment_id,
    model_revision,
    request_count,
    success_count,
    failure_count,
    retryable_failure_count,
    degraded_count,
    attempt_count,
    retry_count,
    last_outcome,
    last_observed_at,
    last_latency_ms,
    last_status_code,
    last_error_code,
    last_failure_kind,
    last_upstream_status_code,
    last_retry_at,
    last_retry_delay_ms,
    last_retry_failure_kind,
    created_at,
    updated_at
) VALUES (
    :telemetry_key,
    :capability,
    :request_shape,
    :deployment_id,
    :model_revision,
    :request_count,
    :success_count,
    :failure_count,
    :retryable_failure_count,
    :degraded_count,
    :attempt_count,
    :retry_count,
    :last_outcome,
    :last_observed_at,
    :last_latency_ms,
    :last_status_code,
    :last_error_code,
    :last_failure_kind,
    :last_upstream_status_code,
    :last_retry_at,
    :last_retry_delay_ms,
    :last_retry_failure_kind,
    :observed_at,
    :observed_at
)
ON CONFLICT (telemetry_key) DO UPDATE SET
    request_count = mo_provider_telemetry.request_count + excluded.request_count,
    success_count = mo_provider_telemetry.success_count + excluded.success_count,
    failure_count = mo_provider_telemetry.failure_count + excluded.failure_count,
    retryable_failure_count = mo_provider_telemetry.retryable_failure_count
        + excluded.retryable_failure_count,
    degraded_count = mo_provider_telemetry.degraded_count + excluded.degraded_count,
    attempt_count = mo_provider_telemetry.attempt_count + excluded.attempt_count,
    retry_count = mo_provider_telemetry.retry_count + excluded.retry_count,
    last_outcome = CASE
        WHEN excluded.request_count > 0 THEN excluded.last_outcome
        ELSE mo_provider_telemetry.last_outcome
    END,
    last_observed_at = CASE
        WHEN excluded.request_count > 0 THEN excluded.last_observed_at
        ELSE mo_provider_telemetry.last_observed_at
    END,
    last_latency_ms = CASE
        WHEN excluded.request_count > 0 THEN excluded.last_latency_ms
        ELSE mo_provider_telemetry.last_latency_ms
    END,
    last_status_code = CASE
        WHEN excluded.request_count > 0 THEN excluded.last_status_code
        ELSE mo_provider_telemetry.last_status_code
    END,
    last_error_code = CASE
        WHEN excluded.request_count > 0 THEN excluded.last_error_code
        ELSE mo_provider_telemetry.last_error_code
    END,
    last_failure_kind = CASE
        WHEN excluded.request_count > 0 THEN excluded.last_failure_kind
        ELSE mo_provider_telemetry.last_failure_kind
    END,
    last_upstream_status_code = CASE
        WHEN excluded.request_count > 0 THEN excluded.last_upstream_status_code
        ELSE mo_provider_telemetry.last_upstream_status_code
    END,
    last_retry_at = CASE
        WHEN excluded.retry_count > 0 THEN excluded.last_retry_at
        ELSE mo_provider_telemetry.last_retry_at
    END,
    last_retry_delay_ms = CASE
        WHEN excluded.retry_count > 0 THEN excluded.last_retry_delay_ms
        ELSE mo_provider_telemetry.last_retry_delay_ms
    END,
    last_retry_failure_kind = CASE
        WHEN excluded.retry_count > 0 THEN excluded.last_retry_failure_kind
        ELSE mo_provider_telemetry.last_retry_failure_kind
    END,
    updated_at = excluded.updated_at
"""
