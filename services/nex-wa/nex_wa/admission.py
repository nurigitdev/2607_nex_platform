from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from nex_runtime import build_unit_of_work
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .work_assets import (
    SqlAlchemyWorkAssetRepository,
    WorkAssetError,
    WorkAssetInput,
    WorkAssetRecord,
)
from .work_evidence import (
    SqlAlchemyWorkEvidenceRepository,
    WorkEvidenceInput,
    WorkEvidenceRecord,
    deterministic_work_evidence_id,
)


class WorkAdmissionError(Exception):
    def __init__(self, error_code: str, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class NormalizedEvidenceAdmission:
    evidence: WorkEvidenceRecord
    asset: WorkAssetRecord


class WaEvidenceAdmissionService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        evidence_repository: SqlAlchemyWorkEvidenceRepository | None = None,
        asset_repository: SqlAlchemyWorkAssetRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        concurrency_retries: int = 2,
    ) -> None:
        if concurrency_retries < 1:
            raise ValueError("concurrency_retries must be positive")
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._evidence_repository = evidence_repository or (
            SqlAlchemyWorkEvidenceRepository(session_factory, clock=self._clock)
        )
        self._asset_repository = asset_repository or SqlAlchemyWorkAssetRepository(
            session_factory,
            clock=self._clock,
        )
        self._concurrency_retries = concurrency_retries

    def admit_normalized_evidence(
        self,
        evidence: WorkEvidenceInput,
        asset: WorkAssetInput,
    ) -> NormalizedEvidenceAdmission:
        _require_same_admission_lineage(evidence, asset)
        attempts_remaining = self._concurrency_retries
        while True:
            try:
                return self._admit_once(evidence, asset)
            except IntegrityError as exc:
                attempts_remaining -= 1
                if attempts_remaining == 0:
                    raise WorkAdmissionError(
                        "WA_ADMISSION_INTEGRITY_CONFLICT",
                        "normalized evidence admission conflicted concurrently",
                        409,
                    ) from exc
            except WorkAssetError as exc:
                if exc.error_code != "WA_ASSET_CONCURRENT_UPDATE":
                    raise
                attempts_remaining -= 1
                if attempts_remaining == 0:
                    raise

    def admit_normalized_evidence_set(
        self,
        evidence: tuple[WorkEvidenceInput, ...],
        asset: WorkAssetInput,
    ) -> NormalizedEvidenceAdmission:
        if not evidence:
            raise WorkAdmissionError(
                "WA_ADMISSION_LINEAGE_INVALID",
                "evidence set must not be empty",
                409,
            )
        for item in evidence:
            _require_same_admission_lineage(item, asset)
        attempts_remaining = self._concurrency_retries
        while True:
            try:
                return self._admit_set_once(evidence, asset)
            except IntegrityError as exc:
                attempts_remaining -= 1
                if attempts_remaining == 0:
                    raise WorkAdmissionError(
                        "WA_ADMISSION_INTEGRITY_CONFLICT",
                        "normalized evidence-set admission conflicted concurrently",
                        409,
                    ) from exc
            except WorkAssetError as exc:
                if exc.error_code != "WA_ASSET_CONCURRENT_UPDATE":
                    raise
                attempts_remaining -= 1
                if attempts_remaining == 0:
                    raise

    def _admit_once(
        self,
        evidence: WorkEvidenceInput,
        asset: WorkAssetInput,
    ) -> NormalizedEvidenceAdmission:
        now = self._clock()
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                evidence_record = self._evidence_repository.create_or_get_in_session(
                    transaction.db,
                    evidence,
                    created_at=now,
                )
                asset_record = self._asset_repository.create_or_update_in_session(
                    transaction.db,
                    asset,
                    updated_at=now,
                )
                return NormalizedEvidenceAdmission(evidence_record, asset_record)
        except IntegrityError:
            raise
        except SQLAlchemyError as exc:
            raise WorkAdmissionError(
                "WA_ADMISSION_STORE_UNAVAILABLE",
                "normalized evidence admission persistence is unavailable",
                503,
            ) from exc

    def _admit_set_once(
        self,
        evidence: tuple[WorkEvidenceInput, ...],
        asset: WorkAssetInput,
    ) -> NormalizedEvidenceAdmission:
        now = self._clock()
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                records = tuple(
                    self._evidence_repository.create_or_get_in_session(
                        transaction.db,
                        item,
                        created_at=now,
                    )
                    for item in evidence
                )
                asset_record = self._asset_repository.create_or_update_in_session(
                    transaction.db,
                    asset,
                    updated_at=now,
                )
                return NormalizedEvidenceAdmission(records[0], asset_record)
        except IntegrityError:
            raise
        except SQLAlchemyError as exc:
            raise WorkAdmissionError(
                "WA_ADMISSION_STORE_UNAVAILABLE",
                "normalized evidence-set persistence is unavailable",
                503,
            ) from exc


def _require_same_admission_lineage(
    evidence: WorkEvidenceInput,
    asset: WorkAssetInput,
) -> None:
    if evidence.tenant_id != asset.tenant_id:
        raise WorkAdmissionError(
            "WA_ADMISSION_LINEAGE_INVALID",
            "evidence and asset tenant must match",
            409,
        )
    evidence_id = deterministic_work_evidence_id(
        tenant_id=evidence.tenant_id,
        source_type=evidence.source_type,
        source_ref=evidence.source_ref,
        source_revision_ref=evidence.source_revision_ref,
    )
    if evidence_id not in {binding.work_evidence_id for binding in asset.bindings}:
        raise WorkAdmissionError(
            "WA_ADMISSION_LINEAGE_INVALID",
            "admitted evidence must be bound to the WorkAsset",
            409,
        )
