from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
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
from nex_ae_api.chat import register_chat_routes
from nex_ae_api.documents import register_document_library_routes
from nex_ae_api.prompts import DEFAULT_AE_PROMPT_STORE
from nex_ae_api.recovery_requests import register_generation_recovery_request_routes
from nex_ae_api.retrieval import register_retrieval_routes
from nex_ae_api.uploads import register_upload_routes
from nex_ae_api.workspace import register_workspace_routes


SERVICE_SPEC = SERVICE_SPECS["nex-ae-api"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
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
register_workspace_routes(app)
register_upload_routes(app)
register_document_library_routes(app)
register_artifact_handoff_routes(app)
register_generation_compatibility_routes(app, expected_audience="nex-ae-api")
register_generation_recovery_policy_routes(app, expected_audience="nex-ae-api")
register_generation_recovery_request_routes(app)
register_chat_routes(app, analytics_store=DEFAULT_PROMPT_ANALYTICS_STORE)
register_retrieval_routes(app)
register_prompt_analytics_routes(app, store=DEFAULT_PROMPT_ANALYTICS_STORE)
register_prompt_registry_routes(
    app,
    store=DEFAULT_AE_PROMPT_STORE,
    expected_audience="nex-ae-api",
)
