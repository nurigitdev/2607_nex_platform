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
WA_EVIDENCE_AUDIT_READ_SCOPE = "work:evidence:audit:read"
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
        record = self._get_asset_record(tenant_id, work_asset_id)
        return {
            "schema_version": "wa_work_asset_summary.v1",
            "tenant_id": record.tenant_id,
            "work_asset_id": record.work_asset_id,
            "asset_type": record.asset_type,
            "actor_type": record.actor_type,
            "actor_ref": record.actor_ref,
            "agent_type_snapshot": record.agent_type_snapshot,
            "project_ref": record.project_ref,
            "occurred_at": record.occurred_at,
            "classification": record.classification,
            "asset_status": record.asset_status,
            "asset_hash": record.asset_hash,
            "version": record.version,
            "evidence_count": len(record.bindings),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _get_asset_record(self, tenant_id: str, work_asset_id: str):
        try:
            record = self._asset_repository.get(tenant_id, work_asset_id)
        except WorkAssetError as exc:
            raise WaReadError(exc.error_code, exc.detail, exc.status_code) from exc
        if record is None:
            raise WaReadError("WA_ASSET_NOT_FOUND", "WorkAsset was not found", 404)
        return record

    def get_asset_evidence(
        self, tenant_id: str, work_asset_id: str
    ) -> dict[str, Any]:
        asset = self._get_asset_record(tenant_id, work_asset_id)
        items: list[dict[str, Any]] = []
        for binding in asset.bindings:
            evidence = self.get_evidence(tenant_id, binding.work_evidence_id)
            items.append(
                {
                    "binding_role": binding.binding_role,
                    "binding_created_at": binding.created_at,
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
            "tenant_id": asset.tenant_id,
            "work_asset_id": asset.work_asset_id,
            "items": items,
        }

    def get_evidence_audit(
        self, tenant_id: str, work_evidence_id: str
    ) -> dict[str, Any]:
        try:
            lineage = self._evidence_repository.list_source_lineage(
                tenant_id, work_evidence_id
            )
        except WorkEvidenceError as exc:
            raise WaReadError(exc.error_code, exc.detail, exc.status_code) from exc
        if not lineage:
            raise WaReadError(
                "WA_EVIDENCE_NOT_FOUND", "WorkEvidence was not found", 404
            )
        return {
            "schema_version": "wa_work_evidence_audit.v1",
            "tenant_id": tenant_id,
            "work_evidence_id": work_evidence_id,
            "source_type": lineage[0].source_type,
            "source_ref": lineage[0].source_ref,
            "replay_policy": "SAME_IDENTITY_SAME_HASH_REUSE",
            "conflict_policy": "SAME_IDENTITY_DIFFERENT_HASH_REJECT",
            "items": [
                {
                    "work_evidence_id": item.work_evidence_id,
                    "source_revision_ref": item.source_revision_ref,
                    "source_hash": item.source_hash,
                    "evidence_hash": item.evidence_hash,
                    "evidence_status": item.evidence_status,
                    "supersedes_evidence_id": item.supersedes_evidence_id,
                    "created_at": item.created_at,
                }
                for item in lineage
            ],
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
        "/internal/v1/work-evidence/{work_evidence_id}/audit",
        response_model=None,
        operation_id="getWaWorkEvidenceAudit",
    )
    def get_work_evidence_audit(
        work_evidence_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        return _read(
            request,
            authorization,
            tenant_id,
            lambda service: service.get_evidence_audit(tenant_id, work_evidence_id),
            detailed=True,
            audit=True,
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
    audit: bool = False,
):
    scopes = [DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_READ_SCOPE]
    if detailed:
        scopes.append(WA_EVIDENCE_DETAIL_READ_SCOPE)
    if audit:
        scopes.append(WA_EVIDENCE_AUDIT_READ_SCOPE)
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
