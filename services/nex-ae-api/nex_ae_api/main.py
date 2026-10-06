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
from nex_ae_api.analytics import (
    DEFAULT_PROMPT_ANALYTICS_STORE,
    register_prompt_analytics_routes,
)
from nex_ae_api.artifacts import register_artifact_handoff_routes
from nex_ae_api.auth_sessions import register_auth_session_routes
from nex_ae_api.chat import register_chat_routes
from nex_ae_api.documents import register_document_library_routes
from nex_ae_api.generation_feedback import register_generation_feedback_routes
from nex_ae_api.mvp_acceptance_api import register_ae_mvp_acceptance_routes
from nex_ae_api.prompts import build_default_ae_prompt_store
from nex_ae_api.recovery_requests import register_generation_recovery_request_routes
from nex_ae_api.repaired_response_decisions import (
    register_repaired_response_decision_routes,
)
from nex_ae_api.repaired_responses import register_repaired_response_handoff_routes
from nex_ae_api.retrieval import register_retrieval_routes
from nex_ae_api.runtime_policy_api import register_runtime_policy_routes
from nex_ae_api.trace_projection import (
    InMemoryAeTraceProjectionSource,
    SqlAlchemyAeTraceProjectionSource,
    register_ae_trace_projection_routes,
)
from nex_ae_api.uploads import register_upload_routes
from nex_ae_api.upload_progress import register_upload_progress_routes
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
register_workspace_routes(app)
register_upload_routes(app)
register_upload_progress_routes(app)
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
