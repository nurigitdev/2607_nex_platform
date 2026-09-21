from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime.prompts import PromptRegistryStore

from nex_cx.chunking import build_and_store_chunk_set
from nex_cx.embedding_index import MoEmbeddingClient, build_and_store_embedding_index
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    run_text_extraction_job,
)
from nex_cx.ingestion_orchestration import (
    INGESTION_PIPELINE_STEPS,
    RUNNING,
    complete_ingestion_step,
    validate_ingestion_run,
)
from nex_cx.ingestion_orchestration_repository import (
    IngestionRunRepository,
    IngestionRunRepositoryError,
)
from nex_cx.lexical_index import build_and_store_lexical_index
from nex_cx.summaries import build_and_store_document_summary
from nex_cx.summary_embeddings import build_and_store_summary_embedding_index


@dataclass(frozen=True)
class IngestionStepResult:
    output_ref: str
    skipped: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.output_ref, str) or not self.output_ref.strip():
            raise ValueError("output_ref must be a non-empty metadata reference")


@dataclass(frozen=True)
class IngestionCheckpointExecutionError(Exception):
    error_code: str
    detail: str
    retryable: bool
    failed_step: str
    status_code: int = 500

    def __str__(self) -> str:
        return self.detail


IngestionStepHandler = Callable[[Mapping[str, Any]], IngestionStepResult]


def execute_ingestion_checkpoint(
    run: Mapping[str, Any],
    *,
    run_repository: IngestionRunRepository,
    worker_id: str,
    step_handlers: Mapping[str, IngestionStepHandler],
    observed_at: str | None = None,
) -> dict[str, Any]:
    current = validate_ingestion_run(run)
    if current["status"] != RUNNING or current["current_step"] is None:
        raise IngestionCheckpointExecutionError(
            error_code="cx.ingestion_checkpoint.run_not_active",
            detail="Only an active ingestion run can execute a checkpoint.",
            retryable=False,
            failed_step=str(current.get("current_step") or "unknown"),
            status_code=409,
        )
    step_id = str(current["current_step"])
    handler = step_handlers.get(step_id)
    if handler is None:
        raise IngestionCheckpointExecutionError(
            error_code="cx.ingestion_checkpoint.handler_missing",
            detail=f"No ingestion step handler is registered for {step_id}.",
            retryable=False,
            failed_step=step_id,
            status_code=500,
        )
    try:
        result = handler(current)
        if not isinstance(result, IngestionStepResult):
            raise TypeError("Ingestion step handler returned an invalid result.")
        checkpoint = complete_ingestion_step(
            current,
            worker_id=worker_id,
            output_ref=result.output_ref,
            skipped=result.skipped,
            observed_at=observed_at,
            expected_checkpoint_version=current["checkpoint_version"],
        )
        return run_repository.save(
            checkpoint,
            expected_checkpoint_version=current["checkpoint_version"],
        )
    except IngestionCheckpointExecutionError:
        raise
    except IngestionRunRepositoryError as exc:
        raise IngestionCheckpointExecutionError(
            error_code=exc.error_code,
            detail=exc.detail,
            retryable=exc.status_code >= 500,
            failed_step=step_id,
            status_code=exc.status_code,
        ) from exc
    except Exception as exc:
        raise IngestionCheckpointExecutionError(
            error_code=str(
                getattr(exc, "error_code", "cx.ingestion_checkpoint.step_failed")
            ),
            detail=str(
                getattr(exc, "detail", "CX ingestion checkpoint execution failed.")
            ),
            retryable=bool(getattr(exc, "retryable", False)),
            failed_step=step_id,
            status_code=int(getattr(exc, "status_code", 500)),
        ) from exc


def build_default_ingestion_step_handlers(
    *,
    store: ContentIngestionStore,
    storage_config: CxStorageConfig,
    mo_client: MoEmbeddingClient,
    embedding_alias: str,
    prompt_store: PromptRegistryStore | None = None,
) -> dict[str, IngestionStepHandler]:
    return {
        "extraction": lambda run: _existing_or_execute(
            step_id="extraction",
            document_id=str(run["document_id"]),
            existing=store.get_extraction_result(str(run["document_id"])),
            execute=lambda: run_text_extraction_job(
                str(run["job_id"]),
                store=store,
                storage_config=storage_config,
                request_id=str(run["request_id"]),
                trace_id=str(run["trace_id"]),
            ),
        ),
        "chunking": lambda run: _existing_or_execute(
            step_id="chunking",
            document_id=str(run["document_id"]),
            existing=store.get_chunk_set(str(run["document_id"])),
            execute=lambda: build_and_store_chunk_set(
                str(run["document_id"]),
                store=store,
                storage_config=storage_config,
                request_id=str(run["request_id"]),
                trace_id=str(run["trace_id"]),
            ),
        ),
        "lexical_index": lambda run: _existing_or_execute(
            step_id="lexical_index",
            document_id=str(run["document_id"]),
            existing=store.get_lexical_index(str(run["document_id"])),
            execute=lambda: build_and_store_lexical_index(
                str(run["document_id"]),
                store=store,
                storage_config=storage_config,
                request_id=str(run["request_id"]),
                trace_id=str(run["trace_id"]),
            ),
        ),
        "embedding_index": lambda run: _existing_or_execute(
            step_id="embedding_index",
            document_id=str(run["document_id"]),
            existing=store.get_embedding_index(str(run["document_id"])),
            execute=lambda: build_and_store_embedding_index(
                str(run["document_id"]),
                store=store,
                mo_client=mo_client,
                embedding_alias=embedding_alias,
                request_id=str(run["request_id"]),
                trace_id=str(run["trace_id"]),
            ),
        ),
        "summary": lambda run: _existing_or_execute(
            step_id="summary",
            document_id=str(run["document_id"]),
            existing=store.get_document_summary(str(run["document_id"])),
            execute=lambda: build_and_store_document_summary(
                str(run["document_id"]),
                store=store,
                prompt_store=prompt_store,
                request_id=str(run["request_id"]),
                trace_id=str(run["trace_id"]),
            ),
        ),
        "summary_embedding": lambda run: _existing_or_execute(
            step_id="summary_embedding",
            document_id=str(run["document_id"]),
            existing=store.get_summary_embedding_index(str(run["document_id"])),
            execute=lambda: build_and_store_summary_embedding_index(
                str(run["document_id"]),
                store=store,
                mo_client=mo_client,
                embedding_alias=embedding_alias,
                request_id=str(run["request_id"]),
                trace_id=str(run["trace_id"]),
            ),
        ),
    }


def execute_all_ingestion_checkpoints(
    run: Mapping[str, Any],
    *,
    run_repository: IngestionRunRepository,
    worker_id: str,
    step_handlers: Mapping[str, IngestionStepHandler],
    observed_at: str | None = None,
) -> dict[str, Any]:
    current = validate_ingestion_run(run)
    for _ in INGESTION_PIPELINE_STEPS:
        if current["status"] != RUNNING:
            break
        current = execute_ingestion_checkpoint(
            current,
            run_repository=run_repository,
            worker_id=worker_id,
            step_handlers=step_handlers,
            observed_at=observed_at,
        )
    return current


def _existing_or_execute(
    *,
    step_id: str,
    document_id: str,
    existing: Mapping[str, Any] | None,
    execute: Callable[[], Mapping[str, Any]],
) -> IngestionStepResult:
    output = existing if existing is not None else execute()
    return IngestionStepResult(
        output_ref=_metadata_output_ref(step_id, document_id, output),
        skipped=existing is not None,
    )


def _metadata_output_ref(
    step_id: str,
    document_id: str,
    output: Mapping[str, Any],
) -> str:
    if step_id == "summary":
        object_id = output.get("document_summary_id")
        ref_type = "cx.document_summary"
    elif step_id == "summary_embedding":
        object_id = output.get("document_summary_id")
        ref_type = "cx.document_summary_embedding"
    else:
        object_id = output.get("document_id", document_id)
        ref_type = f"cx.{step_id}"
    if not isinstance(object_id, str) or not object_id:
        raise ValueError(f"{step_id} output does not contain a metadata identity")
    return f"{ref_type}:{object_id}"
