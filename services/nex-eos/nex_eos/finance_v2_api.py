from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    admit_service_token_from_request,
    problem_response,
)

from .accounting_posting_admission import (
    EosAccountingPostingAdmissionError,
    EosAccountingPostingAdmissionService,
)
from .candidate_review import (
    EosCandidateReviewError,
    SqlAlchemyEosCandidateReviewRepository,
)
from .candidate_validation import (
    EosCandidateValidationError,
    EosCandidateValidationService,
)
from .journal_posting import EosJournalPostingError, EosJournalPostingService
from .journal_verification import EosJournalQueryService
from .journals import EosJournalError
from .voucher_candidate_commands import (
    EosCreateVoucherCandidateService,
    EosVoucherCandidateCommandError,
)
from .voucher_candidate_revision_commands import EosReviseVoucherCandidateService
from .voucher_candidates import (
    EosVoucherCandidateError,
    SqlAlchemyEosVoucherCandidateRepository,
)
from .voucher_commands import EosServiceCaller


def register_finance_v2_routes(app: FastAPI) -> None:
    @app.post(
        "/internal/v2/finance/voucher-candidates/{candidate_id}/posting",
        response_model=None,
        operation_id="FINANCE.VOUCHER.APPROVE_AND_POST",
    )
    def post_voucher_candidate(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service: EosJournalPostingService | None = getattr(
            request.app.state, "eos_journal_posting_service", None
        )
        if service is None:
            return _journal_posting_problem(
                request,
                EosJournalPostingError(
                    "EOS_JOURNAL_POST_UNAVAILABLE",
                    "Atomic Posting dependencies are not configured",
                    status_code=503,
                    retryable=True,
                ),
            )
        try:
            result = service.execute(candidate_id, payload)
        except EosJournalPostingError as exc:
            return _journal_posting_problem(request, exc)
        return JSONResponse(
            result,
            status_code=(
                201 if result["idempotency_disposition"] == "CREATED" else 200
            ),
        )

    @app.get(
        "/internal/v2/finance/journals/{journal_id}",
        response_model=None,
        operation_id="FINANCE.JOURNAL.GET",
    )
    def get_posted_journal(
        journal_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        correlation_id: str = Header(alias="X-Correlation-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _journal_query_service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            return service.get(
                tenant_id=tenant_id,
                company_id=company_id,
                journal_id=journal_id,
                requester_subject_id=requester_subject_id,
                correlation_id=correlation_id,
            )
        except EosJournalError as exc:
            return _journal_problem(request, exc)

    @app.get(
        "/internal/v2/finance/journals/{journal_id}/verification",
        response_model=None,
        operation_id="FINANCE.JOURNAL.VERIFY",
    )
    def verify_posted_journal(
        journal_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        company_id: str = Header(alias="X-NeX-Company-Id"),
        requester_subject_id: str = Header(alias="X-NeX-Subject-Id"),
        correlation_id: str = Header(alias="X-Correlation-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service = _journal_query_service(request)
        if isinstance(service, JSONResponse):
            return service
        try:
            return service.verify(
                tenant_id=tenant_id,
                company_id=company_id,
                journal_id=journal_id,
                requester_subject_id=requester_subject_id,
                correlation_id=correlation_id,
            )
        except EosJournalError as exc:
            return _journal_problem(request, exc)

    @app.post("/internal/v2/finance/voucher-candidates", response_model=None)
    def create_voucher_candidate(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service: EosCreateVoucherCandidateService | None = getattr(
            request.app.state,
            "eos_voucher_candidate_command_service",
            None,
        )
        if service is None:
            return _problem(
                request,
                EosVoucherCandidateCommandError(
                    "EOS_VOUCHER_CANDIDATE_COMMAND_UNAVAILABLE",
                    "VoucherCandidate command dependencies are not configured.",
                    status_code=503,
                    retryable=True,
                ),
            )
        try:
            result = service.execute(
                payload,
                caller=EosServiceCaller(
                    subject=admitted.subject,
                    audience=admitted.audience,
                    scopes=admitted.scopes,
                ),
            )
        except EosVoucherCandidateCommandError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=201 if result["idempotency_disposition"] == "CREATED" else 200,
        )

    @app.post(
        "/internal/v2/finance/voucher-candidates/{candidate_id}/revisions",
        response_model=None,
        operation_id="FINANCE.VOUCHER_CANDIDATE.REVISE",
    )
    def revise_voucher_candidate(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service: EosReviseVoucherCandidateService | None = getattr(
            request.app.state,
            "eos_voucher_candidate_revision_service",
            None,
        )
        if service is None:
            return _problem(
                request,
                EosVoucherCandidateCommandError(
                    "EOS_VOUCHER_CANDIDATE_REVISION_UNAVAILABLE",
                    "VoucherCandidate revision dependencies are not configured.",
                    status_code=503,
                    retryable=True,
                ),
            )
        try:
            result = service.execute(
                candidate_id,
                payload,
                caller=EosServiceCaller(
                    subject=admitted.subject,
                    audience=admitted.audience,
                    scopes=admitted.scopes,
                ),
            )
        except EosVoucherCandidateCommandError as exc:
            return _problem(request, exc)
        return JSONResponse(
            result,
            status_code=201 if result["idempotency_disposition"] == "CREATED" else 200,
        )

    @app.get(
        "/internal/v2/finance/voucher-candidates/{candidate_id}",
        response_model=None,
        operation_id="FINANCE.VOUCHER_CANDIDATE.GET_V2",
    )
    def get_voucher_candidate(
        candidate_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        repository: SqlAlchemyEosVoucherCandidateRepository | None = getattr(
            request.app.state,
            "eos_voucher_candidates",
            None,
        )
        if repository is None:
            return problem_response(
                request,
                status_code=503,
                error_code="EOS_VOUCHER_CANDIDATE_QUERY_UNAVAILABLE",
                title="EOS VoucherCandidate query unavailable",
                detail="VoucherCandidate query persistence is not configured.",
                retryable=True,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-voucher-candidate-query-unavailable"
                ),
            )
        try:
            result = repository.get(tenant_id=tenant_id, candidate_id=candidate_id)
        except EosVoucherCandidateError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="EOS VoucherCandidate query failed",
                detail=exc.detail,
                retryable=exc.retryable,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-voucher-candidate-query-failed"
                ),
            )
        if result is None:
            return problem_response(
                request,
                status_code=404,
                error_code="EOS_VOUCHER_CANDIDATE_NOT_FOUND",
                title="EOS VoucherCandidate not found",
                detail="VoucherCandidate was not found in tenant scope.",
                retryable=False,
                type_uri=(
                    "https://nex-platform.local/problems/"
                    "eos-voucher-candidate-not-found"
                ),
            )
        return result

    @app.post(
        "/internal/v2/finance/voucher-candidates/{candidate_id}/validation",
        response_model=None,
        operation_id="FINANCE.VOUCHER_CANDIDATE.VALIDATE",
    )
    def validate_voucher_candidate(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service: EosCandidateValidationService | None = getattr(
            request.app.state,
            "eos_candidate_validation_service",
            None,
        )
        if service is None:
            return _validation_problem(
                request,
                EosCandidateValidationError(
                    "EOS_CANDIDATE_VALIDATION_UNAVAILABLE",
                    "VoucherCandidate validation dependencies are not configured.",
                    status_code=503,
                    retryable=True,
                ),
            )
        try:
            return service.validate(candidate_id, payload)
        except EosCandidateValidationError as exc:
            return _validation_problem(request, exc)

    @app.post(
        "/internal/v2/finance/voucher-candidates/{candidate_id}/posting-admission",
        response_model=None,
        operation_id="FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION",
    )
    def admit_voucher_candidate_posting(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        service: EosAccountingPostingAdmissionService | None = getattr(
            request.app.state,
            "eos_accounting_posting_admission_service",
            None,
        )
        if service is None:
            return _posting_admission_problem(
                request,
                EosAccountingPostingAdmissionError(
                    "EOS_ACCOUNTING_POSTING_ADMISSION_UNAVAILABLE",
                    "Accounting Posting admission dependencies are not configured.",
                    status_code=503,
                    retryable=True,
                ),
            )
        try:
            return service.admit(candidate_id, payload)
        except EosAccountingPostingAdmissionError as exc:
            return _posting_admission_problem(request, exc)

    @app.get(
        "/internal/v2/finance/voucher-candidates/{candidate_id}/review",
        response_model=None,
        operation_id="FINANCE.VOUCHER_CANDIDATE.REVIEW_GET",
    )
    def get_voucher_candidate_review(
        candidate_id: str,
        request: Request,
        tenant_id: str = Header(alias="X-NeX-Tenant-Id"),
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        repository: SqlAlchemyEosCandidateReviewRepository | None = getattr(
            request.app.state,
            "eos_candidate_review_repository",
            None,
        )
        if repository is None:
            return _review_problem(
                request,
                EosCandidateReviewError(
                    "EOS_CANDIDATE_REVIEW_UNAVAILABLE",
                    "Candidate review persistence is not configured.",
                    status_code=503,
                    retryable=True,
                ),
            )
        try:
            result = repository.get(tenant_id=tenant_id, candidate_id=candidate_id)
        except EosCandidateReviewError as exc:
            return _review_problem(request, exc)
        if result is None:
            return _review_problem(
                request,
                EosCandidateReviewError(
                    "EOS_CANDIDATE_REVIEW_NOT_FOUND",
                    "VoucherCandidate was not found in tenant scope.",
                    status_code=404,
                ),
            )
        return result

    @app.post(
        "/internal/v2/finance/voucher-candidates/{candidate_id}/review-invalidation",
        response_model=None,
        operation_id="FINANCE.VOUCHER_CANDIDATE.INVALIDATE_REVIEW",
    )
    def invalidate_voucher_candidate_review(
        candidate_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = admit_service_token_from_request(
            request,
            authorization,
            expected_audience="nex-eos",
            required_scopes=(DEFAULT_SERVICE_SCOPE,),
            route_class="WRITE",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        repository: SqlAlchemyEosCandidateReviewRepository | None = getattr(
            request.app.state,
            "eos_candidate_review_repository",
            None,
        )
        if repository is None:
            return _review_problem(
                request,
                EosCandidateReviewError(
                    "EOS_CANDIDATE_REVIEW_UNAVAILABLE",
                    "Candidate review persistence is not configured.",
                    status_code=503,
                    retryable=True,
                ),
            )
        if str(payload.get("candidate_id")) != candidate_id:
            return _review_problem(
                request,
                EosCandidateReviewError(
                    "EOS_CANDIDATE_REVIEW_INVALID",
                    "Path candidate_id differs from the invalidation payload.",
                    status_code=422,
                ),
            )
        try:
            return repository.invalidate(payload)
        except EosCandidateReviewError as exc:
            return _review_problem(request, exc)


def _problem(request: Request, exc: EosVoucherCandidateCommandError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS VoucherCandidate command failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/eos-voucher-candidate-command-failed"
        ),
    )


def _validation_problem(request: Request, exc: EosCandidateValidationError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS VoucherCandidate validation failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "eos-voucher-candidate-validation-failed"
        ),
    )


def _review_problem(request: Request, exc: EosCandidateReviewError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS VoucherCandidate review failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/eos-voucher-candidate-review-failed"
        ),
    )


def _posting_admission_problem(
    request: Request,
    exc: EosAccountingPostingAdmissionError,
):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS accounting Posting admission failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "eos-accounting-posting-admission-failed"
        ),
    )


def _journal_query_service(request: Request):
    service: EosJournalQueryService | None = getattr(
        request.app.state,
        "eos_journal_query_service",
        None,
    )
    if service is not None:
        return service
    return _journal_problem(
        request,
        EosJournalError(
            "EOS_JOURNAL_QUERY_UNAVAILABLE",
            "PostedJournal query dependencies are not configured",
            status_code=503,
            retryable=True,
        ),
    )


def _journal_problem(request: Request, exc: EosJournalError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS PostedJournal query failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-journal-query-failed",
    )


def _journal_posting_problem(request: Request, exc: EosJournalPostingError):
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="EOS atomic Journal Posting failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/eos-journal-posting-failed",
    )
