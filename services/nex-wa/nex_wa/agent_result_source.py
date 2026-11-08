from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .admission import WaEvidenceAdmissionService
from .intake_contracts import WaEvidenceIntakeRequest
from .source_adapters import (
    WA_SOURCE_ENVELOPE_SCHEMA,
    WaSourceAdapterError,
    WaSourceNormalizedEnvelope,
)
from .work_assets import WorkAssetBindingInput, WorkAssetInput
from .work_evidence import WorkEvidenceInput, deterministic_work_evidence_id

WORK_SOURCE_READ_SCOPE = "work:source:read"
EOS_PROJECT_VERIFY_SCOPE = "project:verify"
DEFAULT_AGENT_WORK_CLASSIFICATION = "CONFIDENTIAL"


class AgentResultProjectionClient(Protocol):
    def fetch_result(self, *, tenant_id: str, result_id: str) -> Mapping[str, Any]: ...


class ProjectVerificationClient(Protocol):
    def verify_project(self, *, tenant_id: str, project_id: str) -> Mapping[str, Any]: ...


class WorkResultProjectionClient(Protocol):
    def fetch_by_execution(
        self, *, tenant_id: str, agent_execution_id: str
    ) -> Mapping[str, Any]: ...


class HttpAeAgentResultProjectionClient:
    def __init__(
        self, *, base_url: str, service_token: str, timeout_seconds: float = 15.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def fetch_result(self, *, tenant_id: str, result_id: str) -> Mapping[str, Any]:
        return _request_json(
            Request(
                f"{self._base_url}/internal/v1/wa-sources/agent-results/{result_id}",
                method="GET",
                headers=_headers(self._service_token, tenant_id),
            ),
            timeout_seconds=self._timeout_seconds,
            unavailable_code="WA_AE_SOURCE_UNAVAILABLE",
        )


class HttpEosProjectVerificationClient:
    def __init__(
        self, *, base_url: str, service_token: str, timeout_seconds: float = 15.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def verify_project(self, *, tenant_id: str, project_id: str) -> Mapping[str, Any]:
        request = Request(
            f"{self._base_url}/internal/v1/projects:verify-batch",
            method="POST",
            data=json.dumps(
                {"tenant_id": tenant_id, "project_ids": [project_id]},
                sort_keys=True,
            ).encode("utf-8"),
            headers={
                **_headers(self._service_token, tenant_id),
                "Content-Type": "application/json",
            },
        )
        return _request_json(
            request,
            timeout_seconds=self._timeout_seconds,
            unavailable_code="WA_EOS_PROJECT_UNAVAILABLE",
        )


class HttpWcWorkResultProjectionClient:
    def __init__(
        self, *, base_url: str, service_token: str, timeout_seconds: float = 15.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds

    def fetch_by_execution(
        self, *, tenant_id: str, agent_execution_id: str
    ) -> Mapping[str, Any]:
        return _request_json(
            Request(
                f"{self._base_url}/internal/v1/wa-sources/work-results/"
                f"by-execution/{agent_execution_id}",
                method="GET",
                headers=_headers(self._service_token, tenant_id),
            ),
            timeout_seconds=self._timeout_seconds,
            unavailable_code="WA_WC_SOURCE_UNAVAILABLE",
        )


class AeAgentResultSourceAdapter:
    source_type = "AE_AGENT_RESULT"

    def __init__(
        self,
        *,
        source: AgentResultProjectionClient,
        admission: WaEvidenceAdmissionService,
        projects: ProjectVerificationClient | None = None,
        work_results: WorkResultProjectionClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._admission = admission
        self._projects = projects
        self._work_results = work_results
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch(self, request: WaEvidenceIntakeRequest) -> WaSourceNormalizedEnvelope:
        if request.source_type != self.source_type:
            raise _invalid("AgentResult adapter received a mismatched source type")
        projection = self._source.fetch_result(
            tenant_id=request.tenant_id,
            result_id=request.source_revision_ref,
        )
        _require_request_match(request, projection)
        _require_completion_barrier(projection)
        project_ref = _require_authority_profile(projection)
        if project_ref is not None:
            self._verify_project(request.tenant_id, project_ref)
        occurred_at = _timestamp(projection.get("created_at"))
        evidence_id = deterministic_work_evidence_id(
            tenant_id=request.tenant_id,
            source_type=request.source_type,
            source_ref=request.source_ref,
            source_revision_ref=request.source_revision_ref,
        )
        primary = WorkEvidenceInput(
                tenant_id=request.tenant_id,
                source_owner="nex-ae-api",
                source_type=request.source_type,
                source_ref=request.source_ref,
                source_revision_ref=request.source_revision_ref,
                source_hash=request.source_hash,
                evidence_kind="AGENT_EXECUTION_RESULT",
                actor_type="AGENT",
                actor_ref=_text(projection.get("agent_id"), "agent_id"),
                agent_type_snapshot=_text(
                    projection.get("agent_type"), "agent_type"
                ),
                project_ref=project_ref,
                occurred_at=occurred_at,
                observed_at=_aware(self._clock(), "observed_at"),
                classification=DEFAULT_AGENT_WORK_CLASSIFICATION,
            )
        bindings = [WorkAssetBindingInput(evidence_id, "PRIMARY")]
        evidence = [primary]
        if project_ref is not None:
            supporting = self._supporting_evidence(
                request=request,
                projection=projection,
                project_ref=project_ref,
            )
            evidence.append(supporting)
            bindings.append(
                WorkAssetBindingInput(
                    deterministic_work_evidence_id(
                        tenant_id=supporting.tenant_id,
                        source_type=supporting.source_type,
                        source_ref=supporting.source_ref,
                        source_revision_ref=supporting.source_revision_ref,
                    ),
                    "SUPPORTING",
                )
            )
        asset = WorkAssetInput(
                tenant_id=request.tenant_id,
                asset_type="AGENT_EXECUTION_RESULT",
                agent_execution_id=request.source_ref,
                actor_type="AGENT",
                actor_ref=_text(projection.get("agent_id"), "agent_id"),
                agent_type_snapshot=_text(
                    projection.get("agent_type"), "agent_type"
                ),
                project_ref=project_ref,
                occurred_at=occurred_at,
                classification=DEFAULT_AGENT_WORK_CLASSIFICATION,
                bindings=tuple(bindings),
            )
        if len(evidence) == 1:
            self._admission.admit_normalized_evidence(primary, asset)
        else:
            self._admission.admit_normalized_evidence_set(tuple(evidence), asset)
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

    def _supporting_evidence(
        self,
        *,
        request: WaEvidenceIntakeRequest,
        projection: Mapping[str, Any],
        project_ref: str,
    ) -> WorkEvidenceInput:
        if self._work_results is None:
            raise WaSourceAdapterError(
                "WA_WC_SOURCE_UNAVAILABLE",
                "background AgentResult requires its WC WorkResult source",
            )
        supporting = self._work_results.fetch_by_execution(
            tenant_id=request.tenant_id,
            agent_execution_id=request.source_ref,
        )
        expected = {
            "tenant_id": request.tenant_id,
            "source_execution_ref": request.source_ref,
            "work_item_id": projection.get("source_work_item_ref"),
            "claim_id": projection.get("source_claim_ref"),
            "claim_generation": projection.get("source_claim_generation"),
            "assignment_id": projection.get("source_assignment_ref"),
            "submitted_agent_id": projection.get("agent_id"),
        }
        if any(supporting.get(field) != value for field, value in expected.items()):
            raise WaSourceAdapterError(
                "WA_WC_SOURCE_LINEAGE_MISMATCH",
                "WC WorkResult does not match AgentResult execution and claim lineage",
                retryable=False,
                status_code=409,
            )
        result_id = _text(supporting.get("result_id"), "WC result_id")
        work_item_id = _text(supporting.get("work_item_id"), "WC work_item_id")
        revision = supporting.get("revision_no")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise _invalid("WC revision_no must be a positive integer")
        supersedes_evidence_id = self._resolve_supporting_supersession(
            request=request,
            supporting=supporting,
            work_item_id=work_item_id,
            revision=revision,
        )
        return WorkEvidenceInput(
            tenant_id=request.tenant_id,
            source_owner="nex-wc",
            source_type="WC_WORK_RESULT",
            source_ref=work_item_id,
            source_revision_ref=result_id,
            source_hash=_text(supporting.get("result_hash"), "WC result_hash"),
            evidence_kind="WORK_COORDINATION_RESULT",
            actor_type="AGENT",
            actor_ref=_text(projection.get("agent_id"), "agent_id"),
            agent_type_snapshot=_text(projection.get("agent_type"), "agent_type"),
            project_ref=project_ref,
            occurred_at=_timestamp(supporting.get("submitted_at")),
            observed_at=_aware(self._clock(), "observed_at"),
            classification=DEFAULT_AGENT_WORK_CLASSIFICATION,
            supersedes_evidence_id=supersedes_evidence_id,
        )

    def _resolve_supporting_supersession(
        self,
        *,
        request: WaEvidenceIntakeRequest,
        supporting: Mapping[str, Any],
        work_item_id: str,
        revision: int,
    ) -> str | None:
        previous_result = supporting.get("supersedes_result_id")
        previous_revision = supporting.get("supersedes_revision_no")
        if previous_result is None and previous_revision is None:
            return None
        if (
            not isinstance(previous_result, str)
            or not previous_result.strip()
            or not isinstance(previous_revision, int)
            or isinstance(previous_revision, bool)
            or previous_revision < 1
            or previous_revision >= revision
        ):
            raise _invalid("WC superseded revision identity is invalid")
        existing = self._admission.find_evidence(
            tenant_id=request.tenant_id,
            source_type="WC_WORK_RESULT",
            source_ref=work_item_id,
            source_revision_ref=previous_result,
        )
        return None if existing is None else existing.work_evidence_id

    def _verify_project(self, tenant_id: str, project_id: str) -> None:
        if self._projects is None:
            raise WaSourceAdapterError(
                "WA_PROJECT_VERIFICATION_UNAVAILABLE",
                "background AgentResult requires EOS Project verification",
            )
        result = self._projects.verify_project(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        items = result.get("results")
        if (
            result.get("tenant_id") != tenant_id
            or not isinstance(items, list)
            or len(items) != 1
            or items[0].get("project_id") != project_id
            or items[0].get("verification_status") != "VERIFIED"
        ):
            raise WaSourceAdapterError(
                "WA_PROJECT_ATTRIBUTION_DENIED",
                "AgentResult Project attribution was not verified",
                retryable=False,
                status_code=409,
            )


def _require_request_match(
    request: WaEvidenceIntakeRequest,
    projection: Mapping[str, Any],
) -> None:
    expected = (
        request.tenant_id,
        request.source_ref,
        request.source_revision_ref,
        request.source_hash,
    )
    actual = (
        projection.get("tenant_id"),
        projection.get("agent_execution_id"),
        projection.get("result_id"),
        projection.get("result_hash"),
    )
    if actual != expected:
        raise WaSourceAdapterError(
            "WA_AGENT_RESULT_SOURCE_MISMATCH",
            "AgentResult projection does not match the admitted source identity",
            retryable=False,
            status_code=409,
        )


def _require_completion_barrier(projection: Mapping[str, Any]) -> None:
    if (
        projection.get("status") not in {"SUCCEEDED", "PARTIAL"}
        or projection.get("agent_execution_state") != "SUCCEEDED"
        or projection.get("required_delivery_state") != "ACKNOWLEDGED"
    ):
        raise WaSourceAdapterError(
            "WA_AGENT_RESULT_NOT_COMPLETE",
            "AgentResult has not crossed its authoritative completion barrier",
        )


def _require_authority_profile(projection: Mapping[str, Any]) -> str | None:
    agent_type = projection.get("agent_type")
    claim_fields = (
        "source_work_item_ref",
        "source_claim_ref",
        "source_claim_generation",
        "source_assignment_ref",
    )
    if agent_type == "IA":
        if (
            projection.get("project_id") is not None
            or any(projection.get(field) is not None for field in claim_fields)
            or projection.get("required_delivery_target_type") != "WORKSPACE_RESULT"
        ):
            raise _authority_invalid()
        return None
    if agent_type in {"CA", "PA", "EA"}:
        project_ref = _text(projection.get("project_id"), "project_id")
        if (
            any(projection.get(field) in {None, ""} for field in claim_fields)
            or isinstance(projection.get("source_claim_generation"), bool)
            or not isinstance(projection.get("source_claim_generation"), int)
            or int(projection["source_claim_generation"]) < 1
            or projection.get("required_delivery_target_type") != "WC_WORK_RESULT"
        ):
            raise _authority_invalid()
        return project_ref
    raise _authority_invalid()


def _request_json(
    request: Request,
    *,
    timeout_seconds: float,
    unavailable_code: str,
) -> Mapping[str, Any]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise WaSourceAdapterError(
            unavailable_code,
            "authoritative source request failed",
            retryable=exc.code >= 500 or exc.code in {408, 429},
            status_code=503 if exc.code >= 500 else 409,
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WaSourceAdapterError(
            unavailable_code,
            "authoritative source is unavailable",
        ) from exc
    if not isinstance(payload, Mapping):
        raise WaSourceAdapterError(
            unavailable_code,
            "authoritative source response is malformed",
        )
    return payload


def _headers(token: str, tenant_id: str) -> dict[str, str]:
    if not token.strip():
        raise _invalid("service token is required")
    return {
        "Authorization": f"Bearer {token}",
        "X-NeX-Tenant-Id": tenant_id,
        "Accept": "application/json",
    }


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid("created_at must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("created_at must be an RFC3339 timestamp") from exc
    return _aware(parsed, "created_at")


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} is required")
    return value.strip()


def _authority_invalid() -> WaSourceAdapterError:
    return WaSourceAdapterError(
        "WA_AGENT_AUTHORITY_PROFILE_UNSUPPORTED",
        "AgentResult authority profile is not admitted by P9 v1",
        retryable=False,
        status_code=409,
    )


def _invalid(detail: str) -> WaSourceAdapterError:
    return WaSourceAdapterError(
        "WA_AGENT_RESULT_SOURCE_INVALID",
        detail,
        retryable=False,
        status_code=422,
    )
