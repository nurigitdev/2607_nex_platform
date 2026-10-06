from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    OperationalEventEmitResult,
    OperationalEventEmitter,
    build_subject_ref,
)

AE_ARTIFACT_ACCESS_EVENT_PREFIX = "ae.artifact_access"
AE_ARTIFACT_ACCESS_ACTIONS = ("preview", "download")


def observe_artifact_access(
    emitter: OperationalEventEmitter,
    *,
    action: str,
    artifact_file_id: str,
    artifact_id: str | None,
    allowed: bool,
    request_id: str | None,
    trace_id: str | None,
) -> OperationalEventEmitResult:
    if action not in AE_ARTIFACT_ACCESS_ACTIONS:
        raise ValueError("artifact access action is invalid")
    result_code = "SUCCEEDED" if allowed else "BLOCKED"
    event_type = f"{AE_ARTIFACT_ACCESS_EVENT_PREFIX}.{action}.{result_code.lower()}"
    return emitter.safe_emit(
        event_type=event_type,
        severity="INFO" if allowed else "WARNING",
        message=f"AE artifact {action} access {result_code.lower()}.",
        trace_id=_optional_text(trace_id),
        request_id=_optional_text(request_id),
        subject_ref=build_subject_ref("ae.artifact_file", artifact_file_id),
        details={
            "access_type": action,
            "result_code": result_code,
            "artifact_id": _optional_text(artifact_id),
            "retryable": False,
            "private_payload_included": False,
        },
        event_id=str(
            uuid5(
                NAMESPACE_URL,
                "ae-artifact-access:"
                f"{action}:{artifact_file_id}:{result_code}:"
                f"{_optional_text(trace_id)}:{_optional_text(request_id)}",
            )
        ),
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
