from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5


DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_OWNER_USER_ID = "local-user"


class CxContentRepository(Protocol):
    def save_source_file(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_source_file(self, source_file_id: str) -> dict[str, Any] | None:
        ...

    def get_source_file_by_sha256(self, source_sha256: str) -> dict[str, Any] | None:
        ...

    def save_content_object(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def mark_source_file_checksum_verified(
        self,
        source_file_id: str,
        *,
        verified_at: str,
    ) -> dict[str, Any]:
        ...

    def get_content_object(self, content_object_id: str) -> dict[str, Any] | None:
        ...

    def find_active_content_object(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        source_sha256: str,
    ) -> dict[str, Any] | None:
        ...


@dataclass
class InMemoryCxContentRepository:
    source_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_file_ids_by_sha256: dict[str, str] = field(default_factory=dict)
    content_objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_content_object_ids_by_owner_sha: dict[tuple[str, str, str], str] = field(
        default_factory=dict
    )

    def save_source_file(self, record: dict[str, Any]) -> dict[str, Any]:
        existing_id = self.source_file_ids_by_sha256.get(record["source_sha256"])
        if existing_id is not None:
            return self.source_files[existing_id]

        stored = dict(record)
        self.source_files[stored["source_file_id"]] = stored
        self.source_file_ids_by_sha256[stored["source_sha256"]] = stored["source_file_id"]
        return stored

    def get_source_file(self, source_file_id: str) -> dict[str, Any] | None:
        return self.source_files.get(source_file_id)

    def get_source_file_by_sha256(self, source_sha256: str) -> dict[str, Any] | None:
        source_file_id = self.source_file_ids_by_sha256.get(source_sha256)
        if source_file_id is None:
            return None
        return self.source_files[source_file_id]

    def mark_source_file_checksum_verified(
        self,
        source_file_id: str,
        *,
        verified_at: str,
    ) -> dict[str, Any]:
        source_file = self.source_files[source_file_id]
        source_file["checksum_verified_at"] = verified_at
        return source_file

    def save_content_object(self, record: dict[str, Any]) -> dict[str, Any]:
        stored = dict(record)
        self.content_objects[stored["content_object_id"]] = stored
        if stored["lifecycle_status"] == "ACTIVE":
            self.active_content_object_ids_by_owner_sha[
                (
                    stored["tenant_id"],
                    stored["owner_user_id"],
                    stored["source_sha256"],
                )
            ] = stored["content_object_id"]
        return stored

    def get_content_object(self, content_object_id: str) -> dict[str, Any] | None:
        return self.content_objects.get(content_object_id)

    def find_active_content_object(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        source_sha256: str,
    ) -> dict[str, Any] | None:
        content_object_id = self.active_content_object_ids_by_owner_sha.get(
            (tenant_id, owner_user_id, source_sha256)
        )
        if content_object_id is None:
            return None
        return self.content_objects[content_object_id]


def build_source_file_record(upload_registration: dict[str, Any]) -> dict[str, Any]:
    storage = upload_registration["storage"]
    source_sha256 = upload_registration["source_sha256"]
    source_file_id = str(uuid5(NAMESPACE_URL, f"cx-source-file:{source_sha256}"))
    return {
        "source_file_id": source_file_id,
        "source_sha256": source_sha256,
        "size_bytes": upload_registration["size_bytes"],
        "content_type": upload_registration["content_type"],
        "storage_uri": f"local://cx/source-files/{storage['source_storage_key']}",
        "storage_backend": storage["source_storage_backend"],
        "storage_key": storage["source_storage_key"],
        "source_storage_path": storage["source_storage_path"],
        "stored_filename": storage["stored_filename"],
        "stored_extension": storage["stored_extension"],
        "first_seen_trace_id": upload_registration["trace_id"],
        "checksum_verified_at": None,
        "created_at": upload_registration["created_at"],
    }


def build_content_object_record(
    upload_registration: dict[str, Any],
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    owner_user_id: str = DEFAULT_OWNER_USER_ID,
    source_file_id: str,
) -> dict[str, Any]:
    now = upload_registration["created_at"]
    return {
        "content_object_id": upload_registration["document_id"],
        "tenant_id": tenant_id,
        "owner_user_id": owner_user_id,
        "source_file_id": source_file_id,
        "source_sha256": upload_registration["source_sha256"],
        "upload_id": upload_registration["upload_id"],
        "original_filename": upload_registration["original_filename"],
        "content_type": upload_registration["content_type"],
        "size_bytes": upload_registration["size_bytes"],
        "classification": "internal",
        "lifecycle_status": "ACTIVE",
        "retrieval_policy": dict(upload_registration["retrieval_policy"]),
        "created_trace_id": upload_registration["trace_id"],
        "created_at": now,
        "updated_at": upload_registration["updated_at"],
    }
