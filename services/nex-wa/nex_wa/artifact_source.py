from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.request import Request

from .admission import WaEvidenceAdmissionService
from .agent_result_source import _headers, _request_json
from .intake_contracts import WaEvidenceIntakeRequest
from .source_adapters import (
    WA_SOURCE_ENVELOPE_SCHEMA,
    WaSourceAdapterError,
    WaSourceNormalizedEnvelope,
)
from .work_assets import WorkAssetBindingInput, WorkAssetInput
from .work_evidence import WorkEvidenceInput, deterministic_work_evidence_id


class ArtifactProjectionClient(Protocol):
    def fetch_version(
        self, *, tenant_id: str, artifact_id: str, artifact_version_id: str
    ) -> Mapping[str, Any]: ...


class HumanSubjectVerificationClient(Protocol):
    def verify_subject(self, *, tenant_id: str, subject_id: str) -> Mapping[str, Any]: ...


class HistoricalMembershipVerificationClient(Protocol):
    def verify_membership(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        occurred_at: str,
    ) -> Mapping[str, Any]: ...


class HttpAeArtifactProjectionClient:
    def __init__(self, *, base_url: str, service_token: str, timeout_seconds=15.0):
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = float(timeout_seconds)

    def fetch_version(
        self, *, tenant_id: str, artifact_id: str, artifact_version_id: str
    ) -> Mapping[str, Any]:
        return _request_json(
            Request(
                f"{self._base_url}/internal/v1/wa-sources/artifacts/"
                f"{artifact_id}/versions/{artifact_version_id}",
                method="GET",
                headers=_headers(self._service_token, tenant_id),
            ),
            timeout_seconds=self._timeout_seconds,
            unavailable_code="WA_AE_ARTIFACT_SOURCE_UNAVAILABLE",
        )


class HttpOaHumanSubjectVerificationClient:
    def __init__(self, *, base_url: str, service_token: str, timeout_seconds=15.0):
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = float(timeout_seconds)

    def verify_subject(self, *, tenant_id: str, subject_id: str) -> Mapping[str, Any]:
        return _post(
            f"{self._base_url}/internal/v1/identity/subjects:verify-batch",
            self._service_token,
            tenant_id,
            {"tenant_id": tenant_id, "subject_ids": [subject_id]},
            self._timeout_seconds,
            "WA_OA_SUBJECT_UNAVAILABLE",
        )


class HttpEosHistoricalMembershipVerificationClient:
    def __init__(self, *, base_url: str, service_token: str, timeout_seconds=15.0):
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = float(timeout_seconds)

    def verify_membership(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        occurred_at: str,
    ) -> Mapping[str, Any]:
        return _post(
            f"{self._base_url}/internal/v1/project-memberships:verify-at",
            self._service_token,
            tenant_id,
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "subject_id": subject_id,
                "occurred_at": occurred_at,
            },
            self._timeout_seconds,
            "WA_EOS_MEMBERSHIP_UNAVAILABLE",
        )


class AeArtifactSourceAdapter:
    source_type = "AE_ARTIFACT"

    def __init__(
        self,
        *,
        source: ArtifactProjectionClient,
        subjects: HumanSubjectVerificationClient,
        admission: WaEvidenceAdmissionService,
        memberships: HistoricalMembershipVerificationClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._subjects = subjects
        self._admission = admission
        self._memberships = memberships
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch(self, request: WaEvidenceIntakeRequest) -> WaSourceNormalizedEnvelope:
        if request.source_type != self.source_type:
            raise _invalid("Artifact adapter received a mismatched source type")
        projection = self._source.fetch_version(
            tenant_id=request.tenant_id,
            artifact_id=request.source_ref,
            artifact_version_id=request.source_revision_ref,
        )
        _require_request_match(request, projection)
        owner = projection.get("owner_actor_ref")
        if not isinstance(owner, Mapping):
            raise _invalid("Artifact owner reference is unavailable")
        if owner.get("tenant_id") != request.tenant_id or owner.get("actor_type") not in {
            "user",
            "HUMAN",
        }:
            raise _invalid("Artifact owner is outside the admitted Human tenant scope")
        subject_id = _text(owner.get("actor_id"), "owner actor_id")
        self._verify_subject(request.tenant_id, subject_id)
        occurred_at = _timestamp(projection.get("created_at"))
        project_ref = projection.get("project_ref")
        if project_ref is not None:
            project_ref = _text(project_ref, "project_ref")
            self._verify_membership(
                tenant_id=request.tenant_id,
                project_id=project_ref,
                subject_id=subject_id,
                occurred_at=_wire(occurred_at),
            )
        classification = _classification(projection.get("classification"))
        evidence_id = deterministic_work_evidence_id(
            tenant_id=request.tenant_id,
            source_type=request.source_type,
            source_ref=request.source_ref,
            source_revision_ref=request.source_revision_ref,
        )
        evidence = WorkEvidenceInput(
            tenant_id=request.tenant_id,
            source_owner="nex-ae-api",
            source_type=request.source_type,
            source_ref=request.source_ref,
            source_revision_ref=request.source_revision_ref,
            source_hash=request.source_hash,
            evidence_kind="OWNERSHIP_OR_DELIVERABLE_EVIDENCE",
            actor_type="HUMAN",
            actor_ref=subject_id,
            project_ref=project_ref,
            occurred_at=occurred_at,
            observed_at=_aware(self._clock(), "observed_at"),
            classification=classification,
        )
        asset = WorkAssetInput(
            tenant_id=request.tenant_id,
            asset_type="HUMAN_OWNED_ARTIFACT",
            artifact_id=request.source_ref,
            artifact_version_id=request.source_revision_ref,
            actor_type="HUMAN",
            actor_ref=subject_id,
            project_ref=project_ref,
            occurred_at=occurred_at,
            classification=classification,
            bindings=(WorkAssetBindingInput(evidence_id, "PRIMARY"),),
        )
        self._admission.admit_normalized_evidence(evidence, asset)
        return WaSourceNormalizedEnvelope(
            schema_version=WA_SOURCE_ENVELOPE_SCHEMA,
            tenant_id=request.tenant_id,
            source_owner="nex-ae-api",
            source_type=request.source_type,
            source_ref=request.source_ref,
            source_revision_ref=request.source_revision_ref,
            source_hash=request.source_hash,
            occurred_at=request.occurred_at,
        )

    def _verify_subject(self, tenant_id: str, subject_id: str) -> None:
        result = self._subjects.verify_subject(
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        items = result.get("results")
        if (
            result.get("tenant_id") != tenant_id
            or not isinstance(items, list)
            or len(items) != 1
            or items[0].get("subject_id") != subject_id
            or items[0].get("verification_status") != "VERIFIED"
        ):
            raise WaSourceAdapterError(
                "WA_HUMAN_OWNER_DENIED",
                "Artifact Human owner was not verified by OA",
                retryable=False,
                status_code=409,
            )

    def _verify_membership(
        self, *, tenant_id: str, project_id: str, subject_id: str, occurred_at: str
    ) -> None:
        if self._memberships is None:
            raise WaSourceAdapterError(
                "WA_PROJECT_MEMBERSHIP_UNAVAILABLE",
                "Project-attributed Artifact requires historical membership verification",
            )
        result = self._memberships.verify_membership(
            tenant_id=tenant_id,
            project_id=project_id,
            subject_id=subject_id,
            occurred_at=occurred_at,
        )
        if (
            result.get("tenant_id") != tenant_id
            or result.get("project_id") != project_id
            or result.get("subject_id") != subject_id
            or result.get("occurred_at") != occurred_at
            or result.get("membership_valid") is not True
            or result.get("verification_status") != "VERIFIED"
        ):
            raise WaSourceAdapterError(
                "WA_PROJECT_MEMBERSHIP_DENIED",
                "Artifact owner was not a verified Project member at occurrence time",
                retryable=False,
                status_code=409,
            )


def _require_request_match(
    request: WaEvidenceIntakeRequest, projection: Mapping[str, Any]
) -> None:
    actual = (
        projection.get("tenant_id"),
        projection.get("artifact_id"),
        projection.get("artifact_version_id"),
        projection.get("artifact_content_hash"),
        projection.get("artifact_status"),
    )
    expected = (
        request.tenant_id,
        request.source_ref,
        request.source_revision_ref,
        request.source_hash.removeprefix("sha256:"),
        "READY",
    )
    if actual != expected:
        raise WaSourceAdapterError(
            "WA_ARTIFACT_SOURCE_MISMATCH",
            "Artifact projection does not match the admitted READY source identity",
            retryable=False,
            status_code=409,
        )


def _post(url, token, tenant_id, payload, timeout_seconds, unavailable_code):
    return _request_json(
        Request(
            url,
            method="POST",
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers={
                **_headers(token, tenant_id),
                "Content-Type": "application/json",
            },
        ),
        timeout_seconds=timeout_seconds,
        unavailable_code=unavailable_code,
    )


def _classification(value: object) -> str:
    if value == "RESTRICTED":
        return "RESTRICTED"
    if value in {"INTERNAL", "CONFIDENTIAL"}:
        return "CONFIDENTIAL"
    raise _invalid("Artifact classification is invalid")


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid("Artifact created_at must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("Artifact created_at must be an RFC3339 timestamp") from exc
    return _aware(parsed, "created_at")


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _wire(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} is required")
    return value.strip()


def _invalid(detail: str) -> WaSourceAdapterError:
    return WaSourceAdapterError(
        "WA_ARTIFACT_SOURCE_INVALID",
        detail,
        retryable=False,
        status_code=422,
    )
