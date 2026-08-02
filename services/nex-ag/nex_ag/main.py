from nex_runtime import SERVICE_SPECS, build_service_app
from nex_ag.generation_audit import register_generation_audit_routes
from nex_ag.readiness import register_readiness_routes


app = build_service_app(SERVICE_SPECS["nex-ag"])
register_readiness_routes(app)
register_generation_audit_routes(app)
