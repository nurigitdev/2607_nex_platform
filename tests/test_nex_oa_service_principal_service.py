from __future__ import annotations

import pytest

from nex_oa.service_principal_repository import (
    InMemoryOaServicePrincipalRepository,
)
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.service_principals import OaServicePrincipalError


def _payload(**overrides: object) -> dict[str, object]:
    return {
        "principal_id": "ae-runtime",
        "service_id": "nex-ae-api",
        "display_name": "AE Runtime",
        "allowed_audiences": ["nex-oa", "nex-cx"],
        "allowed_scopes": ["document:read", "generation:create"],
        "expected_revision": 0,
        **overrides,
    }


def test_service_principal_create_read_list_update_and_status_lifecycle() -> None:
    repository = InMemoryOaServicePrincipalRepository()
    service = OaServicePrincipalService(repository)

    created = service.upsert_principal(_payload())
    read = service.get_principal("AE-RUNTIME")
    listed = service.list_principals(service_id="nex-ae-api")
    updated = service.upsert_principal(
        _payload(display_name="AE Runtime 2", expected_revision=1)
    )
    disabled = service.set_principal_status(
        "ae-runtime", target_status="DISABLED", expected_revision=2
    )
    enabled = service.set_principal_status(
        "ae-runtime", target_status="ACTIVE", expected_revision=3
    )

    assert created["response_schema_version"] == "oa_service_principal_response.v1"
    assert created["principal"]["revision"] == 1
    assert read["principal"]["allowed_audiences"] == ["nex-cx", "nex-oa"]
    assert listed["count"] == 1
    assert updated["principal"]["display_name"] == "AE Runtime 2"
    assert disabled["principal"]["status"] == "DISABLED"
    assert enabled["principal"]["revision"] == 4
    assert "previous_revision" not in enabled["principal"]


def test_service_principal_list_is_empty_and_filterable() -> None:
    service = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    assert service.list_principals() == {
        "response_schema_version": "oa_service_principal_response.v1",
        "items": [],
        "count": 0,
    }


def test_service_principal_missing_and_stale_operations_fail_closed() -> None:
    service = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    with pytest.raises(OaServicePrincipalError) as read:
        service.get_principal("missing")
    with pytest.raises(OaServicePrincipalError) as status:
        service.set_principal_status(
            "missing", target_status="DISABLED", expected_revision=1
        )
    assert read.value.status_code == 404
    assert status.value.error_code == "oa.service_principal_not_found"

    service.upsert_principal(_payload())
    with pytest.raises(OaServicePrincipalError) as stale:
        service.upsert_principal(_payload(expected_revision=0))
    assert stale.value.error_code == "oa.service_principal_revision_conflict"


def test_principal_response_excludes_repository_internal_fields() -> None:
    repository = InMemoryOaServicePrincipalRepository()
    service = OaServicePrincipalService(repository)
    repository.principals["ae-runtime"] = {
        **_payload(),
        "principal_schema_version": "oa_service_principal.v1",
        "status": "ACTIVE",
        "revision": 1,
        "internal_note": "do-not-return",
    }

    result = service.get_principal("ae-runtime")

    assert "internal_note" not in result["principal"]
    assert "expected_revision" not in result["principal"]
    assert result["principal"]["allowed_scopes"] == [
        "document:read",
        "generation:create",
    ]

    import nex_oa.service_principal_service as module

    assert module._principal_wire({"principal_id": "partial"}) == {
        "principal_id": "partial"
    }


def test_main_wires_service_principal_runtime_without_routes_yet() -> None:
    from nex_oa.main import SERVICE_PRINCIPAL_REPOSITORY, SERVICE_PRINCIPAL_SERVICE

    assert SERVICE_PRINCIPAL_SERVICE.repository is SERVICE_PRINCIPAL_REPOSITORY
