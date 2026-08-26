from nex_runtime import (
    PERSISTENCE_MODE_POSTGRES,
    SERVICE_SPECS,
    ServicePersistenceRuntime,
    attach_service_persistence_runtime,
    build_service_app,
    register_service_job_control_routes,
    register_service_log_retention_routes,
)
from nex_runtime.compatibility import register_generation_compatibility_routes
from nex_runtime.prompts import register_prompt_registry_routes
from nex_runtime.recovery import register_generation_recovery_policy_routes
from nex_cx.chunking import register_chunking_routes
from nex_cx.document_library import register_document_library_routes
from nex_cx.embedding_index import register_embedding_index_routes
from nex_cx.generation import DEFAULT_GENERATION_STORE, register_generation_routes
from nex_cx.ingestion import (
    DEFAULT_INGESTION_STORE,
    CxStorageConfig,
    build_storage_config,
    register_ingestion_routes,
)
from nex_cx.lexical_index import register_lexical_index_routes
from nex_cx.processing import register_processing_routes
from nex_cx.prompts import DEFAULT_CX_PROMPT_STORE
from nex_cx.repository import CxContentRepository, SqlAlchemyCxContentRepository
from nex_cx.retrieval import register_retrieval_routes
from nex_cx.remediation_execution import (
    RemediationExecutionStoreProtocol,
    SqlAlchemyRemediationExecutionStore,
    register_remediation_execution_routes,
)
from nex_cx.summary_embeddings import register_summary_embedding_routes
from nex_cx.summaries import register_summary_routes


def build_cx_content_repository(
    runtime: ServicePersistenceRuntime,
    *,
    storage_config: CxStorageConfig,
) -> CxContentRepository:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyCxContentRepository(
            runtime.api_session_factory,
            local_source_root=storage_config.source_root,
        )
    return DEFAULT_INGESTION_STORE.content_repository


def build_cx_remediation_execution_store(
    runtime: ServicePersistenceRuntime,
) -> RemediationExecutionStoreProtocol | None:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyRemediationExecutionStore(
            runtime.api_session_factory,
            database_env=runtime.database_env,
            redacted_database_url=runtime.redacted_database_url,
        )
    return None


SERVICE_SPEC = SERVICE_SPECS["nex-cx"]
app = build_service_app(SERVICE_SPEC)
SERVICE_PERSISTENCE = attach_service_persistence_runtime(app, SERVICE_SPEC)
CX_STORAGE_CONFIG = build_storage_config()
CX_CONTENT_REPOSITORY = build_cx_content_repository(
    SERVICE_PERSISTENCE,
    storage_config=CX_STORAGE_CONFIG,
)
DEFAULT_INGESTION_STORE.content_repository = CX_CONTENT_REPOSITORY
CX_PROCESSING_RUN_REPOSITORY: CxContentRepository | None = (
    CX_CONTENT_REPOSITORY
    if SERVICE_PERSISTENCE.mode == PERSISTENCE_MODE_POSTGRES
    else None
)
CX_REMEDIATION_EXECUTION_STORE = build_cx_remediation_execution_store(
    SERVICE_PERSISTENCE,
)
register_service_job_control_routes(
    app,
    service_id=SERVICE_SPEC.service_id,
    job_queue=SERVICE_PERSISTENCE.job_queue,
)
register_service_log_retention_routes(
    app,
    service_id=SERVICE_SPEC.service_id,
    store=SERVICE_PERSISTENCE.service_log_store,
)
register_generation_routes(
    app,
    store=DEFAULT_GENERATION_STORE,
    retrieval_store=DEFAULT_INGESTION_STORE,
)
register_remediation_execution_routes(
    app,
    generation_store=DEFAULT_GENERATION_STORE,
    execution_store=CX_REMEDIATION_EXECUTION_STORE,
    job_queue=SERVICE_PERSISTENCE.job_queue,
)
register_generation_compatibility_routes(app, expected_audience="nex-cx")
register_generation_recovery_policy_routes(app, expected_audience="nex-cx")
register_ingestion_routes(
    app,
    store=DEFAULT_INGESTION_STORE,
    storage_config=CX_STORAGE_CONFIG,
    database_env=SERVICE_PERSISTENCE.database_env,
    redacted_database_url=SERVICE_PERSISTENCE.redacted_database_url,
    source_kind=(
        "postgres-read"
        if SERVICE_PERSISTENCE.mode == PERSISTENCE_MODE_POSTGRES
        else "memory"
    ),
)
register_document_library_routes(
    app,
    store=DEFAULT_INGESTION_STORE,
    database_env=SERVICE_PERSISTENCE.database_env,
    redacted_database_url=SERVICE_PERSISTENCE.redacted_database_url,
    source_kind=(
        "postgres-read"
        if SERVICE_PERSISTENCE.mode == PERSISTENCE_MODE_POSTGRES
        else "memory"
    ),
)
register_chunking_routes(app, store=DEFAULT_INGESTION_STORE)
register_embedding_index_routes(app, store=DEFAULT_INGESTION_STORE)
register_lexical_index_routes(app, store=DEFAULT_INGESTION_STORE)
register_processing_routes(
    app,
    store=DEFAULT_INGESTION_STORE,
    storage_config=CX_STORAGE_CONFIG,
    prompt_store=DEFAULT_CX_PROMPT_STORE,
    job_queue=SERVICE_PERSISTENCE.job_queue,
    processing_run_repository=CX_PROCESSING_RUN_REPOSITORY,
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
