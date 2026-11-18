from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Engine


def cleanup_wc_tenant(
    engine: Engine, *, tenant_id: str, worker_ids: Sequence[str]
) -> dict[str, int]:
    deleted = 0
    with engine.begin() as connection:
        work_item_ids = list(
            connection.execute(
                text(
                    "SELECT work_item_id::text FROM wc_work_item "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalars()
        )
        event_ids = list(
            connection.execute(
                text(
                    "SELECT event_id::text FROM wc_event_outbox "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalars()
        )
        request_ids = work_item_ids + event_ids
        if request_ids:
            deleted += int(
                connection.execute(
                    text(
                        "DELETE FROM service_jobs WHERE request_id = ANY(:request_ids)"
                    ),
                    {"request_ids": request_ids},
                ).rowcount
                or 0
            )
        for table in (
            "wc_event_outbox",
            "wc_claim",
            "wc_assignment",
            "wc_routing_decision",
            "wc_work_item",
        ):
            deleted += int(
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
        if worker_ids:
            deleted += int(
                connection.execute(
                    text(
                        "DELETE FROM service_worker_heartbeats "
                        "WHERE service_id = 'nex-wc' AND worker_id = ANY(:worker_ids)"
                    ),
                    {"worker_ids": list(worker_ids)},
                ).rowcount
                or 0
            )
    with engine.connect() as connection:
        remaining = int(
            connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one()
        )
    return {"wc_deleted": deleted, "wc_remaining": remaining}


def cleanup_ae_tenant(engine: Engine, *, tenant_id: str) -> dict[str, int]:
    return _cleanup_tenant_tables(
        engine,
        tenant_id=tenant_id,
        tables=("ae_claim_handoff_inbox", "ae_agent_execution", "ae_agent_identity"),
        prefix="ae",
    )


def cleanup_oa_tenant(engine: Engine, *, tenant_id: str) -> dict[str, int]:
    return _cleanup_tenant_tables(
        engine,
        tenant_id=tenant_id,
        tables=(
            "oa_authz_events",
            "oa_group_roles",
            "oa_group_members",
            "oa_roles",
            "oa_groups",
            "oa_user_sessions",
            "oa_tenant_memberships",
            "oa_subjects",
            "oa_tenants",
        ),
        prefix="oa",
    )


def _cleanup_tenant_tables(
    engine: Engine,
    *,
    tenant_id: str,
    tables: Sequence[str],
    prefix: str,
) -> dict[str, int]:
    deleted = 0
    with engine.begin() as connection:
        for table in tables:
            deleted += int(
                connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                or 0
            )
    with engine.connect() as connection:
        remaining = sum(
            int(
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )
            for table in tables
        )
    return {f"{prefix}_deleted": deleted, f"{prefix}_remaining": remaining}
