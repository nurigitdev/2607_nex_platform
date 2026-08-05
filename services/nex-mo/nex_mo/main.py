from nex_runtime import SERVICE_SPECS, attach_service_persistence_runtime, build_service_app
from nex_mo.providers import register_mock_provider_routes


SERVICE_SPEC = SERVICE_SPECS["nex-mo"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
register_mock_provider_routes(app)
