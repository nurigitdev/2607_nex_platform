from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nex_runtime import OperationalEventEmitter
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from .intake import WaEvidenceIntakeService
from .intake_contracts import (
    WA_EXTERNAL_INTAKE_SOURCE_TYPES,
    WaIntakeContractError,
    normalize_evidence_intake_request,
)

WA_RECONCILIATION_PAGE_SCHEMA = "wa_source_reconciliation_page.v1"
WA_RECONCILIATION_MODES = frozenset({"OPERATOR", "STARTUP"})


class WaReconciliationError(Exception):
    def __init__(self, error_code: str, detail: str, *, retryable: bool) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable


class AeWaReconciliationSource(Protocol):
    def list_sources(
        self,
        *,
        tenant_id: str,
        source_type: str,
        created_after: str,
        created_before: str,
        limit: int,
        cursor: str | None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class WaReconciliationSourceResult:
    source_type: str
    pages_scanned: int
    items_scanned: int
    jobs_admitted: int
    jobs_reused: int
    complete: bool
    next_cursor: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WaReconciliationResult:
    tenant_id: str
    mode: str
    created_after: str
    created_before: str
    sources: tuple[WaReconciliationSourceResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "mode": self.mode,
            "created_after": self.created_after,
            "created_before": self.created_before,
            "sources": [source.to_dict() for source in self.sources],
        }


class HttpAeWaReconciliationSource:
    _PATHS: ClassVar[dict[str, str]] = {
        "AE_AGENT_RESULT": "/internal/v1/wa-sources/agent-results",
        "AE_ARTIFACT": "/internal/v1/wa-sources/artifacts",
    }

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not base_url.strip() or not service_token.strip():
            raise ValueError(
                "AE reconciliation endpoint and service token are required"
            )
        if timeout_seconds <= 0:
            raise ValueError("AE reconciliation timeout must be positive")
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def list_sources(
        self,
        *,
        tenant_id: str,
        source_type: str,
        created_after: str,
        created_before: str,
        limit: int,
        cursor: str | None,
    ) -> Mapping[str, Any]:
        path = self._PATHS.get(source_type)
        if path is None:
            raise WaReconciliationError(
                "WA_RECONCILIATION_SOURCE_UNSUPPORTED",
                "reconciliation source type is unsupported",
                retryable=False,
            )
        query = {
            "created_after": created_after,
            "created_before": created_before,
            "limit": str(limit),
        }
        if cursor is not None:
            query["cursor"] = cursor
        request = Request(
            f"{self._base_url}{path}?{urlencode(query)}",
            method="GET",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Accept": "application/json",
                "X-NeX-Tenant-Id": tenant_id,
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise WaReconciliationError(
                "WA_RECONCILIATION_AE_REQUEST_FAILED",
                "AE reconciliation listing request failed",
                retryable=exc.code >= 500 or exc.code in {408, 429},
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WaReconciliationError(
                "WA_RECONCILIATION_AE_UNAVAILABLE",
                "AE reconciliation listing is unavailable",
                retryable=True,
            ) from exc
        if not isinstance(payload, Mapping):
            raise WaReconciliationError(
                "WA_RECONCILIATION_PAGE_INVALID",
                "AE reconciliation listing returned an invalid page",
                retryable=False,
            )
        return payload


class WaAeReconciliationService:
    def __init__(
        self,
        *,
        source: AeWaReconciliationSource,
        intake: WaEvidenceIntakeService,
        event_emitter: OperationalEventEmitter | None = None,
    ) -> None:
        self._source = source
        self._intake = intake
        self._event_emitter = event_emitter

    def run(
        self,
        *,
        tenant_id: str,
        created_after: str,
        created_before: str,
        mode: str,
        page_size: int = 50,
        max_pages_per_source: int = 10,
    ) -> WaReconciliationResult:
        normalized_mode = mode.strip().upper() if isinstance(mode, str) else ""
        if normalized_mode not in WA_RECONCILIATION_MODES:
            raise WaReconciliationError(
                "WA_RECONCILIATION_MODE_INVALID",
                "reconciliation mode must be OPERATOR or STARTUP",
                retryable=False,
            )
        if not tenant_id.strip():
            raise WaReconciliationError(
                "WA_RECONCILIATION_TENANT_REQUIRED",
                "reconciliation tenant is required",
                retryable=False,
            )
        if not 1 <= page_size <= 100 or not 1 <= max_pages_per_source <= 100:
            raise WaReconciliationError(
                "WA_RECONCILIATION_BOUND_INVALID",
                "reconciliation page size and maximum page count are invalid",
                retryable=False,
            )
        results = tuple(
            self._run_source(
                tenant_id=tenant_id.strip(),
                source_type=source_type,
                created_after=created_after,
                created_before=created_before,
                mode=normalized_mode,
                page_size=page_size,
                max_pages=max_pages_per_source,
            )
            for source_type in WA_EXTERNAL_INTAKE_SOURCE_TYPES
        )
        result = WaReconciliationResult(
            tenant_id=tenant_id.strip(),
            mode=normalized_mode,
            created_after=created_after,
            created_before=created_before,
            sources=results,
        )
        if self._event_emitter is not None:
            self._event_emitter.safe_emit(
                event_type="wa.reconciliation.completed",
                severity="INFO",
                message="WA bounded reconciliation completed.",
                details={
                    "mode": normalized_mode,
                    "source_count": len(results),
                    "jobs_admitted": sum(item.jobs_admitted for item in results),
                    "jobs_reused": sum(item.jobs_reused for item in results),
                    "complete": all(item.complete for item in results),
                },
            )
        return result

    def _run_source(
        self,
        *,
        tenant_id: str,
        source_type: str,
        created_after: str,
        created_before: str,
        mode: str,
        page_size: int,
        max_pages: int,
    ) -> WaReconciliationSourceResult:
        cursor: str | None = None
        pages_scanned = items_scanned = jobs_admitted = jobs_reused = 0
        complete = False
        while pages_scanned < max_pages:
            page = self._source.list_sources(
                tenant_id=tenant_id,
                source_type=source_type,
                created_after=created_after,
                created_before=created_before,
                limit=page_size,
                cursor=cursor,
            )
            items, has_more, next_cursor = _validate_page(
                page,
                tenant_id=tenant_id,
                source_type=source_type,
                created_after=created_after,
                created_before=created_before,
                requested_limit=page_size,
                current_cursor=cursor,
            )
            pages_scanned += 1
            for item in items:
                request = normalize_evidence_intake_request(item)
                identity = semantic_sha256_hash_ref(
                    {
                        "tenant_id": request.tenant_id,
                        "source_type": request.source_type,
                        "source_ref": request.source_ref,
                        "source_revision_ref": request.source_revision_ref,
                        "mode": mode,
                    }
                ).removeprefix("sha256:")[:32]
                admission = self._intake.admit(
                    item,
                    caller_service_id="nex-ae-api",
                    request_id=f"wa-reconcile-{identity}",
                    trace_id=f"wa-reconcile-{identity}",
                )
                items_scanned += 1
                if admission.idempotent_reuse:
                    jobs_reused += 1
                else:
                    jobs_admitted += 1
            cursor = next_cursor
            if not has_more:
                complete = True
                break
        return WaReconciliationSourceResult(
            source_type=source_type,
            pages_scanned=pages_scanned,
            items_scanned=items_scanned,
            jobs_admitted=jobs_admitted,
            jobs_reused=jobs_reused,
            complete=complete,
            next_cursor=None if complete else cursor,
        )


def _validate_page(
    page: Mapping[str, Any],
    *,
    tenant_id: str,
    source_type: str,
    created_after: str,
    created_before: str,
    requested_limit: int,
    current_cursor: str | None,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    if (
        page.get("schema_version") != WA_RECONCILIATION_PAGE_SCHEMA
        or page.get("source_type") != source_type
        or page.get("created_after") != created_after
        or page.get("created_before") != created_before
        or not isinstance(page.get("items"), list)
        or not isinstance(page.get("pagination"), Mapping)
    ):
        raise _invalid_page()
    pagination = page["pagination"]
    items = page["items"]
    has_more = pagination.get("has_more")
    next_cursor = pagination.get("next_cursor")
    if (
        pagination.get("limit") != requested_limit
        or pagination.get("returned") != len(items)
        or len(items) > requested_limit
        or not isinstance(has_more, bool)
        or (has_more and (not isinstance(next_cursor, str) or not next_cursor))
        or (not has_more and next_cursor is not None)
        or (has_more and next_cursor == current_cursor)
    ):
        raise _invalid_page()
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise _invalid_page()
        try:
            request = normalize_evidence_intake_request(item)
        except WaIntakeContractError as exc:
            raise _invalid_page() from exc
        if request.tenant_id != tenant_id or request.source_type != source_type:
            raise _invalid_page()
        normalized.append(request.to_job_payload())
    return normalized, has_more, next_cursor


def _invalid_page() -> WaReconciliationError:
    return WaReconciliationError(
        "WA_RECONCILIATION_PAGE_INVALID",
        "AE reconciliation listing returned an invalid bounded page",
        retryable=False,
    )


__all__ = (
    "AeWaReconciliationSource",
    "HttpAeWaReconciliationSource",
    "WaAeReconciliationService",
    "WaReconciliationError",
    "WaReconciliationResult",
    "WaReconciliationSourceResult",
)
