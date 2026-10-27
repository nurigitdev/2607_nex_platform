from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_wc.work_results import WorkResultError

WORK_SOURCE_READ_SCOPE = "work:source:read"
PROJECTION_SCHEMA_VERSION = "wa_work_result_source_projection.v1"


class WorkResultProjectionRepository(Protocol):
    def get_result_source(
        self, *, tenant_id: str, result_id: str
    ) -> Mapping[str, Any] | None: ...

    def list_result_sources_by_execution(
        self, *, tenant_id: str, source_execution_ref: str, limit: int
    ) -> Sequence[Mapping[str, Any]]: ...


class WorkResultWaProjectionSource:
    def __init__(self, repository: WorkResultProjectionRepository) -> None:
        self._repository = repository

    def get_by_result(
        self, *, tenant_id: str, result_id: str
    ) -> dict[str, Any] | None:
        record = self._repository.get_result_source(
            tenant_id=tenant_id,
            result_id=result_id,
        )
        return None if record is None else build_work_result_wa_projection(record)

    def get_by_execution(
        self, *, tenant_id: str, agent_execution_id: str
    ) -> dict[str, Any] | None:
        records = self._repository.list_result_sources_by_execution(
            tenant_id=tenant_id,
            source_execution_ref=agent_execution_id,
            limit=2,
        )
        if not records:
            return None
        projections = sorted(
            (build_work_result_wa_projection(record) for record in records),
            key=lambda item: (
                item["revision_no"],
                item["submitted_at"],
                item["result_id"],
            ),
            reverse=True,
        )
        projection = projections[0]
        if projection["source_execution_ref"] != agent_execution_id:
            raise _invalid("WorkResult execution lookup returned mismatched lineage.")
        if len(projections) == 2:
            previous = projections[1]
            _require_revision_lineage(projection, previous)
            projection = {
                **projection,
                "supersedes_result_id": previous["result_id"],
                "supersedes_revision_no": previous["revision_no"],
            }
        return projection


def build_work_result_wa_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = record.get("work_result")
    if not isinstance(payload, Mapping):
        raise _invalid("WorkResult authoritative payload is unavailable.")
    result_hash = str(record.get("result_hash") or "")
    if semantic_sha256_hash_ref(payload) != result_hash:
        raise _invalid("WorkResult semantic hash does not match its payload.")
    submitted_by = payload.get("submitted_by")
    if not isinstance(submitted_by, Mapping):
        raise _invalid("WorkResult submitted Agent lineage is unavailable.")
    expected = {
        "tenant_id": str(payload.get("tenant_id") or ""),
        "result_id": str(payload.get("result_id") or ""),
        "work_item_id": str(payload.get("work_item_id") or ""),
        "revision_no": payload.get("revision_no"),
        "source_execution_ref": str(payload.get("source_execution_ref") or ""),
        "claim_id": str(payload.get("claim_ref") or ""),
        "claim_generation": payload.get("claim_generation"),
        "assignment_id": str(payload.get("assignment_ref") or ""),
        "submitted_agent_id": str(submitted_by.get("entity_id") or ""),
        "submitted_at": str(payload.get("submitted_at") or ""),
    }
    actual = {field: record.get(field) for field in expected}
    actual = {
        field: str(value) if field not in {"revision_no", "claim_generation"} else value
        for field, value in actual.items()
    }
    if actual != expected or not all(
        value not in (None, "") for value in expected.values()
    ):
        raise _invalid("WorkResult scalar lineage does not match its payload.")
    return {
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        **expected,
        "result_hash": result_hash,
    }


def _require_revision_lineage(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
) -> None:
    lineage_fields = (
        "tenant_id",
        "work_item_id",
        "source_execution_ref",
        "claim_id",
        "claim_generation",
        "assignment_id",
        "submitted_agent_id",
    )
    if any(current[field] != previous[field] for field in lineage_fields):
        raise WorkResultError(
            "wc.wa_source_result_ambiguous",
            "WorkResult revisions do not share one canonical execution lineage.",
        )
    if current["revision_no"] <= previous["revision_no"]:
        raise WorkResultError(
            "wc.wa_source_result_ambiguous",
            "WorkResult revisions are not strictly ordered.",
        )


def register_wa_work_result_source_routes(
    app: FastAPI,
    *,
    source: WorkResultWaProjectionSource | None,
) -> None:
    app.state.wc_wa_work_result_source = source

    @app.get("/internal/v1/wa-sources/work-results/{result_id}", response_model=None)
    def get_work_result_source(
        result_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Header(default=None, alias="X-NeX-Tenant-Id"),
    ):
        problem = _admission_problem(request, authorization, tenant_id)
        if problem is not None:
            return problem
        if source is None:
            return _problem(request, 503, "wc.wa_source_unavailable", True)
        try:
            projection = source.get_by_result(
                tenant_id=tenant_id.strip(),
                result_id=result_id,
            )
        except WorkResultError as exc:
            return _work_result_problem(request, exc)
        return _projection_or_not_found(request, projection)

    @app.get(
        "/internal/v1/wa-sources/work-results/by-execution/{agent_execution_id}",
        response_model=None,
    )
    def get_work_result_source_by_execution(
        agent_execution_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str | None = Header(default=None, alias="X-NeX-Tenant-Id"),
    ):
        problem = _admission_problem(request, authorization, tenant_id)
        if problem is not None:
            return problem
        if source is None:
            return _problem(request, 503, "wc.wa_source_unavailable", True)
        try:
            projection = source.get_by_execution(
                tenant_id=tenant_id.strip(),
                agent_execution_id=agent_execution_id,
            )
        except WorkResultError as exc:
            return _work_result_problem(request, exc)
        return _projection_or_not_found(request, projection)


def _admission_problem(
    request: Request,
    authorization: str | None,
    tenant_id: str | None,
) -> JSONResponse | None:
    admitted = admit_service_token_from_request(
        request,
        authorization,
        expected_audience="nex-wc",
        required_scopes=(DEFAULT_SERVICE_SCOPE, WORK_SOURCE_READ_SCOPE),
    )
    if isinstance(admitted, JSONResponse):
        return admitted
    if admitted.service_id != "nex-wa":
        return _problem(request, 403, "wc.wa_source_caller_forbidden")
    if tenant_id is None or not tenant_id.strip():
        return _problem(request, 400, "wc.wa_source_tenant_required")
    return None


def _projection_or_not_found(
    request: Request,
    projection: dict[str, Any] | None,
) -> dict[str, Any] | JSONResponse:
    if projection is None:
        return _problem(request, 404, "wc.wa_source_work_result_not_found")
    return projection


def _work_result_problem(request: Request, exc: WorkResultError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="WC WA source projection failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/wc-wa-source-projection",
    )


def _problem(
    request: Request,
    status_code: int,
    error_code: str,
    retryable: bool = False,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=status_code,
        error_code=error_code,
        title="WC WA source projection failed",
        detail="WC WorkResult source projection request was not admitted.",
        retryable=retryable,
        type_uri="https://nex-platform.local/problems/wc-wa-source-projection",
    )


def _invalid(detail: str) -> WorkResultError:
    return WorkResultError("wc.wa_source_lineage_invalid", detail)
