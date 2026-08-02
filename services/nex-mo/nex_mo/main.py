from nex_runtime import SERVICE_SPECS, build_service_app
from nex_mo.providers import register_mock_provider_routes


app = build_service_app(SERVICE_SPECS["nex-mo"])
register_mock_provider_routes(app)
