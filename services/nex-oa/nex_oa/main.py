from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)
from nex_oa.auth_boundary import register_identity_auth_boundary_routes
from nex_oa.subjects import (
    build_subject_registry_for_runtime,
    register_subject_registry_routes,
)


SERVICE_SPEC = SERVICE_SPECS["nex-oa"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
SUBJECT_REGISTRY = build_subject_registry_for_runtime(SERVICE_PERSISTENCE)
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
register_subject_registry_routes(app, registry=SUBJECT_REGISTRY)
register_identity_auth_boundary_routes(app)
