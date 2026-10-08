from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import re
from typing import Any

OBSERVABILITY_SIGNAL_SCHEMA_VERSION = "platform_observability_signal.v1"
OBSERVABILITY_CORRELATION_SCHEMA_VERSION = "ag_observability_correlation.v1"
OBSERVABILITY_SERVICE_IDS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
OBSERVABILITY_SIGNAL_KINDS = ("METRIC", "LOG", "TRACE", "READINESS")
OBSERVABILITY_SIGNAL_STATUSES = ("HEALTHY", "DEGRADED", "FAILED", "NO_DATA")
OBSERVABILITY_SEVERITIES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
OBSERVABILITY_SAFE_ATTRIBUTE_FIELDS = frozenset(
    {
        "environment_class",
        "capability",
        "operation",
        "state",
        "failure_code",
        "policy_id",
        "revision_fingerprint",
        "route_alias",
        "source_kind",
        "retryable",
    }
)
OBSERVABILITY_FORBIDDEN_KEY_FRAGMENTS = (
    "prompt",
    "content",
    "document",
    "generated",
    "vector",
    "token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "api_key",
    "endpoint",
    "database_url",
    "storage_ref",
    "file_path",
)
MAX_OBSERVABILITY_SIGNALS = 1_000
MAX_OBSERVABILITY_MEASUREMENTS = 32
MAX_OBSERVABILITY_ATTRIBUTES = 16
MAX_OBSERVABILITY_REASON_CODES = 16

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_MEASUREMENT_NAME = re.compile(r"^[a-z][a-z0-9_.]{0,95}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


class ObservabilitySignalError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class ObservabilitySignal:
    signal_id: str
    service_id: str
    signal_kind: str
    signal_name: str
    observed_at: str
    severity: str
    status: str
    correlation_key: str
    trace_id: str | None = None
    request_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    measurements: Mapping[str, float | int] | None = None
    reason_codes: Sequence[str] = ()
    safe_attributes: Mapping[str, str | bool | int | float | None] | None = None

    def __post_init__(self) -> None:
        _identifier(self.signal_id, "signal_id")
        if self.service_id not in OBSERVABILITY_SERVICE_IDS:
            raise ObservabilitySignalError(
                "observability.service_invalid", "service_id is not a platform service"
            )
        if self.signal_kind not in OBSERVABILITY_SIGNAL_KINDS:
            raise ObservabilitySignalError(
                "observability.kind_invalid", "signal kind is not supported"
            )
        _identifier(self.signal_name, "signal_name")
        _timestamp(self.observed_at, "observed_at")
        if self.severity not in OBSERVABILITY_SEVERITIES:
            raise ObservabilitySignalError(
                "observability.severity_invalid", "signal severity is not supported"
            )
        if self.status not in OBSERVABILITY_SIGNAL_STATUSES:
            raise ObservabilitySignalError(
                "observability.status_invalid", "signal status is not supported"
            )
        _identifier(self.correlation_key, "correlation_key")
        if self.trace_id is not None and _TRACE_ID.fullmatch(self.trace_id) is None:
            raise ObservabilitySignalError(
                "observability.trace_id_invalid",
                "trace_id must contain 32 lowercase hexadecimal characters",
            )
        if self.request_id is not None:
            _identifier(self.request_id, "request_id")
        if (self.resource_type is None) != (self.resource_id is None):
            raise ObservabilitySignalError(
                "observability.resource_binding_invalid",
                "resource_type and resource_id must be provided together",
            )
        if self.resource_type is not None:
            _identifier(self.resource_type, "resource_type")
            _identifier(str(self.resource_id), "resource_id")
        _measurements(self.measurements or {})
        _reason_codes(self.reason_codes)
        _safe_attributes(self.safe_attributes or {})

    @property
    def signal_digest(self) -> str:
        return "sha256:" + hashlib.sha256(
            json.dumps(self.to_wire(include_digest=False), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def to_wire(self, *, include_digest: bool = True) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "schema_version": OBSERVABILITY_SIGNAL_SCHEMA_VERSION,
            "signal_id": self.signal_id,
            "service_id": self.service_id,
            "signal_kind": self.signal_kind,
            "signal_name": self.signal_name,
            "observed_at": _timestamp(self.observed_at, "observed_at").isoformat().replace(
                "+00:00", "Z"
            ),
            "severity": self.severity,
            "status": self.status,
            "correlation_key": self.correlation_key,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "measurements": _measurements(self.measurements or {}),
            "reason_codes": _reason_codes(self.reason_codes),
            "safe_attributes": _safe_attributes(self.safe_attributes or {}),
            "private_payload_included": False,
        }
        if include_digest:
            wire["signal_digest"] = self.signal_digest
        return wire


def correlate_observability_signals(
    signals: Sequence[ObservabilitySignal],
    *,
    checked_at: str,
    maximum_age_seconds: int,
) -> dict[str, Any]:
    if not signals or len(signals) > MAX_OBSERVABILITY_SIGNALS:
        raise ObservabilitySignalError(
            "observability.signal_count_invalid",
            "signal collection must be non-empty and bounded",
        )
    if maximum_age_seconds < 1:
        raise ObservabilitySignalError(
            "observability.maximum_age_invalid", "maximum age must be positive"
        )
    checked = _timestamp(checked_at, "checked_at")
    duplicate_ids = [
        signal_id
        for signal_id, count in Counter(item.signal_id for item in signals).items()
        if count > 1
    ]
    if duplicate_ids:
        raise ObservabilitySignalError(
            "observability.signal_duplicate", "signal IDs must be unique"
        )

    grouped: dict[str, list[ObservabilitySignal]] = defaultdict(list)
    stale_ids: list[str] = []
    for signal in signals:
        observed = _timestamp(signal.observed_at, "observed_at")
        if observed > checked:
            raise ObservabilitySignalError(
                "observability.signal_from_future", "signal timestamp is in the future"
            )
        if (checked - observed).total_seconds() > maximum_age_seconds:
            stale_ids.append(signal.signal_id)
        group_key = f"trace:{signal.trace_id}" if signal.trace_id else f"key:{signal.correlation_key}"
        grouped[group_key].append(signal)

    groups = []
    for correlation_id, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda item: (_timestamp(item.observed_at, "observed_at"), item.signal_id))
        groups.append(
            {
                "correlation_id": correlation_id,
                "correlation_type": "TRACE" if correlation_id.startswith("trace:") else "KEY",
                "signal_ids": [item.signal_id for item in ordered],
                "service_ids": sorted({item.service_id for item in ordered}),
                "signal_kinds": sorted({item.signal_kind for item in ordered}),
                "first_observed_at": ordered[0].to_wire()["observed_at"],
                "last_observed_at": ordered[-1].to_wire()["observed_at"],
                "degraded": any(
                    item.status in {"DEGRADED", "FAILED", "NO_DATA"} for item in ordered
                ),
            }
        )

    status_counts = Counter(item.status for item in signals)
    kind_counts = Counter(item.signal_kind for item in signals)
    return {
        "schema_version": OBSERVABILITY_CORRELATION_SCHEMA_VERSION,
        "checked_at": checked.isoformat().replace("+00:00", "Z"),
        "maximum_age_seconds": maximum_age_seconds,
        "correlation_status": "STALE" if stale_ids else "READY",
        "groups": groups,
        "stale_signal_ids": sorted(stale_ids),
        "summary": {
            "signal_count": len(signals),
            "group_count": len(groups),
            "trace_linked_count": sum(item.trace_id is not None for item in signals),
            "stale_count": len(stale_ids),
            "by_kind": dict(sorted(kind_counts.items())),
            "by_status": dict(sorted(status_counts.items())),
            "private_payload_included": False,
        },
    }


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ObservabilitySignalError(
            "observability.identifier_invalid", f"{field} is not a valid identifier"
        )
    lowered = value.lower()
    if any(fragment in lowered for fragment in OBSERVABILITY_FORBIDDEN_KEY_FRAGMENTS):
        raise ObservabilitySignalError(
            "observability.private_field_forbidden", f"{field} contains a private field marker"
        )
    return value


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ObservabilitySignalError(
            "observability.timestamp_invalid", f"{field} must be an ISO-8601 timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservabilitySignalError(
            "observability.timestamp_invalid", f"{field} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise ObservabilitySignalError(
            "observability.timestamp_timezone_required", f"{field} must be timezone-aware"
        )
    return parsed.astimezone(UTC)


def _measurements(values: Mapping[str, float | int]) -> dict[str, float]:
    if len(values) > MAX_OBSERVABILITY_MEASUREMENTS:
        raise ObservabilitySignalError(
            "observability.measurement_count_invalid", "measurement count exceeds the limit"
        )
    result: dict[str, float] = {}
    for key, value in values.items():
        if _MEASUREMENT_NAME.fullmatch(key) is None:
            raise ObservabilitySignalError(
                "observability.measurement_name_invalid", "measurement name is invalid"
            )
        if any(fragment in key for fragment in OBSERVABILITY_FORBIDDEN_KEY_FRAGMENTS):
            raise ObservabilitySignalError(
                "observability.private_field_forbidden", "measurement name is private"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ObservabilitySignalError(
                "observability.measurement_value_invalid", "measurement value must be finite"
            )
        result[key] = float(value)
    return dict(sorted(result.items()))


def _reason_codes(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or len(values) > MAX_OBSERVABILITY_REASON_CODES:
        raise ObservabilitySignalError(
            "observability.reason_codes_invalid", "reason codes must be a bounded sequence"
        )
    normalized = [_identifier(value, "reason_code") for value in values]
    if len(normalized) != len(set(normalized)):
        raise ObservabilitySignalError(
            "observability.reason_codes_duplicate", "reason codes must be unique"
        )
    return sorted(normalized)


def _safe_attributes(
    values: Mapping[str, str | bool | int | float | None],
) -> dict[str, str | bool | int | float | None]:
    if len(values) > MAX_OBSERVABILITY_ATTRIBUTES:
        raise ObservabilitySignalError(
            "observability.attribute_count_invalid", "safe attribute count exceeds the limit"
        )
    unknown = sorted(set(values) - OBSERVABILITY_SAFE_ATTRIBUTE_FIELDS)
    if unknown:
        raise ObservabilitySignalError(
            "observability.attribute_field_forbidden", "safe attribute field is not allowed"
        )
    normalized: dict[str, str | bool | int | float | None] = {}
    for key, value in values.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ObservabilitySignalError(
                "observability.attribute_value_invalid", "safe attribute value must be finite"
            )
        if value is not None and not isinstance(value, (str, bool, int, float)):
            raise ObservabilitySignalError(
                "observability.attribute_value_invalid", "safe attribute value must be scalar"
            )
        if isinstance(value, str) and len(value) > 200:
            raise ObservabilitySignalError(
                "observability.attribute_value_invalid", "safe attribute value is too long"
            )
        normalized[key] = value
    return dict(sorted(normalized.items()))
