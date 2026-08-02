from nex_runtime import SERVICE_SPECS, build_service_app
from nex_cx.chunking import register_chunking_routes
from nex_cx.generation import register_generation_routes
from nex_cx.ingestion import DEFAULT_INGESTION_STORE, register_ingestion_routes


app = build_service_app(SERVICE_SPECS["nex-cx"])
register_generation_routes(app)
register_ingestion_routes(app, store=DEFAULT_INGESTION_STORE)
register_chunking_routes(app, store=DEFAULT_INGESTION_STORE)
