from nex_runtime import SERVICE_SPECS, attach_service_persistence_runtime, build_service_app
from nex_ag.generation_audit import register_generation_audit_routes
from nex_ag.operations import (
    register_job_operation_routes,
    register_operational_event_taxonomy_routes,
    register_operational_event_routes,
    register_unified_operation_routes,
)
from nex_ag.readiness import register_readiness_routes
from nex_ag.retrieval_policies import register_retrieval_policy_routes


SERVICE_SPEC = SERVICE_SPECS["nex-ag"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
register_readiness_routes(app)
register_generation_audit_routes(app)
register_retrieval_policy_routes(app)
register_unified_operation_routes(app)
register_operational_event_taxonomy_routes(app)
register_operational_event_routes(app)
register_job_operation_routes(app)
