from nex_runtime import SERVICE_SPECS, build_service_app
from nex_runtime.prompts import register_prompt_registry_routes
from nex_ae_api.chat import register_chat_routes
from nex_ae_api.prompts import DEFAULT_AE_PROMPT_STORE
from nex_ae_api.retrieval import register_retrieval_routes


app = build_service_app(SERVICE_SPECS["nex-ae-api"])
register_chat_routes(app)
register_retrieval_routes(app)
register_prompt_registry_routes(
    app,
    store=DEFAULT_AE_PROMPT_STORE,
    expected_audience="nex-ae-api",
)
