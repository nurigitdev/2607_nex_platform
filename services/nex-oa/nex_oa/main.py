from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    register_service_job_control_routes,
)


SERVICE_SPEC = SERVICE_SPECS["nex-oa"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
register_service_job_control_routes(
    app,
    service_id=SERVICE_SPEC.service_id,
    job_queue=SERVICE_PERSISTENCE.job_queue,
)
