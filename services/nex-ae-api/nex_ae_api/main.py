import os

from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    build_service_token_admission_runtime,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)
from nex_runtime.compatibility import register_generation_compatibility_routes
from nex_runtime.prompts import register_prompt_registry_routes
from nex_runtime.recovery import register_generation_recovery_policy_routes

from nex_ae_api.agent_identity import SqlAlchemyAgentIdentityRegistry
from nex_ae_api.agent_registry_api import register_agent_registry_routes
from nex_ae_api.agent_runtime_foundation import attach_agent_runtime_foundation
from nex_ae_api.agent_runtime_operations import (
    SqlAlchemyAgentRuntimeOperationsSource,
    UnavailableAgentRuntimeOperationsSource,
    register_agent_runtime_operations_routes,
)
from nex_ae_api.analytics import (
    DEFAULT_PROMPT_ANALYTICS_STORE,
    register_prompt_analytics_routes,
)
from nex_ae_api.approval_decision_event_api import (
    ApprovalDecisionEventRouter,
    HttpEosBusinessApprovalDecisionClient,
    SqlAlchemyNslApprovalDecisionAdmission,
    register_approval_decision_event_routes,
)
from nex_ae_api.approval_facade import register_approval_facade_routes
from nex_ae_api.artifacts import register_artifact_handoff_routes
from nex_ae_api.auth_sessions import register_auth_session_routes
from nex_ae_api.chat import register_chat_routes
from nex_ae_api.claim_handoff_api import register_claim_handoff_routes
from nex_ae_api.documents import register_document_library_routes
from nex_ae_api.eos_outbox_event_api import register_eos_outbox_event_routes
from nex_ae_api.generation_feedback import register_generation_feedback_routes
from nex_ae_api.mvp_acceptance_api import register_ae_mvp_acceptance_routes
from nex_ae_api.nsl_approval_events import SqlAlchemyNslApprovalEventService
from nex_ae_api.private_object_store import (
    AePrivateObjectStorageError,
    build_ae_private_object_store,
)
from nex_ae_api.prompts import build_default_ae_prompt_store
from nex_ae_api.recovery_requests import register_generation_recovery_request_routes
from nex_ae_api.repaired_response_decisions import (
    register_repaired_response_decision_routes,
)
from nex_ae_api.repaired_responses import register_repaired_response_handoff_routes
from nex_ae_api.retrieval import register_retrieval_routes
from nex_ae_api.runtime_policy_api import register_runtime_policy_routes
from nex_ae_api.semantic_candidate_admission import (
    attach_semantic_candidate_admission,
)
from nex_ae_api.trace_projection import (
    InMemoryAeTraceProjectionSource,
    SqlAlchemyAeTraceProjectionSource,
    register_ae_trace_projection_routes,
)
from nex_ae_api.upload_progress import register_upload_progress_routes
from nex_ae_api.uploads import register_upload_routes
from nex_ae_api.voucher_attachment_api import register_voucher_attachment_routes
from nex_ae_api.voucher_attachment_storage import VoucherAttachmentObjectGateway
from nex_ae_api.voucher_attachments import SqlAlchemyVoucherAttachmentRepository
from nex_ae_api.work_result_event_api import register_work_result_event_routes
from nex_ae_api.work_result_events import SqlAlchemyWorkResultEventService
from nex_ae_api.workspace import register_workspace_routes

SERVICE_SPEC = SERVICE_SPECS["nex-ae-api"]
SERVICE_TOKEN_ADMISSION = build_service_token_admission_runtime(
    expected_audience=SERVICE_SPEC.service_id
)
app = build_service_app(
    SERVICE_SPEC,
    service_token_admission=SERVICE_TOKEN_ADMISSION,
)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
AE_PROMPT_STORE = build_default_ae_prompt_store(app)
AE_TRACE_PROJECTION_SOURCE = (
    SqlAlchemyAeTraceProjectionSource(SERVICE_PERSISTENCE.api_session_factory)
    if SERVICE_PERSISTENCE.api_session_factory is not None
    else InMemoryAeTraceProjectionSource()
)
register_service_job_control_routes(
    app,
    service_id=SERVICE_SPEC.service_id,
    job_queue=SERVICE_PERSISTENCE.job_queue,
)
register_service_log_retention_routes(
    app,
    service_id=SERVICE_SPEC.service_id,
    store=SERVICE_PERSISTENCE.service_log_store,
)
register_auth_session_routes(app)
register_approval_facade_routes(app)
register_workspace_routes(app)
register_upload_routes(app)
register_upload_progress_routes(app)
AE_VOUCHER_ATTACHMENT_REPOSITORY = (
    SqlAlchemyVoucherAttachmentRepository(SERVICE_PERSISTENCE.api_session_factory)
    if SERVICE_PERSISTENCE.api_session_factory is not None
    else None
)
try:
    AE_VOUCHER_ATTACHMENT_GATEWAY = (
        VoucherAttachmentObjectGateway(
            build_ae_private_object_store(),
            AE_VOUCHER_ATTACHMENT_REPOSITORY,
        )
        if AE_VOUCHER_ATTACHMENT_REPOSITORY is not None
        else None
    )
except AePrivateObjectStorageError:
    AE_VOUCHER_ATTACHMENT_GATEWAY = None
register_voucher_attachment_routes(
    app,
    repository=AE_VOUCHER_ATTACHMENT_REPOSITORY,
    gateway=AE_VOUCHER_ATTACHMENT_GATEWAY,
)
register_document_library_routes(app)
register_artifact_handoff_routes(app)
register_generation_compatibility_routes(app, expected_audience="nex-ae-api")
register_generation_recovery_policy_routes(app, expected_audience="nex-ae-api")
register_generation_recovery_request_routes(app)
register_chat_routes(
    app,
    analytics_store=DEFAULT_PROMPT_ANALYTICS_STORE,
    prompt_store=AE_PROMPT_STORE,
)
AE_AGENT_RUNTIME = attach_agent_runtime_foundation(
    app,
    SERVICE_PERSISTENCE,
    application=app.state.ae_chat_application_service,
)
register_claim_handoff_routes(
    app,
    admission=AE_AGENT_RUNTIME.admission,
)
AE_WORK_RESULT_EVENTS = (
    SqlAlchemyWorkResultEventService(
        SERVICE_PERSISTENCE.api_session_factory,
        runtime_jobs=AE_AGENT_RUNTIME.jobs,
    )
    if SERVICE_PERSISTENCE.api_session_factory is not None
    and AE_AGENT_RUNTIME.jobs is not None
    else None
)
app.state.ae_work_result_events = AE_WORK_RESULT_EVENTS
register_work_result_event_routes(app, admission=AE_WORK_RESULT_EVENTS)
AE_APPROVAL_DECISION_EVENTS = None
if (
    SERVICE_PERSISTENCE.api_session_factory is not None
    and AE_AGENT_RUNTIME.jobs is not None
    and os.getenv("NEX_AE_TO_EOS_SERVICE_TOKEN", "").strip()
):
    AE_APPROVAL_DECISION_EVENTS = ApprovalDecisionEventRouter(
        nsl_admission=SqlAlchemyNslApprovalDecisionAdmission(
            SERVICE_PERSISTENCE.api_session_factory,
            event_service=SqlAlchemyNslApprovalEventService(
                SERVICE_PERSISTENCE.api_session_factory,
                runtime_jobs=AE_AGENT_RUNTIME.jobs,
            ),
        ),
        business_admission=HttpEosBusinessApprovalDecisionClient(
            base_url=os.getenv("NEX_EOS_BASE_URL", "http://127.0.0.1:8107"),
            service_token=os.environ["NEX_AE_TO_EOS_SERVICE_TOKEN"],
        ),
    )
app.state.ae_approval_decision_events = AE_APPROVAL_DECISION_EVENTS
register_approval_decision_event_routes(
    app,
    admission=AE_APPROVAL_DECISION_EVENTS,
)
register_eos_outbox_event_routes(
    app,
    store=SERVICE_PERSISTENCE.operational_event_store,
)
register_agent_registry_routes(
    app,
    registry=(
        SqlAlchemyAgentIdentityRegistry(SERVICE_PERSISTENCE.api_session_factory)
        if SERVICE_PERSISTENCE.api_session_factory is not None
        else None
    ),
)
AE_SEMANTIC_CANDIDATE_ADMISSION = attach_semantic_candidate_admission(
    app,
    SERVICE_PERSISTENCE,
    AE_AGENT_RUNTIME,
    prompt_store=AE_PROMPT_STORE,
)
register_agent_runtime_operations_routes(
    app,
    source=(
        SqlAlchemyAgentRuntimeOperationsSource(
            SERVICE_PERSISTENCE.api_session_factory,
            queue_name=(
                AE_AGENT_RUNTIME.dispatcher.config.queue_name
                if AE_AGENT_RUNTIME.dispatcher is not None
                else "ae-runtime"
            ),
        )
        if SERVICE_PERSISTENCE.api_session_factory is not None
        else UnavailableAgentRuntimeOperationsSource()
    ),
)
register_generation_feedback_routes(app)
register_repaired_response_handoff_routes(app)
register_repaired_response_decision_routes(app)
register_retrieval_routes(app)
register_prompt_analytics_routes(app, store=DEFAULT_PROMPT_ANALYTICS_STORE)
register_prompt_registry_routes(
    app,
    store=AE_PROMPT_STORE,
    expected_audience="nex-ae-api",
)
register_runtime_policy_routes(app, store=AE_PROMPT_STORE)
register_ae_mvp_acceptance_routes(app)
register_ae_trace_projection_routes(app, source=AE_TRACE_PROJECTION_SOURCE)
