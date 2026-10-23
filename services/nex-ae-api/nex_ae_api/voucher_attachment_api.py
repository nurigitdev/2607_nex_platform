from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from nex_runtime import problem_response, request_id_from_headers, trace_id_from_headers
from starlette.concurrency import run_in_threadpool

from .oa_session_client import OaUserSessionClient
from .route_auth import AeFacadeRouteAuthContext, authorize_ae_facade_route_request
from .voucher_attachment_storage import (
    VoucherAttachmentObjectGateway,
    VoucherAttachmentStorageError,
)
from .voucher_attachments import (
    ATTACHMENT_BATCH_SCHEMA_VERSION,
    SqlAlchemyVoucherAttachmentRepository,
    VoucherAttachmentPersistenceError,
)


def register_voucher_attachment_routes(
    app: FastAPI,
    *,
    repository: SqlAlchemyVoucherAttachmentRepository | None,
    gateway: VoucherAttachmentObjectGateway | None,
    oa_session_client: OaUserSessionClient | None = None,
    session_mode: str | None = None,
) -> None:
    app.state.ae_voucher_attachment_repository = repository
    app.state.ae_voucher_attachment_gateway = gateway

    @app.post("/api/v1/voucher-attachments/batches", response_model=None)
    def create_batch(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = _authorize_browser(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        if repository is None:
            return _unavailable(request, "Attachment persistence is unavailable.")
        owner = auth.browser_context
        assert owner is not None
        interaction_id = payload.get("interaction_id")
        try:
            saved = repository.create_batch(
                {
                    "schema_version": ATTACHMENT_BATCH_SCHEMA_VERSION,
                    "attachment_batch_id": payload.get("attachment_batch_id")
                    or str(uuid4()),
                    "tenant_id": owner.tenant_id,
                    "owner_subject_ref": {
                        "type": "oa.user",
                        "id": owner.user_id,
                    },
                    "conversation_id": payload.get("conversation_id"),
                    "interaction_id": interaction_id,
                    "trace": {
                        "trace_id": trace_id_from_headers(request),
                        "correlation_id": request_id_from_headers(request),
                        "causation_id": interaction_id,
                    },
                }
            )
        except VoucherAttachmentPersistenceError as exc:
            return _problem(request, exc)
        return JSONResponse(status_code=201, content=saved)

    @app.get(
        "/api/v1/voucher-attachments/batches/{attachment_batch_id}",
        response_model=None,
    )
    def get_batch(
        attachment_batch_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = _authorize_browser(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        if repository is None:
            return _unavailable(request, "Attachment persistence is unavailable.")
        try:
            return _owned_batch(repository, auth, attachment_batch_id)
        except (
            VoucherAttachmentPersistenceError,
            VoucherAttachmentStorageError,
        ) as exc:
            return _problem(request, exc)

    @app.post(
        "/api/v1/voucher-attachments/batches/{attachment_batch_id}/items",
        response_model=None,
    )
    async def upload_item(
        attachment_batch_id: str,
        request: Request,
        file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency marker
        attachment_id: str | None = Form(default=None),
        authorization: str | None = Header(default=None),
    ):
        auth = _authorize_browser(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        if repository is None or gateway is None:
            return _unavailable(request, "Attachment storage is unavailable.")
        owner = auth.browser_context
        assert owner is not None
        try:
            _owned_batch(repository, auth, attachment_batch_id)
            item_id = attachment_id or str(uuid4())
            size = file.size
            registered = repository.register_item(
                {
                    "tenant_id": owner.tenant_id,
                    "attachment_batch_id": attachment_batch_id,
                    "attachment_id": item_id,
                    "display_name": file.filename,
                    "media_type": file.content_type,
                    "size_bytes": size,
                }
            )
            replay = registered["state"] in {"READY", "LOCKED"}
            await file.seek(0)
            resolved = await run_in_threadpool(
                gateway.publish,
                tenant_id=owner.tenant_id,
                attachment_batch_id=attachment_batch_id,
                attachment_id=item_id,
                source=file.file,
            )
            batch = repository.get_batch(
                tenant_id=owner.tenant_id,
                attachment_batch_id=attachment_batch_id,
            )
        except (
            VoucherAttachmentPersistenceError,
            VoucherAttachmentStorageError,
        ) as exc:
            return _problem(request, exc)
        return JSONResponse(
            status_code=200 if replay else 201,
            content={
                "attachment_batch_id": attachment_batch_id,
                "attachment": next(
                    item for item in batch["items"] if item["attachment_id"] == item_id
                ),
                "resolution": resolved,
            },
        )

    @app.delete(
        "/api/v1/voucher-attachments/batches/{attachment_batch_id}/items/"
        "{attachment_id}",
        response_model=None,
    )
    def remove_item(
        attachment_batch_id: str,
        attachment_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = _authorize_browser(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        if repository is None or gateway is None:
            return _unavailable(request, "Attachment storage is unavailable.")
        owner = auth.browser_context
        assert owner is not None
        try:
            _owned_batch(repository, auth, attachment_batch_id)
            removed = gateway.remove(
                tenant_id=owner.tenant_id,
                attachment_batch_id=attachment_batch_id,
                attachment_id=attachment_id,
            )
        except (
            VoucherAttachmentPersistenceError,
            VoucherAttachmentStorageError,
        ) as exc:
            return _problem(request, exc)
        return removed

    @app.post(
        "/api/v1/voucher-attachments/batches/{attachment_batch_id}/finalize",
        response_model=None,
    )
    def finalize_batch(
        attachment_batch_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = _authorize_browser(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        if repository is None:
            return _unavailable(request, "Attachment persistence is unavailable.")
        owner = auth.browser_context
        assert owner is not None
        try:
            _owned_batch(repository, auth, attachment_batch_id)
            return repository.finalize_batch(
                tenant_id=owner.tenant_id,
                attachment_batch_id=attachment_batch_id,
            )
        except (
            VoucherAttachmentPersistenceError,
            VoucherAttachmentStorageError,
        ) as exc:
            return _problem(request, exc)

    @app.post(
        "/api/v1/voucher-attachments/batches/{attachment_batch_id}/lock",
        response_model=None,
    )
    def lock_batch_manifest(
        attachment_batch_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth = _authorize_browser(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        if repository is None:
            return _unavailable(request, "Attachment persistence is unavailable.")
        owner = auth.browser_context
        assert owner is not None
        try:
            _owned_batch(repository, auth, attachment_batch_id)
            return repository.lock_manifest(
                tenant_id=owner.tenant_id,
                attachment_batch_id=attachment_batch_id,
            )
        except (
            VoucherAttachmentPersistenceError,
            VoucherAttachmentStorageError,
        ) as exc:
            return _problem(request, exc)

    @app.get(
        "/api/v1/voucher-attachments/batches/{attachment_batch_id}/items/"
        "{attachment_id}/content",
        response_model=None,
    )
    def get_item_content(
        attachment_batch_id: str,
        attachment_id: str,
        request: Request,
        download: bool = Query(default=False),
        tenant_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ):
        auth = authorize_ae_facade_route_request(
            request,
            authorization,
            oa_session_client=oa_session_client,
            session_mode=session_mode,
        )
        if isinstance(auth, JSONResponse):
            return auth
        if repository is None or gateway is None:
            return _unavailable(request, "Attachment storage is unavailable.")
        try:
            if auth.browser_context is not None:
                batch = _owned_batch(repository, auth, attachment_batch_id)
                owner = auth.browser_context
                resolved_tenant = owner.tenant_id
                item = _batch_item(batch, attachment_id)
                opened = gateway.open_for_owner(
                    tenant_id=resolved_tenant,
                    owner_subject_id=owner.user_id,
                    object_ref=str(item["object_ref"]),
                )
            else:
                claims = auth.service_claims
                if claims is None or tenant_id is None:
                    raise _forbidden("Attachment review authority is required.")
                batch = repository.get_batch(
                    tenant_id=tenant_id,
                    attachment_batch_id=attachment_batch_id,
                )
                if batch is None:
                    raise _not_found("Voucher attachment batch was not found.")
                item = _batch_item(batch, attachment_id)
                opened = gateway.open_for_service(
                    requester_service=claims.service_id,
                    tenant_id=tenant_id,
                    object_ref=str(item["object_ref"]),
                )
        except (
            VoucherAttachmentPersistenceError,
            VoucherAttachmentStorageError,
        ) as exc:
            return _problem(request, exc)
        disposition = "attachment" if download else "inline"
        encoded_name = quote(opened.display_name, safe="")
        return StreamingResponse(
            _stream_and_close(opened.source),
            media_type=opened.media_type,
            headers={
                "Content-Length": str(opened.size_bytes),
                "Content-Disposition": (
                    f"{disposition}; filename*=UTF-8''{encoded_name}"
                ),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )


def _authorize_browser(
    request: Request,
    authorization: str | None,
    *,
    oa_session_client: OaUserSessionClient | None,
    session_mode: str | None,
) -> AeFacadeRouteAuthContext | JSONResponse:
    auth = authorize_ae_facade_route_request(
        request,
        authorization,
        oa_session_client=oa_session_client,
        session_mode=session_mode,
    )
    if isinstance(auth, JSONResponse):
        return auth
    if auth.browser_context is None:
        return problem_response(
            request,
            status_code=403,
            error_code="ae.voucher_attachment.browser_user_required",
            title="Voucher attachment access denied",
            detail="An authenticated browser user is required.",
        )
    return auth


def _owned_batch(
    repository: SqlAlchemyVoucherAttachmentRepository,
    auth: AeFacadeRouteAuthContext,
    attachment_batch_id: str,
) -> dict[str, Any]:
    owner = auth.browser_context
    if owner is None:
        raise _forbidden("Voucher attachment owner authority is required.")
    batch = repository.get_batch(
        tenant_id=owner.tenant_id,
        attachment_batch_id=attachment_batch_id,
    )
    if batch is None or batch["owner_subject_ref"]["id"] != owner.user_id:
        raise _not_found("Voucher attachment batch was not found.")
    return batch


def _batch_item(batch: dict[str, Any], attachment_id: str) -> dict[str, Any]:
    item = next(
        (value for value in batch["items"] if value["attachment_id"] == attachment_id),
        None,
    )
    if item is None or item["state"] not in {"READY", "LOCKED"}:
        raise _not_found("Voucher attachment item was not found.")
    return item


def _stream_and_close(source: Any) -> Iterator[bytes]:
    try:
        while chunk := source.read(256 * 1024):
            yield chunk
    finally:
        source.close()


def _problem(
    request: Request,
    exc: VoucherAttachmentPersistenceError | VoucherAttachmentStorageError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Voucher attachment request failed",
        detail=exc.detail,
        retryable=exc.retryable,
    )


def _unavailable(request: Request, detail: str) -> JSONResponse:
    return problem_response(
        request,
        status_code=503,
        error_code="ae.voucher_attachment.unavailable",
        title="Voucher attachment service unavailable",
        detail=detail,
        retryable=True,
    )


def _not_found(detail: str) -> VoucherAttachmentStorageError:
    return VoucherAttachmentStorageError("ae.voucher_attachment.not_found", detail, 404)


def _forbidden(detail: str) -> VoucherAttachmentStorageError:
    return VoucherAttachmentStorageError("ae.voucher_attachment.forbidden", detail, 403)
