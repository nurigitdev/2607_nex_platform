from nex_runtime import SERVICE_SPECS, build_service_app
from nex_runtime.prompts import register_prompt_registry_routes
from nex_ae_api.analytics import (
    DEFAULT_PROMPT_ANALYTICS_STORE,
    register_prompt_analytics_routes,
)
from nex_ae_api.chat import register_chat_routes
from nex_ae_api.prompts import DEFAULT_AE_PROMPT_STORE
from nex_ae_api.retrieval import register_retrieval_routes
from nex_ae_api.workspace import register_workspace_routes


app = build_service_app(SERVICE_SPECS["nex-ae-api"])
register_workspace_routes(app)
register_chat_routes(app, analytics_store=DEFAULT_PROMPT_ANALYTICS_STORE)
register_retrieval_routes(app)
register_prompt_analytics_routes(app, store=DEFAULT_PROMPT_ANALYTICS_STORE)
register_prompt_registry_routes(
    app,
    store=DEFAULT_AE_PROMPT_STORE,
    expected_audience="nex-ae-api",
)
