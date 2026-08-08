from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    register_service_job_control_routes,
)
from nex_ag.generation_audit import register_generation_audit_routes
from nex_ag.operations import (
    attach_ag_operations_source_runtime,
    register_job_operation_routes,
    register_operation_source_readiness_routes,
    register_operational_event_taxonomy_routes,
    register_operational_event_routes,
    register_service_log_routes,
    register_unified_operation_routes,
)
from nex_ag.readiness import register_readiness_routes
from nex_ag.retrieval_policies import register_retrieval_policy_routes


SERVICE_SPEC = SERVICE_SPECS["nex-ag"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
register_service_job_control_routes(
    app,
    service_id=SERVICE_SPEC.service_id,
    job_queue=SERVICE_PERSISTENCE.job_queue,
)
OPERATIONS_SOURCE_RUNTIME = attach_ag_operations_source_runtime(app)
OPERATIONS_SOURCE_REGISTRY = OPERATIONS_SOURCE_RUNTIME.registry
register_readiness_routes(app)
register_generation_audit_routes(app)
register_retrieval_policy_routes(app)
register_operation_source_readiness_routes(app, runtime=OPERATIONS_SOURCE_RUNTIME)
register_unified_operation_routes(
    app,
    event_store=SERVICE_PERSISTENCE.operational_event_store,
    registry=OPERATIONS_SOURCE_REGISTRY,
    runtime=OPERATIONS_SOURCE_RUNTIME,
)
register_operational_event_taxonomy_routes(app)
if OPERATIONS_SOURCE_REGISTRY is None:
    register_operational_event_routes(
        app,
        store=SERVICE_PERSISTENCE.operational_event_store,
    )
    register_service_log_routes(
        app,
        service_log_stores={"nex-ag": SERVICE_PERSISTENCE.service_log_store},
    )
else:
    register_operational_event_routes(app, registry=OPERATIONS_SOURCE_REGISTRY)
    register_service_log_routes(app, registry=OPERATIONS_SOURCE_REGISTRY)
register_job_operation_routes(
    app,
    event_store=SERVICE_PERSISTENCE.operational_event_store,
    registry=OPERATIONS_SOURCE_REGISTRY,
    audit_event_store=SERVICE_PERSISTENCE.operational_event_store,
)
