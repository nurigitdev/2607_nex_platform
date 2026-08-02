from nex_runtime import SERVICE_SPECS, build_service_app
from nex_cx.generation import register_generation_routes
from nex_cx.ingestion import register_ingestion_routes


app = build_service_app(SERVICE_SPECS["nex-cx"])
register_generation_routes(app)
register_ingestion_routes(app)
