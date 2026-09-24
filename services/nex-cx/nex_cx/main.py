import os

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
from nex_cx.async_generation_contracts import CX_ASYNC_GENERATION_JOB_TYPE
from nex_cx.async_generation_operations import (
    register_async_generation_operations_routes,
)
from nex_cx.async_generation_recovery import (
    recover_persisted_async_generation_job,
)
from nex_cx.document_intelligence_orchestration import (
    register_document_intelligence_routes,
)
from nex_cx.document_library import register_document_library_routes
from nex_cx.embedding_index import (
    DEFAULT_EMBEDDING_ALIAS,
    build_default_mo_embedding_client,
    register_embedding_index_routes,
)
from nex_cx.generation import (
    DEFAULT_GENERATION_STORE,
    build_default_mo_client,
    register_generation_routes,
)
from nex_cx.generation_private_output import build_generation_output_store
from nex_cx.generation_request_store import build_generation_request_store
from nex_cx.generation_read_model import GenerationReadModel
from nex_cx.generation_repository import SqlAlchemyGenerationRuntimeRepository
from nex_cx.generation_runtime import (
    GroundedGenerationRuntime,
    SqlAlchemyGenerationAdmissionRepository,
)
from nex_cx.ingestion import (
    DEFAULT_INGESTION_STORE,
    CxStorageConfig,
    build_storage_config,
    register_ingestion_routes,
)
from nex_cx.ingestion_orchestration_repository import (
    InMemoryIngestionRunRepository,
    IngestionRunRepository,
    SqlAlchemyIngestionRunRepository,
)
from nex_cx.ingestion_operations import register_ingestion_operations_routes
from nex_cx.ingestion_worker import (
    CX_INGESTION_JOB_TYPE,
    recover_expired_ingestion_job,
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
from nex_cx.private_text_store import (
    FileSystemCxPrivateTextStore,
    build_private_text_store,
)
from nex_cx.pgvector_store import (
    PgVectorCxVectorStore,
    build_pgvector_cx_vector_store,
)
from nex_cx.summary_pgvector_store import (
    SummaryPgVectorStore,
    build_summary_pgvector_store,
)
from nex_cx.summary_similarity import (
    PostgresSummarySimilarityStore,
    build_summary_similarity_store,
)
from nex_cx.vector_index_operations import register_vector_index_operations_routes
from nex_cx.vector_index_repository import (
    SqlAlchemyVectorIndexRepository,
    VectorIndexRepository,
)
from nex_cx.worker_leases import SqlAlchemyCxWorkerLeaseStore
from nex_cx.worker_operations import register_worker_operations_routes


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


def build_cx_ingestion_run_repository(
    runtime: ServicePersistenceRuntime,
) -> IngestionRunRepository:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return SqlAlchemyIngestionRunRepository(
            runtime.api_session_factory,
            database_env=runtime.database_env,
            redacted_database_url=runtime.redacted_database_url,
        )
    return InMemoryIngestionRunRepository()


def build_cx_vector_operations_dependencies(
    runtime: ServicePersistenceRuntime,
) -> tuple[VectorIndexRepository | None, PgVectorCxVectorStore | None]:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return (
            SqlAlchemyVectorIndexRepository(runtime.api_session_factory),
            build_pgvector_cx_vector_store(
                database_env=runtime.database_env,
                workload="api",
            ),
        )
    return None, None


def build_cx_document_intelligence_dependencies(
    runtime: ServicePersistenceRuntime,
) -> tuple[
    FileSystemCxPrivateTextStore | None,
    SummaryPgVectorStore | None,
    PostgresSummarySimilarityStore | None,
]:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return (
            build_private_text_store(),
            build_summary_pgvector_store(
                database_env=runtime.database_env,
                workload="worker",
            ),
            build_summary_similarity_store(
                database_env=runtime.database_env,
                workload="api",
            ),
        )
    return None, None, None


def build_cx_generation_runtime(
    runtime: ServicePersistenceRuntime,
) -> GroundedGenerationRuntime | None:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.api_session_factory is not None
    ):
        return GroundedGenerationRuntime(
            admission_repository=SqlAlchemyGenerationAdmissionRepository(
                runtime.api_session_factory
            ),
            execution_repository=SqlAlchemyGenerationRuntimeRepository(
                runtime.api_session_factory,
                database_env=runtime.database_env,
                redacted_database_url=runtime.redacted_database_url,
            ),
            private_output_store=build_generation_output_store(),
        )
    return None


def build_cx_generation_read_model(
    generation_runtime: GroundedGenerationRuntime | None,
) -> GenerationReadModel | None:
    if generation_runtime is None:
        return None
    return GenerationReadModel(
        repository=generation_runtime.execution_repository,
        private_output_store=generation_runtime.private_output_store,
    )


def build_cx_worker_lease_store(
    runtime: ServicePersistenceRuntime,
) -> SqlAlchemyCxWorkerLeaseStore | None:
    if (
        runtime.mode == PERSISTENCE_MODE_POSTGRES
        and runtime.worker_session_factory is not None
    ):
        return SqlAlchemyCxWorkerLeaseStore(runtime.worker_session_factory)
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
CX_INGESTION_RUN_REPOSITORY = build_cx_ingestion_run_repository(
    SERVICE_PERSISTENCE,
)
CX_VECTOR_INDEX_REPOSITORY, CX_VECTOR_STORE = (
    build_cx_vector_operations_dependencies(SERVICE_PERSISTENCE)
)
CX_GENERATION_RUNTIME = build_cx_generation_runtime(SERVICE_PERSISTENCE)
CX_GENERATION_READ_MODEL = build_cx_generation_read_model(CX_GENERATION_RUNTIME)
CX_GENERATION_REQUEST_STORE = build_generation_request_store()
CX_WORKER_LEASE_STORE = build_cx_worker_lease_store(SERVICE_PERSISTENCE)
(
    CX_PRIVATE_SUMMARY_TEXT_STORE,
    CX_SUMMARY_VECTOR_STORE,
    CX_SUMMARY_SIMILARITY_STORE,
) = build_cx_document_intelligence_dependencies(SERVICE_PERSISTENCE)
if CX_PRIVATE_SUMMARY_TEXT_STORE is not None:
    DEFAULT_INGESTION_STORE.private_summary_text_store = CX_PRIVATE_SUMMARY_TEXT_STORE
CX_MO_GENERATION_CLIENT = build_default_mo_client()
CX_MO_EMBEDDING_CLIENT = build_default_mo_embedding_client()
CX_EMBEDDING_ALIAS = os.getenv("NEX_CX_EMBEDDING_ALIAS", DEFAULT_EMBEDDING_ALIAS)
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
    execution_runtime=CX_GENERATION_RUNTIME,
    read_model=CX_GENERATION_READ_MODEL,
)
register_async_generation_operations_routes(
    app,
    job_queue=SERVICE_PERSISTENCE.job_queue,
    runtime=CX_GENERATION_RUNTIME,
    request_store=CX_GENERATION_REQUEST_STORE,
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
    job_queue=SERVICE_PERSISTENCE.job_queue,
    ingestion_run_repository=CX_INGESTION_RUN_REPOSITORY,
)
register_ingestion_operations_routes(
    app,
    job_queue=SERVICE_PERSISTENCE.job_queue,
    run_repository=CX_INGESTION_RUN_REPOSITORY,
)
register_worker_operations_routes(
    app,
    job_queue=SERVICE_PERSISTENCE.job_queue,
    heartbeat_store=SERVICE_PERSISTENCE.worker_heartbeat_store,
    lease_store=CX_WORKER_LEASE_STORE,
    recovery_handlers={
        CX_INGESTION_JOB_TYPE: lambda job, observed_at: (
            recover_expired_ingestion_job(
                str(job["job_id"]),
                job_queue=SERVICE_PERSISTENCE.job_queue,
                run_repository=CX_INGESTION_RUN_REPOSITORY,
                observed_at=observed_at,
            )
        ),
        **(
            {
                CX_ASYNC_GENERATION_JOB_TYPE: lambda job, observed_at: (
                    recover_persisted_async_generation_job(
                        job,
                        observed_at,
                        job_queue=SERVICE_PERSISTENCE.job_queue,
                        request_store=CX_GENERATION_REQUEST_STORE,
                        runtime=CX_GENERATION_RUNTIME,
                    )
                )
            }
            if CX_GENERATION_RUNTIME is not None
            else {}
        ),
    },
)
register_vector_index_operations_routes(
    app,
    repository=CX_VECTOR_INDEX_REPOSITORY,
    vector_store=CX_VECTOR_STORE,
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
    generation_client=CX_MO_GENERATION_CLIENT,
)
register_document_intelligence_routes(
    app,
    store=DEFAULT_INGESTION_STORE,
    generation_client=CX_MO_GENERATION_CLIENT,
    embedding_client=CX_MO_EMBEDDING_CLIENT,
    embedding_alias=CX_EMBEDDING_ALIAS,
    summary_vector_store=CX_SUMMARY_VECTOR_STORE,
    summary_similarity_store=CX_SUMMARY_SIMILARITY_STORE,
)
register_summary_embedding_routes(
    app,
    store=DEFAULT_INGESTION_STORE,
    mo_client=CX_MO_EMBEDDING_CLIENT,
    embedding_alias=CX_EMBEDDING_ALIAS,
)
register_prompt_registry_routes(
    app,
    store=DEFAULT_CX_PROMPT_STORE,
    expected_audience="nex-cx",
)
