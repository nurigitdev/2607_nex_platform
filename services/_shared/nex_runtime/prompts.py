from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime.auth import DEFAULT_SERVICE_SCOPE, validate_authorization_header
from nex_runtime.problem import problem_response


@dataclass(frozen=True)
class PromptSeed:
    service_id: str
    purpose: str
    name: str
    owner_domain: str
    binding_key: str
    version: str
    role: str
    segment_order: int
    content: str
    model_capability: str
    metadata: dict[str, Any] = field(default_factory=dict)
    summary_max_chars: int | None = None
    summary_hard_limit_chars: int | None = None


@dataclass
class PromptRegistryStore:
    templates: dict[str, dict[str, Any]] = field(default_factory=dict)
    template_versions: dict[str, dict[str, Any]] = field(default_factory=dict)
    bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    render_events: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save_template(self, record: dict[str, Any]) -> dict[str, Any]:
        if record["prompt_template_id"] in self.templates:
            return self.templates[record["prompt_template_id"]]
        self.templates[record["prompt_template_id"]] = record
        return record

    def save_template_version(self, record: dict[str, Any]) -> dict[str, Any]:
        if record["prompt_template_version_id"] in self.template_versions:
            return self.template_versions[record["prompt_template_version_id"]]
        self.template_versions[record["prompt_template_version_id"]] = record
        return record

    def save_binding(self, record: dict[str, Any]) -> dict[str, Any]:
        existing = self.bindings.get(record["binding_key"])
        if (
            existing is not None
            and existing["prompt_template_version_id"]
            == record["prompt_template_version_id"]
        ):
            return existing
        self.bindings[record["binding_key"]] = record
        return record

    def get_binding(self, binding_key: str) -> dict[str, Any] | None:
        return self.bindings.get(binding_key)

    def get_template_version(
        self,
        prompt_template_version_id: str,
    ) -> dict[str, Any] | None:
        return self.template_versions.get(prompt_template_version_id)

    def save_render_event(self, record: dict[str, Any]) -> dict[str, Any]:
        self.render_events[record["prompt_render_event_id"]] = record
        return record

    def get_render_event(self, prompt_render_event_id: str) -> dict[str, Any] | None:
        return self.render_events.get(prompt_render_event_id)

    def list_bindings(self) -> list[dict[str, Any]]:
        return [self.bindings[key] for key in sorted(self.bindings)]


@dataclass(frozen=True)
class PromptRegistryError(Exception):
    status_code: int
    error_code: str
    detail: str


def seed_prompt_registry(
    store: PromptRegistryStore,
    seeds: list[PromptSeed],
) -> list[dict[str, Any]]:
    seeded: list[dict[str, Any]] = []
    for seed in seeds:
        template = store.save_template(build_prompt_template(seed))
        version = store.save_template_version(build_prompt_template_version(seed, template))
        seeded.append(store.save_binding(build_prompt_binding(seed, version)))
    return seeded


def build_prompt_template(seed: PromptSeed) -> dict[str, Any]:
    now = _utc_now()
    prompt_template_id = str(
        uuid5(
            NAMESPACE_URL,
            f"prompt-template:{seed.service_id}:{seed.purpose}:{seed.name}",
        )
    )
    return {
        "prompt_template_id": prompt_template_id,
        "service_id": seed.service_id,
        "purpose": seed.purpose,
        "name": seed.name,
        "owner_domain": seed.owner_domain,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
    }


def build_prompt_template_version(
    seed: PromptSeed,
    template: dict[str, Any],
) -> dict[str, Any]:
    content_sha256 = sha256_text(seed.content)
    now = _utc_now()
    prompt_template_version_id = str(
        uuid5(
            NAMESPACE_URL,
            "prompt-template-version:"
            f"{template['prompt_template_id']}:{seed.version}:{seed.role}:"
            f"{seed.segment_order}:{content_sha256}",
        )
    )
    return {
        "prompt_template_version_id": prompt_template_version_id,
        "prompt_template_id": template["prompt_template_id"],
        "service_id": seed.service_id,
        "purpose": seed.purpose,
        "version": seed.version,
        "role": seed.role,
        "segment_order": seed.segment_order,
        "content": seed.content,
        "content_sha256": content_sha256,
        "model_capability": seed.model_capability,
        "summary_max_chars": seed.summary_max_chars,
        "summary_hard_limit_chars": seed.summary_hard_limit_chars,
        "metadata": dict(seed.metadata),
        "status": "ACTIVE",
        "created_at": now,
    }


def build_prompt_binding(
    seed: PromptSeed,
    version: dict[str, Any],
) -> dict[str, Any]:
    prompt_binding_id = str(
        uuid5(NAMESPACE_URL, f"prompt-binding:{seed.service_id}:{seed.binding_key}")
    )
    return {
        "prompt_binding_id": prompt_binding_id,
        "binding_key": seed.binding_key,
        "prompt_template_version_id": version["prompt_template_version_id"],
        "service_id": seed.service_id,
        "purpose": seed.purpose,
        "status": "ACTIVE",
        "bound_at": _utc_now(),
    }


def render_prompt_from_binding(
    store: PromptRegistryStore,
    *,
    binding_key: str,
    variables: dict[str, Any],
    request_id: str,
    trace_id: str,
    user_prompt: str | None = None,
    output_text: str | None = None,
) -> dict[str, Any]:
    binding = store.get_binding(binding_key)
    if binding is None or binding["status"] != "ACTIVE":
        raise PromptRegistryError(
            status_code=404,
            error_code="prompt.binding_not_found",
            detail=f"Prompt binding was not found: {binding_key}",
        )

    version = store.get_template_version(binding["prompt_template_version_id"])
    if version is None or version["status"] != "ACTIVE":
        raise PromptRegistryError(
            status_code=404,
            error_code="prompt.template_version_not_found",
            detail=f"Prompt template version was not found: {binding_key}",
        )

    rendered_prompt = render_template(version["content"], variables)
    rendered_prompt_hash = sha256_text(rendered_prompt)
    event = build_prompt_render_event(
        binding=binding,
        version=version,
        rendered_prompt=rendered_prompt,
        rendered_prompt_hash=rendered_prompt_hash,
        variable_keys=sorted(variables),
        request_id=request_id,
        trace_id=trace_id,
        user_prompt=user_prompt,
        output_text=output_text,
    )
    return {
        "rendered_prompt": rendered_prompt,
        "render_event": store.save_render_event(event),
    }


def render_template(template: str, variables: dict[str, Any]) -> str:
    required = {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name
    }
    missing = sorted(field for field in required if field not in variables)
    if missing:
        raise PromptRegistryError(
            status_code=422,
            error_code="prompt.variable_missing",
            detail=f"Prompt variable is missing: {missing[0]}",
        )
    return template.format_map({key: str(value) for key, value in variables.items()})


def build_prompt_render_event(
    *,
    binding: dict[str, Any],
    version: dict[str, Any],
    rendered_prompt: str,
    rendered_prompt_hash: str,
    variable_keys: list[str],
    request_id: str,
    trace_id: str,
    user_prompt: str | None,
    output_text: str | None,
) -> dict[str, Any]:
    event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"prompt-render:{binding['prompt_binding_id']}:{trace_id}:{request_id}:{rendered_prompt_hash}",
        )
    )
    return {
        "prompt_render_event_schema_version": "prompt_render_event.v1",
        "prompt_render_event_id": event_id,
        "service_id": binding["service_id"],
        "prompt_binding_id": binding["prompt_binding_id"],
        "prompt_template_version_id": version["prompt_template_version_id"],
        "binding_key": binding["binding_key"],
        "purpose": binding["purpose"],
        "trace_id": trace_id,
        "request_id": request_id,
        "rendered_prompt_hash": rendered_prompt_hash,
        "rendered_prompt_preview": rendered_prompt[:240],
        "user_prompt_hash": sha256_text(user_prompt) if user_prompt else None,
        "output_hash": sha256_text(output_text) if output_text else None,
        "metadata": {
            "variable_keys": variable_keys,
            "role": version["role"],
            "model_capability": version["model_capability"],
        },
        "created_at": _utc_now(),
    }


def register_prompt_registry_routes(
    app: FastAPI,
    *,
    store: PromptRegistryStore,
    expected_audience: str,
) -> None:
    @app.get("/api/v1/prompts/bindings", response_model=None)
    def list_prompt_bindings(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_prompt_request(request, authorization, expected_audience)
        if auth_problem is not None:
            return auth_problem
        return {"bindings": store.list_bindings()}

    @app.get("/api/v1/prompts/render-events/{prompt_render_event_id}", response_model=None)
    def get_prompt_render_event(
        prompt_render_event_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_prompt_request(request, authorization, expected_audience)
        if auth_problem is not None:
            return auth_problem

        event = store.get_render_event(prompt_render_event_id)
        if event is None:
            return problem_response(
                request,
                status_code=404,
                error_code="prompt.render_event_not_found",
                title="Prompt render event not found",
                detail=f"Prompt render event was not found: {prompt_render_event_id}",
                type_uri="https://nex-platform.local/problems/prompt-render-event-not-found",
            )
        return event


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authorize_prompt_request(
    request: Request,
    authorization: str | None,
    expected_audience: str,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience=expected_audience,
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=f"{expected_audience} requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
