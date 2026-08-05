from nex_runtime import SERVICE_SPECS, attach_service_persistence_runtime, build_service_app
from nex_runtime.compatibility import register_generation_compatibility_routes
from nex_runtime.prompts import register_prompt_registry_routes
from nex_runtime.recovery import register_generation_recovery_policy_routes
from nex_cx.chunking import register_chunking_routes
from nex_cx.embedding_index import register_embedding_index_routes
from nex_cx.generation import register_generation_routes
from nex_cx.ingestion import DEFAULT_INGESTION_STORE, register_ingestion_routes
from nex_cx.lexical_index import register_lexical_index_routes
from nex_cx.processing import register_processing_routes
from nex_cx.prompts import DEFAULT_CX_PROMPT_STORE
from nex_cx.retrieval import register_retrieval_routes
from nex_cx.summary_embeddings import register_summary_embedding_routes
from nex_cx.summaries import register_summary_routes


SERVICE_SPEC = SERVICE_SPECS["nex-cx"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
register_generation_routes(app, retrieval_store=DEFAULT_INGESTION_STORE)
register_generation_compatibility_routes(app, expected_audience="nex-cx")
register_generation_recovery_policy_routes(app, expected_audience="nex-cx")
register_ingestion_routes(app, store=DEFAULT_INGESTION_STORE)
register_chunking_routes(app, store=DEFAULT_INGESTION_STORE)
register_embedding_index_routes(app, store=DEFAULT_INGESTION_STORE)
register_lexical_index_routes(app, store=DEFAULT_INGESTION_STORE)
register_processing_routes(
    app,
    store=DEFAULT_INGESTION_STORE,
    prompt_store=DEFAULT_CX_PROMPT_STORE,
    job_queue=SERVICE_PERSISTENCE.job_queue,
)
register_retrieval_routes(app, store=DEFAULT_INGESTION_STORE)
register_summary_routes(
    app,
    store=DEFAULT_INGESTION_STORE,
    prompt_store=DEFAULT_CX_PROMPT_STORE,
)
register_summary_embedding_routes(app, store=DEFAULT_INGESTION_STORE)
register_prompt_registry_routes(
    app,
    store=DEFAULT_CX_PROMPT_STORE,
    expected_audience="nex-cx",
)
