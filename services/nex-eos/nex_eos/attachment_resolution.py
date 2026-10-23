from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from .attachments import ResolvedObjectRef

AE_ATTACHMENT_RESOLVE_PATH = "/internal/v1/voucher-attachments/resolve"
_RESOLUTION_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "attachment_batch_id",
        "attachment_id",
        "attachment_manifest_hash",
        "object_ref",
        "storage_owner",
        "purpose",
        "status",
        "content_sha256",
        "size_bytes",
        "media_type",
        "authenticated",
        "immutable",
        "object_version_ref",
        "resolved_at",
    }
)


class AeAttachmentResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpAeVoucherAttachmentResolver:
    base_url: str
    service_token: str
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("AE attachment resolver base URL is invalid")
        if not self.service_token or self.service_token != self.service_token.strip():
            raise ValueError("AE attachment resolver service token is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("AE attachment resolver timeout must be positive")

    def resolve_object_ref(
        self,
        *,
        requester_service: str,
        tenant_id: str,
        object_ref: str,
        required_purpose: str,
    ) -> ResolvedObjectRef:
        if requester_service != "nex-eos":
            raise AeAttachmentResolutionError("Unexpected resolver caller identity")
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    f"{self.base_url.rstrip('/')}{AE_ATTACHMENT_RESOLVE_PATH}",
                    headers={
                        "Authorization": f"Bearer {self.service_token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "X-NeX-Tenant-Id": tenant_id,
                        "X-Service-ID": "nex-eos",
                    },
                    json={
                        "object_ref": object_ref,
                        "required_purpose": required_purpose,
                    },
                )
        except httpx.HTTPError as exc:
            raise AeAttachmentResolutionError(
                "AE attachment resolver transport failed"
            ) from exc
        if response.status_code != 200:
            raise AeAttachmentResolutionError(
                "AE attachment resolver rejected the object reference"
            )
        return _resolved_object(_response_payload(response))


def _response_payload(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AeAttachmentResolutionError(
            "AE attachment resolver response is not JSON"
        ) from exc
    if not isinstance(payload, Mapping) or set(payload) != _RESOLUTION_FIELDS:
        raise AeAttachmentResolutionError(
            "AE attachment resolver response fields are invalid"
        )
    return dict(payload)


def _resolved_object(payload: Mapping[str, object]) -> ResolvedObjectRef:
    if payload.get("schema_version") != "ae_voucher_attachment_resolution.v1":
        raise AeAttachmentResolutionError("AE attachment resolver schema is invalid")
    try:
        return ResolvedObjectRef(
            object_ref=str(payload["object_ref"]),
            storage_owner=str(payload["storage_owner"]),
            tenant_id=str(payload["tenant_id"]),
            purpose=str(payload["purpose"]),
            status=str(payload["status"]),
            content_sha256=str(payload["content_sha256"]),
            size_bytes=int(payload["size_bytes"]),
            media_type=str(payload["media_type"]),
            authenticated=payload["authenticated"] is True,
            immutable=payload["immutable"] is True,
            version_ref=(
                str(payload["object_version_ref"])
                if payload["object_version_ref"] is not None
                else None
            ),
            attachment_id=str(payload["attachment_id"]),
            attachment_batch_id=str(payload["attachment_batch_id"]),
            attachment_manifest_hash=str(payload["attachment_manifest_hash"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AeAttachmentResolutionError(
            "AE attachment resolver response values are invalid"
        ) from exc
