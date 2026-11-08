from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from nex_runtime.semantic_hashes import validate_hash_ref

from .intake_contracts import (
    WA_EXTERNAL_INTAKE_SOURCE_TYPES,
    WaEvidenceIntakeRequest,
)

WA_SOURCE_ENVELOPE_SCHEMA = "wa_source_normalized_envelope.v1"
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "source_owner",
        "source_type",
        "source_ref",
        "source_revision_ref",
        "source_hash",
        "occurred_at",
        "inspection_status",
    }
)


class WaSourceAdapterError(Exception):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        retryable: bool = True,
        status_code: int = 503,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class WaSourceNormalizedEnvelope:
    schema_version: str
    tenant_id: str
    source_owner: str
    source_type: str
    source_ref: str
    source_revision_ref: str
    source_hash: str
    occurred_at: str
    inspection_status: str = "SOURCE_AVAILABLE"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class WaEvidenceSourceAdapter(Protocol):
    @property
    def source_type(self) -> str: ...

    def fetch(
        self,
        request: WaEvidenceIntakeRequest,
    ) -> WaSourceNormalizedEnvelope: ...


class WaEvidenceSourceAdapterRegistry:
    def __init__(self, adapters: Mapping[str, WaEvidenceSourceAdapter]) -> None:
        if not isinstance(adapters, Mapping):
            raise WaSourceAdapterError(
                "WA_SOURCE_ADAPTER_REGISTRY_INVALID",
                "source adapter registry must be a mapping",
                retryable=False,
                status_code=422,
            )
        normalized: dict[str, WaEvidenceSourceAdapter] = {}
        for source_type, adapter in adapters.items():
            if source_type not in WA_EXTERNAL_INTAKE_SOURCE_TYPES:
                raise WaSourceAdapterError(
                    "WA_SOURCE_ADAPTER_REGISTRY_INVALID",
                    "source adapter registry contains an unsupported source type",
                    retryable=False,
                    status_code=422,
                )
            if getattr(adapter, "source_type", None) != source_type:
                raise WaSourceAdapterError(
                    "WA_SOURCE_ADAPTER_REGISTRY_INVALID",
                    "source adapter registry key does not match its adapter",
                    retryable=False,
                    status_code=422,
                )
            if not callable(getattr(adapter, "fetch", None)):
                raise WaSourceAdapterError(
                    "WA_SOURCE_ADAPTER_REGISTRY_INVALID",
                    "source adapter must provide fetch()",
                    retryable=False,
                    status_code=422,
                )
            normalized[source_type] = adapter
        self._adapters = normalized

    def resolve(self, source_type: str) -> WaEvidenceSourceAdapter:
        adapter = self._adapters.get(source_type)
        if adapter is None:
            raise WaSourceAdapterError(
                "WA_SOURCE_ADAPTER_UNAVAILABLE",
                "no admitted source adapter is available for the Job",
            )
        return adapter

    def readiness(self) -> dict[str, Any]:
        registered = tuple(sorted(self._adapters))
        missing = tuple(
            source_type
            for source_type in WA_EXTERNAL_INTAKE_SOURCE_TYPES
            if source_type not in self._adapters
        )
        return {
            "name": "wa_source_adapters",
            "ok": not missing,
            "registered_source_types": list(registered),
            "missing_source_types": list(missing),
        }


class ControlledWaEvidenceSourceAdapter:
    """Deterministic adapter for local lifecycle tests, never a live source client."""

    def __init__(self, source_type: str, *, source_owner: str = "controlled-test") -> None:
        if source_type not in WA_EXTERNAL_INTAKE_SOURCE_TYPES:
            raise WaSourceAdapterError(
                "WA_SOURCE_ADAPTER_INVALID",
                "controlled adapter source_type is unsupported",
                retryable=False,
                status_code=422,
            )
        self._source_type = source_type
        self._source_owner = _required_text(source_owner, "source_owner", 128)

    @property
    def source_type(self) -> str:
        return self._source_type

    def fetch(
        self,
        request: WaEvidenceIntakeRequest,
    ) -> WaSourceNormalizedEnvelope:
        if request.source_type != self.source_type:
            raise WaSourceAdapterError(
                "WA_SOURCE_ADAPTER_REQUEST_MISMATCH",
                "source adapter received a mismatched source type",
                retryable=False,
                status_code=422,
            )
        return WaSourceNormalizedEnvelope(
            schema_version=WA_SOURCE_ENVELOPE_SCHEMA,
            tenant_id=request.tenant_id,
            source_owner=self._source_owner,
            source_type=request.source_type,
            source_ref=request.source_ref,
            source_revision_ref=request.source_revision_ref,
            source_hash=request.source_hash,
            occurred_at=request.occurred_at,
        )


def normalize_source_envelope(
    value: Mapping[str, Any] | WaSourceNormalizedEnvelope,
) -> WaSourceNormalizedEnvelope:
    raw = value.to_dict() if isinstance(value, WaSourceNormalizedEnvelope) else value
    if not isinstance(raw, Mapping):
        raise _invalid("source envelope must be an object")
    unknown = sorted(set(raw) - _ENVELOPE_FIELDS)
    if unknown:
        raise WaSourceAdapterError(
            "WA_SOURCE_ENVELOPE_PAYLOAD_FORBIDDEN",
            f"source envelope contains forbidden fields: {', '.join(unknown)}",
            retryable=False,
            status_code=422,
        )
    missing = sorted(_ENVELOPE_FIELDS - set(raw))
    if missing:
        raise _invalid(f"source envelope is missing fields: {', '.join(missing)}")
    schema_version = _required_text(raw["schema_version"], "schema_version", 64)
    if schema_version != WA_SOURCE_ENVELOPE_SCHEMA:
        raise _invalid("source envelope schema_version is unsupported")
    source_type = _required_text(raw["source_type"], "source_type", 64)
    if source_type not in WA_EXTERNAL_INTAKE_SOURCE_TYPES:
        raise _invalid("source envelope source_type is unsupported")
    inspection_status = _required_text(
        raw["inspection_status"],
        "inspection_status",
        64,
    )
    if inspection_status != "SOURCE_AVAILABLE":
        raise _invalid("source envelope inspection_status is unsupported")
    try:
        source_hash = validate_hash_ref(raw["source_hash"])
    except ValueError as exc:
        raise _invalid("source envelope source_hash is invalid") from exc
    return WaSourceNormalizedEnvelope(
        schema_version=schema_version,
        tenant_id=_required_text(raw["tenant_id"], "tenant_id", 128),
        source_owner=_required_text(raw["source_owner"], "source_owner", 128),
        source_type=source_type,
        source_ref=_required_text(raw["source_ref"], "source_ref", 512),
        source_revision_ref=_required_text(
            raw["source_revision_ref"],
            "source_revision_ref",
            256,
        ),
        source_hash=source_hash,
        occurred_at=_required_text(raw["occurred_at"], "occurred_at", 64),
        inspection_status=inspection_status,
    )


def require_matching_source_envelope(
    request: WaEvidenceIntakeRequest,
    envelope: WaSourceNormalizedEnvelope,
) -> None:
    expected = (
        request.tenant_id,
        request.source_type,
        request.source_ref,
        request.source_revision_ref,
        request.source_hash,
    )
    actual = (
        envelope.tenant_id,
        envelope.source_type,
        envelope.source_ref,
        envelope.source_revision_ref,
        envelope.source_hash,
    )
    if actual != expected:
        raise WaSourceAdapterError(
            "WA_SOURCE_ENVELOPE_MISMATCH",
            "source envelope does not match the admitted Job identity and hash",
            retryable=False,
            status_code=409,
        )


def _required_text(value: object, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid(f"{field} must be a non-empty trimmed string")
    if len(value) > max_length:
        raise _invalid(f"{field} exceeds {max_length} characters")
    return value


def _invalid(detail: str) -> WaSourceAdapterError:
    return WaSourceAdapterError(
        "WA_SOURCE_ENVELOPE_INVALID",
        detail,
        retryable=False,
        status_code=422,
    )
