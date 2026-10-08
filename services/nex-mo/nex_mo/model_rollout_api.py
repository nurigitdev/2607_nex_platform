from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Header, Request
from nex_runtime import problem_response

from nex_mo.model_rollout_service import (
    ModelRolloutService,
    ModelRolloutServiceError,
)
from nex_mo.provider_auth import authorize_mo_operations_request


def register_model_rollout_routes(
    app: FastAPI,
    *,
    service: ModelRolloutService,
) -> None:
    @app.get("/api/v1/model-rollouts", response_model=None)
    def list_model_rollouts(
        request: Request,
        capability: str | None = None,
        state: str | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: {
                "data": [
                    record.to_wire()
                    for record in service.list(
                        capability=capability,
                        state=state,
                        limit=limit,
                    )
                ],
                "meta": {
                    "schema_version": "mo_model_rollout_collection.v1",
                    "capability": capability,
                    "state": state,
                    "limit": limit,
                },
            },
        )

    @app.get("/api/v1/model-rollouts/{rollout_id}", response_model=None)
    def get_model_rollout(
        rollout_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: service.get(rollout_id).to_wire(),
        )

    @app.get("/api/v1/model-rollouts/{rollout_id}/events", response_model=None)
    def list_model_rollout_events(
        rollout_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        return _authorized(
            request,
            authorization,
            lambda: {
                "data": [event.to_wire() for event in service.list_events(rollout_id)],
                "meta": {
                    "schema_version": "mo_model_rollout_event_collection.v1",
                    "rollout_id": rollout_id,
                },
            },
        )


def _authorized(
    request: Request,
    authorization: str | None,
    operation: Callable[[], Any],
):
    auth_problem = authorize_mo_operations_request(request, authorization)
    if auth_problem is not None:
        return auth_problem
    try:
        return operation()
    except ModelRolloutServiceError as exc:
        return problem_response(
            request,
            status_code=exc.status_code,
            error_code=exc.error_code,
            title="Model rollout request rejected",
            detail=exc.detail,
            type_uri="https://nex-platform.local/problems/model-rollout-rejected",
        )
    except (KeyError, TypeError, ValueError):
        return problem_response(
            request,
            status_code=422,
            error_code="MO_ROLLOUT_REQUEST_INVALID",
            title="Model rollout request invalid",
            detail="Model rollout request is invalid.",
            type_uri="https://nex-platform.local/problems/model-rollout-invalid",
        )
