from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, Header, Request

from nex_mo.catalog_lifecycle import CatalogLifecycleError
from nex_mo.catalog_lifecycle_service import (
    CatalogLifecycleService,
    CatalogLifecycleServiceError,
    RegisterCatalogEntry,
)
from nex_mo.provider_auth import (
    authenticated_mo_service_actor,
    authorize_mo_service_request,
)
from nex_runtime import problem_response


def register_catalog_lifecycle_routes(
    app: FastAPI,
    *,
    service: CatalogLifecycleService,
) -> None:
    @app.get("/api/v1/model-catalog", response_model=None)
    def list_model_catalog(
        request: Request,
        capability: str | None = None,
        state: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: {
                "data": [
                    entry.to_wire()
                    for entry in service.list_catalog_entries(
                        capability=capability,
                        state=state,
                    )
                ],
                "meta": {
                    "schema_version": "mo_model_catalog_collection.v1",
                    "capability": capability,
                    "state": state,
                },
            },
        )

    @app.post("/api/v1/model-catalog", response_model=None, status_code=201)
    def register_model_catalog_entry(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: service.register_catalog_entry(_registration(payload)).to_wire(),
        )

    @app.get("/api/v1/model-catalog/{catalog_id}", response_model=None)
    def get_model_catalog_entry(
        catalog_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: service.get_catalog_entry(catalog_id).to_wire(),
        )

    @app.post(
        "/api/v1/model-catalog/{catalog_id}/transitions",
        response_model=None,
    )
    def transition_model_catalog_entry(
        catalog_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: service.transition_catalog_entry(
                catalog_id,
                expected_revision=_integer(payload, "expected_revision"),
                target_state=_string(payload, "target_state"),
            ).to_wire(),
        )

    @app.get("/api/v1/provider-alias-bindings", response_model=None)
    def list_provider_alias_bindings(
        request: Request,
        alias: str | None = None,
        capability: str | None = None,
        state: str | None = None,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: {
                "data": [
                    binding.to_wire()
                    for binding in service.list_alias_bindings(
                        alias=alias,
                        capability=capability,
                        state=state,
                    )
                ],
                "meta": {
                    "schema_version": "mo_alias_binding_collection.v1",
                    "alias": alias,
                    "capability": capability,
                    "state": state,
                },
            },
        )

    @app.post("/api/v1/provider-alias-bindings/activate", response_model=None)
    def activate_provider_alias(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: service.activate_alias(
                alias=_string(payload, "alias"),
                capability=_string(payload, "provider_capability"),
                catalog_id=_string(payload, "catalog_id"),
                expected_binding_revision=_integer(
                    payload, "expected_binding_revision"
                ),
                change_reason=_string(payload, "change_reason"),
                changed_by=authenticated_mo_service_actor(request),
            ).to_wire(),
        )

    @app.post("/api/v1/provider-alias-bindings/rollback", response_model=None)
    def rollback_provider_alias(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: service.rollback_alias(
                alias=_string(payload, "alias"),
                capability=_string(payload, "provider_capability"),
                expected_binding_revision=_integer(
                    payload, "expected_binding_revision"
                ),
                change_reason=_string(payload, "change_reason"),
                changed_by=authenticated_mo_service_actor(request),
            ).to_wire(),
        )


def _authorized(
    request: Request,
    authorization: str | None,
    operation: Callable[[], Any],
):
    auth_problem = authorize_mo_service_request(request, authorization)
    if auth_problem is not None:
        return auth_problem
    try:
        return operation()
    except CatalogLifecycleServiceError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="Catalog lifecycle request rejected",
            detail=exc.detail,
            type_uri="https://nex-platform.local/problems/catalog-lifecycle-rejected",
        )
    except (CatalogLifecycleError, KeyError, TypeError, ValueError) as exc:
        return problem_response(
            request,
            status_code=422,
            error_code="MO_CATALOG_REQUEST_INVALID",
            title="Catalog lifecycle request invalid",
            detail="Catalog lifecycle payload is invalid.",
            type_uri="https://nex-platform.local/problems/catalog-lifecycle-invalid",
        )


def _registration(payload: dict[str, Any]) -> RegisterCatalogEntry:
    formats = payload.get("supports_response_formats")
    if not isinstance(formats, list):
        raise ValueError("supports_response_formats must be a list")
    dimensions = payload.get("embedding_dimensions")
    if dimensions is not None and not isinstance(dimensions, int):
        raise ValueError("embedding_dimensions must be an integer")
    return RegisterCatalogEntry(
        provider_capability=_string(payload, "provider_capability"),
        model_name=_string(payload, "model_name"),
        model_revision=_string(payload, "model_revision"),
        deployment_id=_string(payload, "deployment_id"),
        runtime_profile=_string(payload, "runtime_profile"),
        precision=_string(payload, "precision"),
        provider_type=_string(payload, "provider_type"),
        supports_response_formats=tuple(formats),
        max_input_tokens=_integer(payload, "max_input_tokens"),
        max_output_tokens=_integer(payload, "max_output_tokens"),
        embedding_dimensions=dimensions,
    )


def _string(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _integer(payload: dict[str, Any], field_name: str) -> int:
    value = payload.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value
