from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import nex_ae_api.semantic_candidate_admission as admission_module
import pytest
from nex_ae_api.agent_context import ContextBuildRequest
from nex_ae_api.semantic_candidate_admission import (
    SemanticCandidateAdmissionError,
    SemanticCandidateAdmissionResult,
    SemanticCandidateAdmissionRuntime,
    attach_semantic_candidate_admission,
)
from nex_ae_api.semantic_candidate_evidence import LocalSemanticCandidateStorage
from nex_runtime.prompts import PromptRegistryStore
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _app() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


def _persistence() -> SimpleNamespace:
    factory = sessionmaker(
        bind=create_engine("sqlite+pysqlite://", future=True),
        autoflush=False,
        expire_on_commit=False,
    )
    return SimpleNamespace(api_session_factory=factory)


def _environment(mode: str, **overrides: str) -> dict[str, str]:
    return {
        "NEX_AE_PLANNING_MODE": mode,
        "NEX_MO_BASE_URL": "http://127.0.0.1:8105",
        **overrides,
    }


def test_disabled_attachment_has_no_persistence_or_client_dependency() -> None:
    app = _app()
    runtime = attach_semantic_candidate_admission(
        app,
        SimpleNamespace(api_session_factory=None),
        SimpleNamespace(mode="disabled", admission=None),
        prompt_store=PromptRegistryStore(),
        environ=_environment("disabled"),
    )
    assert runtime.mode == "disabled"
    assert runtime.available is False
    assert runtime.unavailable_reason == "planning_disabled"
    assert app.state.ae_semantic_candidate_admission is runtime


def test_required_attachment_rejects_in_memory_candidate_payloads() -> None:
    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        attach_semantic_candidate_admission(
            _app(),
            _persistence(),
            SimpleNamespace(mode="required", admission=object()),
            prompt_store=PromptRegistryStore(),
            environ=_environment("required"),
        )
    assert raised.value.error_code == "SEMANTIC_CANDIDATE_STORAGE_REQUIRED"
    assert raised.value.retryable is True


def test_required_attachment_accepts_durable_private_storage(tmp_path) -> None:
    runtime = attach_semantic_candidate_admission(
        _app(),
        _persistence(),
        SimpleNamespace(mode="required", admission=object()),
        prompt_store=PromptRegistryStore(),
        environ=_environment(
            "required",
            NEX_AE_PRIVATE_STORAGE_MODE="FILESYSTEM",
            NEX_AE_SEMANTIC_CANDIDATE_STORAGE_ROOT=str(tmp_path),
        ),
    )
    assert runtime.available is True
    assert isinstance(runtime.service.candidate_storage, LocalSemanticCandidateStorage)


@pytest.mark.parametrize(
    ("planning_mode", "runtime_mode"),
    [("required", "shadow"), ("shadow", "disabled")],
)
def test_attachment_rejects_incompatible_runtime_modes(
    planning_mode: str, runtime_mode: str
) -> None:
    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        attach_semantic_candidate_admission(
            _app(),
            _persistence(),
            SimpleNamespace(mode=runtime_mode, admission=object()),
            prompt_store=PromptRegistryStore(),
            environ=_environment(planning_mode),
        )
    assert raised.value.error_code == "SEMANTIC_RUNTIME_MODE_MISMATCH"


def test_attachment_persistence_boundary_is_required_only() -> None:
    app = _app()
    shadow = attach_semantic_candidate_admission(
        app,
        SimpleNamespace(api_session_factory=None),
        SimpleNamespace(mode="shadow", admission=None),
        prompt_store=PromptRegistryStore(),
        environ=_environment("shadow"),
    )
    assert shadow.available is False
    assert shadow.unavailable_reason == "persistence_not_configured"

    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        attach_semantic_candidate_admission(
            _app(),
            SimpleNamespace(api_session_factory=None),
            SimpleNamespace(mode="required", admission=None),
            prompt_store=PromptRegistryStore(),
            environ=_environment("required"),
        )
    assert raised.value.error_code == "SEMANTIC_ADMISSION_PERSISTENCE_REQUIRED"


class _Capabilities:
    def __init__(self, snapshot=None) -> None:
        self.snapshot = snapshot
        self.calls = []

    def get_latest(self, *, tenant_id):
        self.calls.append(tenant_id)
        return self.snapshot


class _AdmissionService:
    def __init__(self, snapshot=None) -> None:
        self.capabilities = _Capabilities(snapshot)
        self.clock = lambda: datetime(2026, 10, 17, 3, 0, tzinfo=UTC)
        self.requests = []

    def admit_and_compile(self, request):
        self.requests.append(request)
        return SemanticCandidateAdmissionResult(
            mode="required",
            status="COMPILED",
            directive="ACCEPT_RUNTIME_WORK",
            agent_execution_id="10000000-0000-4000-8000-000000000659",
        )


class _Scheduler:
    def __init__(self) -> None:
        self.calls = []

    def schedule_next(self, **kwargs):
        self.calls.append(kwargs)
        return {"runtime_job_id": "scheduled"}


def _chat_payload(**overrides):
    value = {
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "interaction_id": "20000000-0000-4000-8000-000000000659",
        "workspace_id": "30000000-0000-4000-8000-000000000659",
        "conversation_id": "40000000-0000-4000-8000-000000000659",
        "user_message": "  예산 현황을 정리해줘.  ",
        "conversation_summary": "  지난 대화 요약  ",
    }
    value.update(overrides)
    return value


def _runtime_policy():
    return {
        "compatibility_rule": {
            "rule_id": "ae.compatibility.general-answer",
            "rule_version": "v1",
            "rule_hash": "a" * 64,
        },
        "intent_decision": {
            "retrieval_required": True,
            "execution_mode": "GROUNDED_ANSWER",
        },
    }


@pytest.mark.parametrize("snapshot", [None, {"capability_snapshot_id": "existing"}])
def test_runtime_admit_chat_builds_scoped_request_and_capability_snapshot(
    snapshot,
) -> None:
    service = _AdmissionService(snapshot)
    runtime = SemanticCandidateAdmissionRuntime(
        mode="required", available=True, service=service
    )
    retrieval = {
        "retrieval_package_id": "package-a",
        "package_hash": "b" * 64,
        "status": "READY",
        "evidence_items": [
            {"document_title": "  예산 문서  "},
            {"source_label": "근거 A"},
        ],
    }

    result = runtime.admit_chat(
        payload=_chat_payload(),
        runtime_policy=_runtime_policy(),
        retrieval_package=retrieval,
        request_id="request-a",
        trace_id="c" * 32,
    )

    assert result.status == "COMPILED"
    request = service.requests[0]
    assert request.user_prompt == "예산 현황을 정리해줘."
    assert request.base_context["conversation_summary"] == "지난 대화 요약"
    assert request.base_context["resource_label_hints"] == ["예산 문서", "근거 A"]
    assert request.retrieval_enabled is True
    assert request.authorized_resource_context_available is True
    assert request.trusted_execution_mode == "GROUNDED_ANSWER"
    if snapshot is None:
        assert request.capability_snapshot["tenant_id"] == "tenant-a"
    else:
        assert request.capability_snapshot is snapshot


def test_required_runtime_schedules_compiled_execution() -> None:
    service = _AdmissionService()
    scheduler = _Scheduler()
    runtime = SemanticCandidateAdmissionRuntime(
        mode="required",
        available=True,
        service=service,
        scheduler=scheduler,
    )

    runtime.admit_chat(
        payload=_chat_payload(),
        runtime_policy=_runtime_policy(),
        retrieval_package=None,
        request_id="request-a",
        trace_id="c" * 32,
    )

    assert scheduler.calls == [
        {
            "tenant_id": "tenant-a",
            "execution_id": "10000000-0000-4000-8000-000000000659",
            "now": "2026-10-17T03:00:00Z",
        }
    ]


def test_shadow_runtime_does_not_schedule_compiled_execution() -> None:
    service = _AdmissionService()
    scheduler = _Scheduler()
    runtime = SemanticCandidateAdmissionRuntime(
        mode="shadow",
        available=True,
        service=service,
        scheduler=scheduler,
    )

    runtime.admit_chat(
        payload=_chat_payload(),
        runtime_policy=_runtime_policy(),
        retrieval_package=None,
        request_id="request-a",
        trace_id="c" * 32,
    )

    assert scheduler.calls == []


def test_runtime_disabled_and_unavailable_paths_are_explicit() -> None:
    disabled = SemanticCandidateAdmissionRuntime(
        mode="disabled", available=False, service=None
    )
    result = disabled.admit_chat(
        payload={},
        runtime_policy={},
        retrieval_package=None,
        request_id="request-a",
        trace_id="a" * 32,
    )
    assert result.status == "DISABLED"

    unavailable = SemanticCandidateAdmissionRuntime(
        mode="required", available=False, service=None
    )
    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        unavailable.admit_chat(
            payload={},
            runtime_policy={},
            retrieval_package=None,
            request_id="request-a",
            trace_id="a" * 32,
        )
    assert raised.value.error_code == "SEMANTIC_ADMISSION_NOT_READY"


def _context_request(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "principal_id": "user-a",
        "agent_id": "10000000-0000-4000-8000-000000000660",
        "execution_id": "20000000-0000-4000-8000-000000000660",
        "workspace_id": "30000000-0000-4000-8000-000000000660",
        "conversation_id": "40000000-0000-4000-8000-000000000660",
        "interaction_id": "50000000-0000-4000-8000-000000000660",
        "work_intent_ref": {},
    }
    values.update(overrides)
    return ContextBuildRequest(**values)


def test_chat_context_resolver_is_owner_scoped_and_retrieval_aware() -> None:
    resolver = admission_module._ChatTrustedContextResolver(
        tenant_id="tenant-a",
        owner_subject_id="user-a",
        interaction_id="50000000-0000-4000-8000-000000000660",
        user_prompt="private prompt",
        retrieval_package=None,
        as_of="2026-10-17T03:00:00Z",
    )
    plain = resolver.resolve(_context_request())
    assert plain.retrieval_refs == ()
    assert len(plain.context_manifest) == 1

    retrieval_resolver = admission_module._ChatTrustedContextResolver(
        **{
            **vars(resolver),
            "retrieval_package": {
                "retrieval_package_id": "package-a",
                "package_hash": "sha256:" + "d" * 64,
                "status": "READY",
            },
        }
    )
    resolved = retrieval_resolver.resolve(_context_request())
    assert resolved.retrieval_refs == resolved.evidence_refs
    assert len(resolved.context_manifest) == 2

    with pytest.raises(SemanticCandidateAdmissionError) as raised:
        resolver.resolve(_context_request(principal_id="other-user"))
    assert raised.value.error_code == "TRUSTED_CONTEXT_SCOPE_MISMATCH"


def test_package_hash_and_resource_label_helpers_cover_fallback_boundaries() -> None:
    valid = "sha256:" + "a" * 64
    assert admission_module._package_hash({"package_hash": valid}) == valid
    assert (
        admission_module._package_hash({"package_hash": "b" * 64})
        == "sha256:" + "b" * 64
    )
    assert admission_module._package_hash({"package_hash": "B" * 64}).startswith(
        "sha256:"
    )
    fallback = admission_module._package_hash(
        {"retrieval_package_id": "p", "status": "READY", "evidence_items": "bad"}
    )
    assert fallback.startswith("sha256:")

    assert admission_module._resource_label_hints(None) == []
    assert admission_module._resource_label_hints({"evidence_items": "bad"}) == []
    items = [None, {}, {"document_title": "A", "source_label": "ignored"}]
    items.append({"resource_label": "A"})
    items.extend({"source_label": f"L{i}"} for i in range(40))
    labels = admission_module._resource_label_hints({"evidence_items": items})
    assert labels[0] == "A"
    assert len(labels) == 32


@pytest.mark.parametrize("value", [None, "", "x" * 5])
def test_request_text_helpers_reject_missing_or_invalid_values(value) -> None:
    if value is None:
        with pytest.raises(SemanticCandidateAdmissionError) as raised:
            admission_module._request_text({}, "tenant_id", 4)
        assert raised.value.error_code == "SEMANTIC_ADMISSION_SCOPE_REQUIRED"
    else:
        with pytest.raises(SemanticCandidateAdmissionError) as raised:
            admission_module._optional_request_text(value, 4)
        assert raised.value.error_code == "SEMANTIC_ADMISSION_REQUEST_INVALID"


def test_timestamp_normalizes_naive_datetime() -> None:
    assert admission_module._timestamp(datetime(2026, 10, 17, 3, 0)) == (  # noqa: DTZ001
        "2026-10-17T03:00:00Z"
    )
