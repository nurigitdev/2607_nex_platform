from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.source_ownership import OA_TENANT_SUBJECT_TYPE, OA_USER_SUBJECT_TYPE


CX_OWNER_LINEAGE_SCHEMA_VERSION = "cx_owner_lineage.v1"
OWNER_LINEAGE_COLUMN_NAMES = (
    "tenant_ref_type",
    "tenant_ref_id",
    "owner_subject_ref_type",
    "owner_subject_ref_id",
)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class CxOwnerLineageError(ValueError):
    def __init__(self, *, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class CxOwnerLineage:
    tenant_ref_type: str
    tenant_ref_id: str
    owner_subject_ref_type: str
    owner_subject_ref_id: str

    def __post_init__(self) -> None:
        if self.tenant_ref_type != OA_TENANT_SUBJECT_TYPE:
            raise _invalid("tenant_ref.type must be oa.tenant.")
        if self.owner_subject_ref_type != OA_USER_SUBJECT_TYPE:
            raise _invalid("owner_subject_ref.type must be oa.user.")
        _identifier(self.tenant_ref_id, field_name="tenant_ref.id")
        _identifier(self.owner_subject_ref_id, field_name="owner_subject_ref.id")

    @property
    def ownership_key(self) -> tuple[str, str]:
        return (self.tenant_ref_id, self.owner_subject_ref_id)

    def to_columns(self) -> dict[str, str]:
        return {
            "tenant_ref_type": self.tenant_ref_type,
            "tenant_ref_id": self.tenant_ref_id,
            "owner_subject_ref_type": self.owner_subject_ref_type,
            "owner_subject_ref_id": self.owner_subject_ref_id,
        }

    def to_wire(self) -> dict[str, object]:
        return {
            "owner_lineage_schema_version": CX_OWNER_LINEAGE_SCHEMA_VERSION,
            "tenant_ref": {
                "type": self.tenant_ref_type,
                "id": self.tenant_ref_id,
            },
            "owner_subject_ref": {
                "type": self.owner_subject_ref_type,
                "id": self.owner_subject_ref_id,
            },
        }


def build_owner_lineage(access_context: CxAccessContext) -> CxOwnerLineage:
    return CxOwnerLineage(
        tenant_ref_type=OA_TENANT_SUBJECT_TYPE,
        tenant_ref_id=_identifier(access_context.tenant_id, field_name="tenant_ref.id"),
        owner_subject_ref_type=OA_USER_SUBJECT_TYPE,
        owner_subject_ref_id=_identifier(
            access_context.subject_id,
            field_name="owner_subject_ref.id",
        ),
    )


def normalize_owner_lineage(value: object) -> CxOwnerLineage:
    if isinstance(value, CxOwnerLineage):
        return value
    if not isinstance(value, Mapping):
        raise _invalid("Owner lineage must be an object.")

    nested = value.get("ownership_ref")
    source = nested if isinstance(nested, Mapping) else value
    tenant_ref = source.get("tenant_ref")
    owner_ref = source.get("owner_subject_ref")
    if isinstance(tenant_ref, Mapping) and isinstance(owner_ref, Mapping):
        tenant_type = tenant_ref.get("type")
        tenant_id = tenant_ref.get("id")
        owner_type = owner_ref.get("type")
        owner_id = owner_ref.get("id")
    else:
        tenant_type = source.get("tenant_ref_type")
        tenant_id = source.get("tenant_ref_id")
        owner_type = source.get("owner_subject_ref_type")
        owner_id = source.get("owner_subject_ref_id")

    if tenant_type != OA_TENANT_SUBJECT_TYPE or owner_type != OA_USER_SUBJECT_TYPE:
        raise _invalid("Owner lineage must use canonical OA tenant and user types.")
    return CxOwnerLineage(
        tenant_ref_type=OA_TENANT_SUBJECT_TYPE,
        tenant_ref_id=_identifier(tenant_id, field_name="tenant_ref.id"),
        owner_subject_ref_type=OA_USER_SUBJECT_TYPE,
        owner_subject_ref_id=_identifier(owner_id, field_name="owner_subject_ref.id"),
    )


def attach_owner_lineage(
    record: Mapping[str, Any],
    lineage: CxOwnerLineage,
) -> dict[str, Any]:
    result = dict(record)
    for field_name, expected in lineage.to_columns().items():
        current = result.get(field_name)
        if current not in (None, expected):
            raise CxOwnerLineageError(
                error_code="CX_OWNER_LINEAGE_CONFLICT",
                detail=f"{field_name} conflicts with the authenticated owner scope.",
            )
        result[field_name] = expected
    return result


def owner_lineage_matches_access_context(
    access_context: CxAccessContext,
    value: object,
) -> bool:
    try:
        return normalize_owner_lineage(value).ownership_key == (
            access_context.tenant_id,
            access_context.subject_id,
        )
    except CxOwnerLineageError:
        return False


def _identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field_name} must be a valid identifier.")
    normalized = value.strip()
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise _invalid(f"{field_name} must be a valid identifier.")
    return normalized


def _invalid(detail: str) -> CxOwnerLineageError:
    return CxOwnerLineageError(
        error_code="CX_OWNER_LINEAGE_INVALID",
        detail=detail,
    )
