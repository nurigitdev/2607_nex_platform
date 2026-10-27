from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .work_assets import SqlAlchemyWorkAssetRepository, WorkAssetError
from .work_evidence import SqlAlchemyWorkEvidenceRepository, WorkEvidenceError

WA_EVIDENCE_READ_SCOPE = "work:evidence:read"
WA_EVIDENCE_DETAIL_READ_SCOPE = "work:evidence:detail:read"
WA_READ_CALLERS = frozenset({"nex-ae-api", "nex-ag"})


@dataclass(frozen=True)
class WaReadError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


class WaCoreReadService:
    def __init__(
        self,
        evidence_repository: SqlAlchemyWorkEvidenceRepository,
        asset_repository: SqlAlchemyWorkAssetRepository,
    ) -> None:
        self._evidence_repository = evidence_repository
        self._asset_repository = asset_repository

    def get_evidence(self, tenant_id: str, work_evidence_id: str) -> dict[str, Any]:
        try:
            record = self._evidence_repository.get(tenant_id, work_evidence_id)
        except WorkEvidenceError as exc:
            raise WaReadError(exc.error_code, exc.detail, exc.status_code) from exc
        if record is None:
            raise WaReadError(
                "WA_EVIDENCE_NOT_FOUND", "WorkEvidence was not found", 404
            )
        return {"schema_version": "wa_work_evidence.v1", **record.to_dict()}

    def get_asset(self, tenant_id: str, work_asset_id: str) -> dict[str, Any]:
        try:
            record = self._asset_repository.get(tenant_id, work_asset_id)
        except WorkAssetError as exc:
            raise WaReadError(exc.error_code, exc.detail, exc.status_code) from exc
        if record is None:
            raise WaReadError("WA_ASSET_NOT_FOUND", "WorkAsset was not found", 404)
        return {
            "schema_version": "wa_work_asset.v1",
            **record.to_dict(),
            "bindings": [
                {
                    "work_evidence_id": item.work_evidence_id,
                    "binding_role": item.binding_role,
                    "created_at": item.created_at,
                }
                for item in record.bindings
            ],
        }

    def get_asset_evidence(
        self, tenant_id: str, work_asset_id: str
    ) -> dict[str, Any]:
        asset = self.get_asset(tenant_id, work_asset_id)
        items: list[dict[str, Any]] = []
        for binding in asset["bindings"]:
            evidence = self.get_evidence(tenant_id, binding["work_evidence_id"])
            items.append(
                {
                    "binding_role": binding["binding_role"],
                    "binding_created_at": binding["created_at"],
                    "evidence": evidence,
                }
            )
        items.sort(
            key=lambda item: (
                0 if item["binding_role"] == "PRIMARY" else 1,
                item["evidence"]["occurred_at"],
                item["evidence"]["work_evidence_id"],
            )
        )
        return {
            "schema_version": "wa_work_asset_evidence_lineage.v1",
            "tenant_id": asset["tenant_id"],
            "work_asset_id": asset["work_asset_id"],
            "items": items,
        }


def register_core_read_routes(app: FastAPI) -> None:
    @app.get(
        "/internal/v1/work-evidence/{work_evidence_id}",
        response_model=None,
        operation_id="getWaWorkEvidence",
    )
    def get_work_evidence(
        work_evidence_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            tenant_id,
            lambda service: service.get_evidence(tenant_id, work_evidence_id),
            detailed=True,
        )

    @app.get(
        "/internal/v1/work-assets/{work_asset_id}",
        response_model=None,
        operation_id="getWaWorkAsset",
    )
    def get_work_asset(
        work_asset_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            tenant_id,
            lambda service: service.get_asset(tenant_id, work_asset_id),
            detailed=False,
        )

    @app.get(
        "/internal/v1/work-assets/{work_asset_id}/evidence",
        response_model=None,
        operation_id="getWaWorkAssetEvidenceLineage",
    )
    def get_work_asset_evidence(
        work_asset_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            tenant_id,
            lambda service: service.get_asset_evidence(tenant_id, work_asset_id),
            detailed=True,
        )


def _read(
    request: Request,
    authorization: str | None,
    tenant_id: str,
    operation,
    *,
    detailed: bool,
):
    scopes = [DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_READ_SCOPE]
    if detailed:
        scopes.append(WA_EVIDENCE_DETAIL_READ_SCOPE)
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-wa",
        required_scopes=tuple(scopes),
        route_class="READ",
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    if admitted.service_id not in WA_READ_CALLERS:
        return _problem(
            request,
            WaReadError(
                "WA_READ_CALLER_FORBIDDEN",
                "caller is not allowed to read WA records",
                403,
            ),
        )
    if not isinstance(tenant_id, str) or not tenant_id.strip() or tenant_id != tenant_id.strip():
        return _problem(
            request,
            WaReadError("WA_TENANT_INVALID", "tenant id is invalid", 422),
        )
    service: WaCoreReadService | None = getattr(
        request.app.state, "wa_core_read_service", None
    )
    if service is None:
        return _problem(
            request,
            WaReadError("WA_READ_UNAVAILABLE", "WA read dependencies are unavailable", 503),
        )
    try:
        return operation(service)
    except WaReadError as exc:
        return _problem(request, exc)


def _problem(request: Request, error: WaReadError) -> JSONResponse:
    return problem_response(
        request,
        status_code=error.status_code,
        error_code=error.error_code,
        title="WA read failed",
        detail=error.detail,
        type_uri="https://nex-platform.local/problems/wa-read",
        retryable=error.status_code >= 500,
    )
