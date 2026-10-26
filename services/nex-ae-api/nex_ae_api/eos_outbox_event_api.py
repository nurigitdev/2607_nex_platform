from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    OperationalEventError,
    OperationalEventStore,
    build_operational_event,
    problem_response,
)
from nex_runtime.semantic_hashes import validate_hash_ref

from nex_ae_api.route_auth import authorize_ae_internal_service_request


class EosOutboxEventAdmissionError(ValueError):
    def __init__(self, error_code: str, detail: str, status_code: int = 400) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def register_eos_outbox_event_routes(
    app: FastAPI, *, store: OperationalEventStore
) -> None:
    @app.post("/internal/v1/eos-outbox-events", response_model=None)
    def ingest_eos_outbox_event(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = authorize_ae_internal_service_request(
            request,
            authorization,
            allowed_service_ids=("nex-eos",),
            error_code="AE_EOS_OUTBOX_CALLER_DENIED",
            title="AE EOS outbox caller denied",
            detail="Only nex-eos may publish an EOS outbox event.",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        try:
            receipt, created = admit_eos_outbox_event(store, payload)
        except EosOutboxEventAdmissionError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="AE EOS outbox admission failed",
                detail=exc.detail,
                retryable=False,
            )
        except OperationalEventError:
            return problem_response(
                request,
                status_code=503,
                error_code="ae.eos_outbox_event_store_unavailable",
                title="AE EOS outbox admission failed",
                detail="EOS outbox event persistence is unavailable.",
                retryable=True,
            )
        return JSONResponse(receipt, status_code=201 if created else 200)


def admit_eos_outbox_event(
    store: OperationalEventStore, payload: object
) -> tuple[dict[str, Any], bool]:
    normalized = _normalize(payload)
    existing = store.get_event(normalized["event_id"])
    if existing is not None:
        details = existing.get("details") or {}
        if (
            existing.get("event_type") != normalized["event_type"]
            or details.get("event_payload_hash") != normalized["event_payload_hash"]
            or details.get("business_operation_id")
            != normalized["business_operation_id"]
            or details.get("tenant_id") != normalized["tenant_id"]
        ):
            raise EosOutboxEventAdmissionError(
                "ae.eos_outbox_event_idempotency_conflict",
                "EOS outbox event identity is already bound to different lineage.",
                409,
            )
        return _receipt(normalized), False
    event = build_operational_event(
        service_id="nex-ae-api",
        event_type=normalized["event_type"],
        severity="INFO",
        message="EOS authoritative business event published.",
        request_id=normalized["event_id"],
        subject_ref={
            "type": "EOS_BUSINESS_OPERATION",
            "id": normalized["business_operation_id"],
        },
        details={
            "tenant_id": normalized["tenant_id"],
            "business_operation_id": normalized["business_operation_id"],
            "event_payload_hash": normalized["event_payload_hash"],
            "payload_bytes_included": False,
        },
        event_id=normalized["event_id"],
    )
    store.append(event)
    return _receipt(normalized), True


def _normalize(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "event_id",
        "tenant_id",
        "business_operation_id",
        "event_type",
        "event_payload_hash",
    }:
        raise _invalid("EOS outbox event metadata is invalid.")
    normalized = {
        name: _required(value.get(name), name)
        for name in (
            "event_id",
            "tenant_id",
            "business_operation_id",
            "event_type",
            "event_payload_hash",
        )
    }
    normalized["event_id"] = _uuid(normalized["event_id"], "event_id")
    normalized["business_operation_id"] = _uuid(
        normalized["business_operation_id"], "business_operation_id"
    )
    try:
        normalized["event_payload_hash"] = validate_hash_ref(
            normalized["event_payload_hash"]
        )
    except ValueError as exc:
        raise _invalid("EOS outbox event payload hash is invalid.") from exc
    return normalized


def _receipt(event: dict[str, str]) -> dict[str, str]:
    return {
        "schema_version": "ae_eos_outbox_receipt.v1",
        "event_id": event["event_id"],
        "event_payload_hash": event["event_payload_hash"],
        "receipt_ref": f"AE:OPERATIONAL_EVENT:{event['event_id']}",
    }


def _required(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
    ):
        raise _invalid(f"EOS outbox {field} is invalid.")
    return value


def _uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _invalid(f"EOS outbox {field} is invalid.") from exc


def _invalid(detail: str) -> EosOutboxEventAdmissionError:
    return EosOutboxEventAdmissionError("ae.eos_outbox_event_invalid", detail)
