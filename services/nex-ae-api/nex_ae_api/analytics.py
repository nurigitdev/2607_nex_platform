from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)


DEFAULT_TENANT_ID = "local-tenant"
DEFAULT_USER_ID = "local-user"


@dataclass(frozen=True)
class PromptAnalyticsError(Exception):
    status_code: int
    error_code: str
    detail: str


@dataclass
class PromptAnalyticsStore:
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    prompt_events: dict[str, dict[str, Any]] = field(default_factory=dict)
    intent_classifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    user_task_profiles: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    automation_recommendations: dict[str, dict[str, Any]] = field(default_factory=dict)
    recommendation_ids_by_user: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def record_prompt_analytics(
        self,
        *,
        user_message: str,
        tenant_id: str,
        user_id: str,
        chat_interaction_id: str,
        trace_id: str,
        request_id: str,
        retrieval_used: bool,
        retrieval_outcome: str | None,
        generation_outcome: str | None,
        locale: str | None = None,
        source_channel: str = "chat",
    ) -> dict[str, Any]:
        event = build_prompt_event(
            user_message=user_message,
            tenant_id=tenant_id,
            user_id=user_id,
            chat_interaction_id=chat_interaction_id,
            trace_id=trace_id,
            request_id=request_id,
            retrieval_used=retrieval_used,
            retrieval_outcome=retrieval_outcome,
            generation_outcome=generation_outcome,
            locale=locale,
            source_channel=source_channel,
        )
        classification = build_intent_classification(event, user_message=user_message)
        profile = update_user_task_profile(
            self.user_task_profiles.get((tenant_id, user_id)),
            event=event,
            classification=classification,
        )
        recommendation = build_automation_recommendation(
            event=event,
            profile=profile,
            classification=classification,
        )

        self.prompt_events[event["prompt_event_id"]] = event
        self.intent_classifications[event["prompt_event_id"]] = classification
        self.user_task_profiles[(tenant_id, user_id)] = profile
        if recommendation is not None:
            self.automation_recommendations[
                recommendation["automation_recommendation_id"]
            ] = recommendation
            user_key = (tenant_id, user_id)
            ids = self.recommendation_ids_by_user.setdefault(user_key, [])
            if recommendation["automation_recommendation_id"] not in ids:
                ids.append(recommendation["automation_recommendation_id"])

        snapshot = {
            "prompt_analytics_schema_version": "ae_prompt_analytics.v1",
            "prompt_event": event,
            "intent_classification": classification,
            "user_task_profile": profile,
            "automation_recommendation": recommendation,
        }
        self.snapshots[event["prompt_event_id"]] = snapshot
        return snapshot

    def get_snapshot(self, prompt_event_id: str) -> dict[str, Any] | None:
        return self.snapshots.get(prompt_event_id)

    def get_user_task_profile(self, *, tenant_id: str, user_id: str) -> dict[str, Any] | None:
        return self.user_task_profiles.get((tenant_id, user_id))

    def list_user_recommendations(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        return [
            self.automation_recommendations[recommendation_id]
            for recommendation_id in self.recommendation_ids_by_user.get((tenant_id, user_id), [])
        ]


DEFAULT_PROMPT_ANALYTICS_STORE = PromptAnalyticsStore()


def register_prompt_analytics_routes(
    app: FastAPI,
    *,
    store: PromptAnalyticsStore,
) -> None:
    @app.get("/api/v1/analytics/prompt-events/{prompt_event_id}", response_model=None)
    def get_prompt_event(
        prompt_event_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        snapshot = store.get_snapshot(prompt_event_id)
        if snapshot is None:
            return _analytics_problem_response(
                request,
                PromptAnalyticsError(
                    status_code=404,
                    error_code="ae.prompt_event_not_found",
                    detail=f"Prompt event was not found: {prompt_event_id}",
                ),
            )
        return snapshot

    @app.get("/api/v1/analytics/users/{user_id}/task-profile", response_model=None)
    def get_user_task_profile(
        user_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str = Query(default=DEFAULT_TENANT_ID),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        profile = store.get_user_task_profile(tenant_id=tenant_id, user_id=user_id)
        if profile is None:
            return _analytics_problem_response(
                request,
                PromptAnalyticsError(
                    status_code=404,
                    error_code="ae.user_task_profile_not_found",
                    detail=f"User task profile was not found: {tenant_id}/{user_id}",
                ),
            )
        return profile

    @app.get("/api/v1/analytics/users/{user_id}/recommendations", response_model=None)
    def list_user_recommendations(
        user_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        tenant_id: str = Query(default=DEFAULT_TENANT_ID),
    ):
        auth_problem = _authorize_ae_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        return {
            "recommendations": store.list_user_recommendations(
                tenant_id=tenant_id,
                user_id=user_id,
            )
        }


def build_prompt_event(
    *,
    user_message: str,
    tenant_id: str,
    user_id: str,
    chat_interaction_id: str,
    trace_id: str,
    request_id: str,
    retrieval_used: bool,
    retrieval_outcome: str | None,
    generation_outcome: str | None,
    locale: str | None = None,
    source_channel: str = "chat",
) -> dict[str, Any]:
    prompt = user_message.strip()
    prompt_hash = sha256_text(prompt)
    event_id = str(uuid5(NAMESPACE_URL, f"ae-prompt-event:{trace_id}:{request_id}:{prompt_hash}"))
    return {
        "prompt_event_schema_version": "ae_prompt_event.v1",
        "prompt_event_id": event_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "chat_interaction_id": chat_interaction_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "prompt_hash": prompt_hash,
        "prompt_preview": prompt[:240],
        "prompt_char_count": len(prompt),
        "prompt_token_estimate": estimate_prompt_tokens(prompt),
        "locale": locale,
        "source_channel": source_channel,
        "retrieval_used": retrieval_used,
        "retrieval_outcome": retrieval_outcome,
        "generation_outcome": generation_outcome,
        "metadata": {
            "raw_prompt_stored": False,
        },
        "occurred_at": _utc_now(),
    }


def build_intent_classification(
    event: dict[str, Any],
    *,
    user_message: str,
) -> dict[str, Any]:
    intent = classify_prompt_intent(user_message)
    classification_id = str(
        uuid5(
            NAMESPACE_URL,
            f"ae-intent:{event['prompt_event_id']}:{intent['intent_label']}:{intent['task_category']}",
        )
    )
    return {
        "intent_classification_schema_version": "ae_prompt_intent_classification.v1",
        "intent_classification_id": classification_id,
        "prompt_event_id": event["prompt_event_id"],
        "intent_label": intent["intent_label"],
        "task_category": intent["task_category"],
        "confidence": intent["confidence"],
        "classifier_profile_id": "mock-intent-classifier-v1",
        "prompt_template_version_id": None,
        "evidence": {
            "matched_terms": intent["matched_terms"],
        },
        "created_at": _utc_now(),
    }


def classify_prompt_intent(user_message: str) -> dict[str, Any]:
    lowered = user_message.lower()
    rules = [
        (
            ("summarize", "summary", "brief"),
            "summarize_document",
            "document_summary",
            0.86,
        ),
        (
            ("upload", "file", "document"),
            "manage_uploaded_content",
            "content_management",
            0.78,
        ),
        (
            ("automate", "automation", "workflow", "repeat"),
            "request_automation",
            "workflow_automation",
            0.82,
        ),
    ]
    for terms, intent_label, task_category, confidence in rules:
        matched_terms = [term for term in terms if term in lowered]
        if matched_terms:
            return {
                "intent_label": intent_label,
                "task_category": task_category,
                "confidence": confidence,
                "matched_terms": matched_terms,
            }
    return {
        "intent_label": "general_question",
        "task_category": "knowledge_work",
        "confidence": 0.55,
        "matched_terms": [],
    }


def update_user_task_profile(
    existing: dict[str, Any] | None,
    *,
    event: dict[str, Any],
    classification: dict[str, Any],
) -> dict[str, Any]:
    now = _utc_now()
    frequency = existing["prompt_frequency"] if existing else {"total": 0, "by_task_category": {}}
    by_category = dict(frequency.get("by_task_category", {}))
    task_category = classification["task_category"]
    by_category[task_category] = by_category.get(task_category, 0) + 1
    total = int(frequency.get("total", 0)) + 1
    dominant = [
        {"task_category": category, "count": count}
        for category, count in sorted(
            by_category.items(),
            key=lambda item: (-item[1], item[0]),
        )[:3]
    ]
    return {
        "user_task_profile_schema_version": "ae_user_task_profile.v1",
        "user_task_profile_id": existing["user_task_profile_id"]
        if existing
        else str(uuid5(NAMESPACE_URL, f"ae-user-task-profile:{event['tenant_id']}:{event['user_id']}")),
        "tenant_id": event["tenant_id"],
        "user_id": event["user_id"],
        "role_title": existing.get("role_title") if existing else None,
        "department": existing.get("department") if existing else None,
        "dominant_task_categories": dominant,
        "prompt_frequency": {
            "total": total,
            "by_task_category": by_category,
        },
        "automation_readiness_score": min(1.0, max(by_category.values()) / 3),
        "last_computed_at": now,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }


def build_automation_recommendation(
    *,
    event: dict[str, Any],
    profile: dict[str, Any],
    classification: dict[str, Any],
) -> dict[str, Any] | None:
    category_count = profile["prompt_frequency"]["by_task_category"][
        classification["task_category"]
    ]
    if category_count < 2 and classification["task_category"] != "workflow_automation":
        return None

    recommendation_id = str(
        uuid5(
            NAMESPACE_URL,
            "ae-automation-recommendation:"
            f"{event['tenant_id']}:{event['user_id']}:{classification['task_category']}",
        )
    )
    confidence = min(0.95, 0.55 + category_count * 0.1)
    return {
        "automation_recommendation_schema_version": "ae_automation_recommendation.v1",
        "automation_recommendation_id": recommendation_id,
        "tenant_id": event["tenant_id"],
        "user_id": event["user_id"],
        "source_prompt_event_id": event["prompt_event_id"],
        "user_task_profile_id": profile["user_task_profile_id"],
        "recommendation_type": "workflow",
        "task_category": classification["task_category"],
        "title": f"Create a reusable {classification['task_category']} workflow",
        "rationale_summary": (
            "Repeated prompt patterns suggest this task could be packaged as a "
            "guided automation."
        ),
        "confidence": round(confidence, 4),
        "status": "PROPOSED",
        "metadata": {
            "intent_label": classification["intent_label"],
            "category_prompt_count": category_count,
        },
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }


def estimate_prompt_tokens(prompt: str) -> int:
    if not prompt:
        return 0
    return max(1, (len(prompt) + 3) // 4)


def owner_scope_from_payload(payload: dict[str, Any]) -> tuple[str, str]:
    tenant_id = payload.get("tenant_id", DEFAULT_TENANT_ID)
    user_id = payload.get("user_id", DEFAULT_USER_ID)
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise PromptAnalyticsError(
            status_code=400,
            error_code="ae.analytics_owner_invalid",
            detail="tenant_id must be a non-empty string.",
        )
    if not isinstance(user_id, str) or not user_id.strip():
        raise PromptAnalyticsError(
            status_code=400,
            error_code="ae.analytics_owner_invalid",
            detail="user_id must be a non-empty string.",
        )
    return tenant_id.strip(), user_id.strip()


def record_chat_prompt_analytics(
    analytics_store: PromptAnalyticsStore | None,
    *,
    source_payload: dict[str, Any],
    chat_record: dict[str, Any],
    retrieval_used: bool,
) -> dict[str, Any] | None:
    if analytics_store is None:
        return None

    tenant_id, user_id = owner_scope_from_payload(source_payload)
    retrieval = chat_record.get("retrieval")
    generation = chat_record.get("generation")
    return analytics_store.record_prompt_analytics(
        user_message=source_payload["user_message"],
        tenant_id=tenant_id,
        user_id=user_id,
        chat_interaction_id=chat_record["interaction_id"],
        trace_id=chat_record["trace_id"],
        request_id=chat_record["request_id"],
        retrieval_used=retrieval_used,
        retrieval_outcome=retrieval["cx_status"] if retrieval else None,
        generation_outcome=generation["finish_reason"] if generation else chat_record["status"],
        locale=source_payload.get("locale") if isinstance(source_payload.get("locale"), str) else None,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authorize_ae_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-ae-api",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail="AE API requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _analytics_problem_response(
    request: Request,
    exc: PromptAnalyticsError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Prompt analytics request failed",
        detail=exc.detail,
        type_uri="https://nex-platform.local/problems/prompt-analytics-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
