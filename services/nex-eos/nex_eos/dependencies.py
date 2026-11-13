from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime import build_service_token_admission_runtime
from nex_runtime.service_token_admission import ServiceTokenAdmissionRuntime

from .account_catalog import (
    EosAccountCatalogService,
    SqlAlchemyEosAccountCatalogRepository,
)
from .accounting_approval import (
    EosAccountingApprovalService,
    SqlAlchemyAccountingReviewContextRepository,
)
from .accounting_periods import (
    EosAccountingPeriodService,
    SqlAlchemyEosAccountingPeriodRepository,
)
from .accounting_posting_admission import EosAccountingPostingAdmissionService
from .accounts import SqlAlchemyEosAccountRepository
from .approval_instances import SqlAlchemyEosApprovalInstanceRepository
from .approval_policies import SqlAlchemyEosApprovalPolicyRepository
from .approval_transitions import (
    EosBusinessApprovalTransitionService,
    SqlAlchemyEosApprovalTransitionRepository,
)
from .approved_document_consumption import EosApprovedDocumentConsumptionAdapter
from .approved_documents import (
    EosApprovedDocumentService,
    SqlAlchemyEosApprovedDocumentRepository,
)
from .approver_resolution import EosApproverResolutionService
from .attachment_resolution import HttpAeVoucherAttachmentResolver
from .attachments import SqlAlchemyEosAttachmentRepository
from .authorization import EosVoucherAuthorizationClient, HttpOaAuthorizationSource
from .business_formal_wc import (
    DEFAULT_WC_BASE_URL,
    EosBusinessFormalWcAdapter,
    HttpWcApprovalWorkItemClient,
)
from .business_queries import SqlAlchemyEosBusinessOperationQuery
from .business_transactions import (
    EosBusinessTransactionCoordinator,
    SqlAlchemyEosBusinessTransactionCoordinator,
)
from .candidate_review import SqlAlchemyEosCandidateReviewRepository
from .candidate_validation import EosCandidateValidationService
from .coa_operations import (
    EosCoaOperationsService,
    PinnedCoaPublicationAdmission,
    SqlAlchemyEosCoaOperationsRepository,
)
from .coa_release_admin import (
    EosCoaReleaseAdminService,
    SqlAlchemyEosCoaReleaseAdminRepository,
)
from .config import EosSettings
from .document_signoff import (
    EosDocumentSignoffService,
    EosScopedApprovalDecisionRouter,
    SqlAlchemyDocumentSignoffContextRepository,
)
from .fx_rates import EosFxRateService, SqlAlchemyEosFxRateRepository
from .health import build_configuration_readiness_check
from .journal_posting import EosJournalPostingService
from .journal_verification import EosJournalQueryService
from .journals import SqlAlchemyEosJournalRepository
from .legal_entities import (
    EosLegalEntityService,
    SqlAlchemyEosLegalEntityRepository,
)
from .organization import SqlAlchemyEosOrganizationRepository
from .persistence import EosDatabaseRuntime, build_eos_database_runtime
from .project_application_approvals import EosProjectApplicationApprovalService
from .project_applications import (
    EosProjectApplicationService,
    SqlAlchemyEosProjectApplicationRepository,
)
from .project_authorization import (
    EosProjectAuthorizationGate,
    HttpOaProjectAuthorizationDecisionSource,
    SqlAlchemyEosProjectAuthorizationContextSource,
)
from .project_entitlement_reconciliation import (
    EosProjectEntitlementReconciliationService,
    HttpOaProjectEntitlementProjectionSource,
)
from .project_memberships import SqlAlchemyEosProjectMembershipRepository
from .project_operations import EosGovernedProjectService
from .project_work_assignments import EosProjectWorkAssignmentService
from .project_work_codes import EosProjectBusinessService
from .projects import SqlAlchemyEosProjectRepository
from .reporting_maps import (
    EosReportingMapService,
    SqlAlchemyEosReportingMapRepository,
)
from .scoped_approvals import (
    EosScopedApprovalService,
    SqlAlchemyEosScopedApprovalRepository,
)
from .voucher_access import EosVoucherAccessService
from .voucher_candidate_commands import EosCreateVoucherCandidateService
from .voucher_candidate_revision_commands import EosReviseVoucherCandidateService
from .voucher_candidates import (
    EOS_VOUCHER_CANDIDATE_CREATE_SCOPE,
    SqlAlchemyEosVoucherCandidateRepository,
)
from .voucher_commands import EosCreateVoucherDraftService
from .voucher_verification import SqlAlchemyEosVoucherVerificationQuery
from .vouchers import SqlAlchemyEosVoucherRepository


@dataclass(frozen=True)
class EosDependencies:
    service_token_admission: ServiceTokenAdmissionRuntime
    readiness_checks: tuple[Callable[[], Mapping[str, Any]], ...]
    database_runtime: EosDatabaseRuntime | None
    business_transactions: EosBusinessTransactionCoordinator | None
    organization: SqlAlchemyEosOrganizationRepository | None
    approver_resolution_service: EosApproverResolutionService | None
    projects: SqlAlchemyEosProjectRepository | None
    project_application_service: EosProjectApplicationService | None
    project_application_approval_service: EosProjectApplicationApprovalService | None
    project_memberships: SqlAlchemyEosProjectMembershipRepository | None
    project_operations: EosGovernedProjectService | None
    project_entitlement_reconciliation: (
        EosProjectEntitlementReconciliationService | None
    )
    project_business_service: EosProjectBusinessService | None
    project_work_assignment_service: EosProjectWorkAssignmentService | None
    legal_entities: SqlAlchemyEosLegalEntityRepository | None
    legal_entity_service: EosLegalEntityService | None
    accounts: SqlAlchemyEosAccountRepository | None
    account_catalog: SqlAlchemyEosAccountCatalogRepository | None
    account_catalog_service: EosAccountCatalogService | None
    coa_operations_service: EosCoaOperationsService | None
    reporting_map_service: EosReportingMapService | None
    coa_release_admin_service: EosCoaReleaseAdminService | None
    accounting_period_service: EosAccountingPeriodService | None
    accounting_approval_service: EosAccountingApprovalService | None
    accounting_posting_admission_service: EosAccountingPostingAdmissionService | None
    journals: SqlAlchemyEosJournalRepository | None
    journal_query_service: EosJournalQueryService | None
    journal_posting_service: EosJournalPostingService | None
    document_signoff_service: EosDocumentSignoffService | None
    scoped_approval_decision_router: EosScopedApprovalDecisionRouter | None
    fx_rate_service: EosFxRateService | None
    approval_policies: SqlAlchemyEosApprovalPolicyRepository | None
    approval_instances: SqlAlchemyEosApprovalInstanceRepository | None
    approval_transition_service: EosBusinessApprovalTransitionService | None
    approved_document_service: EosApprovedDocumentService | None
    scoped_approval_service: EosScopedApprovalService | None
    business_formal_wc_adapter: EosBusinessFormalWcAdapter | None
    vouchers: SqlAlchemyEosVoucherRepository | None
    attachments: SqlAlchemyEosAttachmentRepository | None
    voucher_command_service: EosCreateVoucherDraftService | None
    voucher_access_service: EosVoucherAccessService | None
    business_operation_query: SqlAlchemyEosBusinessOperationQuery | None
    voucher_verification_query: SqlAlchemyEosVoucherVerificationQuery | None
    voucher_candidates: SqlAlchemyEosVoucherCandidateRepository | None
    voucher_candidate_command_service: EosCreateVoucherCandidateService | None
    voucher_candidate_revision_service: EosReviseVoucherCandidateService | None
    candidate_validation_service: EosCandidateValidationService | None
    candidate_review_repository: SqlAlchemyEosCandidateReviewRepository | None


def build_eos_dependencies(
    settings: EosSettings,
    *,
    environ: Mapping[str, str],
) -> EosDependencies:
    database_runtime = (
        build_eos_database_runtime(environ=environ)
        if environ.get(settings.database_env)
        else None
    )
    business_transactions = (
        SqlAlchemyEosBusinessTransactionCoordinator(
            database_runtime.session_factory,
        )
        if database_runtime is not None
        else None
    )
    organization = (
        SqlAlchemyEosOrganizationRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    approver_resolution_service = (
        EosApproverResolutionService(organization) if organization is not None else None
    )
    projects = (
        SqlAlchemyEosProjectRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    project_memberships = (
        SqlAlchemyEosProjectMembershipRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    accounts = (
        SqlAlchemyEosAccountRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    account_catalog = (
        SqlAlchemyEosAccountCatalogRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    legal_entities = (
        SqlAlchemyEosLegalEntityRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    voucher_candidates = (
        SqlAlchemyEosVoucherCandidateRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    candidate_validation_service = (
        EosCandidateValidationService(
            candidates=voucher_candidates,
            legal_entities=legal_entities,
            periods=SqlAlchemyEosAccountingPeriodRepository(
                database_runtime.session_factory
            ),
            account_catalog=account_catalog,
            fx_rates=SqlAlchemyEosFxRateRepository(database_runtime.session_factory),
        )
        if database_runtime is not None
        and voucher_candidates is not None
        and legal_entities is not None
        and account_catalog is not None
        else None
    )
    candidate_review_repository = (
        SqlAlchemyEosCandidateReviewRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    approval_policies = (
        SqlAlchemyEosApprovalPolicyRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    approval_instances = (
        SqlAlchemyEosApprovalInstanceRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    approval_transitions = (
        SqlAlchemyEosApprovalTransitionRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    approval_transition_service = (
        EosBusinessApprovalTransitionService(
            approval_instances=approval_instances,
            transitions=approval_transitions,
        )
        if approval_instances is not None and approval_transitions is not None
        else None
    )
    wc_token = environ.get("NEX_EOS_TO_WC_SERVICE_TOKEN", "")
    business_formal_wc_adapter = (
        EosBusinessFormalWcAdapter(
            approval_instances=approval_instances,
            approver_resolution=approver_resolution_service,
            wc_client=HttpWcApprovalWorkItemClient(
                base_url=environ.get("NEX_WC_BASE_URL", DEFAULT_WC_BASE_URL),
                service_token=wc_token,
            ),
        )
        if (
            approval_instances is not None
            and approver_resolution_service is not None
            and wc_token
        )
        else None
    )
    vouchers = (
        SqlAlchemyEosVoucherRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    ae_token = environ.get("NEX_EOS_TO_AE_SERVICE_TOKEN", "")
    attachments = (
        SqlAlchemyEosAttachmentRepository(
            database_runtime.session_factory,
            HttpAeVoucherAttachmentResolver(
                base_url=environ.get("NEX_AE_API_BASE_URL", "http://127.0.0.1:8103"),
                service_token=ae_token,
                timeout_seconds=float(
                    environ.get("NEX_EOS_AE_ATTACHMENT_TIMEOUT_SECONDS", "15")
                ),
            ),
        )
        if database_runtime is not None and ae_token
        else None
    )
    oa_token = environ.get("NEX_EOS_TO_OA_SERVICE_TOKEN", "")
    authorization_source = (
        HttpOaAuthorizationSource(
            base_url=environ.get("NEX_OA_BASE_URL", "http://127.0.0.1:8101"),
            service_token=oa_token,
        )
        if oa_token
        else None
    )
    project_authorizer = (
        EosProjectAuthorizationGate(
            context_source=SqlAlchemyEosProjectAuthorizationContextSource(
                database_runtime.session_factory
            ),
            decision_source=HttpOaProjectAuthorizationDecisionSource(
                base_url=environ.get("NEX_OA_BASE_URL", "http://127.0.0.1:8101"),
                service_token=oa_token,
                timeout_seconds=float(
                    environ.get("NEX_EOS_OA_PROJECT_TIMEOUT_SECONDS", "10")
                ),
            ),
        )
        if database_runtime is not None and oa_token
        else None
    )
    project_application_service = (
        EosProjectApplicationService(
            SqlAlchemyEosProjectApplicationRepository(database_runtime.session_factory),
            authorization_source,
            projects,
        )
        if database_runtime is not None
        and authorization_source is not None
        and projects is not None
        else None
    )
    project_application_approval_service = (
        EosProjectApplicationApprovalService(
            session_factory=database_runtime.session_factory,
            authorization_source=authorization_source,
            wc_client=HttpWcApprovalWorkItemClient(
                base_url=environ.get("NEX_WC_BASE_URL", DEFAULT_WC_BASE_URL),
                service_token=wc_token,
            ),
            project_agent_profile_policy_ref=environ[
                "NEX_EOS_PROJECT_AGENT_PROFILE_POLICY_REF"
            ],
        )
        if database_runtime is not None
        and authorization_source is not None
        and wc_token
        and environ.get("NEX_EOS_PROJECT_AGENT_PROFILE_POLICY_REF", "").strip()
        else None
    )
    approved_document_service = (
        EosApprovedDocumentService(
            SqlAlchemyEosApprovedDocumentRepository(database_runtime.session_factory),
            authorization_source,
        )
        if database_runtime is not None and authorization_source is not None
        else None
    )
    scoped_approval_service = (
        EosScopedApprovalService(
            repository=SqlAlchemyEosScopedApprovalRepository(
                database_runtime.session_factory
            ),
            coordinator=business_transactions,
            authorization_source=authorization_source,
            project_authorizer=project_authorizer,
            wc_client=HttpWcApprovalWorkItemClient(
                base_url=environ.get("NEX_WC_BASE_URL", DEFAULT_WC_BASE_URL),
                service_token=wc_token,
            ),
            accounting_review_repository=(
                SqlAlchemyAccountingReviewContextRepository(
                    database_runtime.session_factory
                )
            ),
            candidate_review_repository=candidate_review_repository,
            candidate_validation_service=candidate_validation_service,
            document_signoff_repository=(
                SqlAlchemyDocumentSignoffContextRepository(
                    database_runtime.session_factory
                )
            ),
        )
        if database_runtime is not None
        and business_transactions is not None
        and authorization_source is not None
        and wc_token
        else None
    )
    accounting_approval_service = (
        EosAccountingApprovalService(
            session_factory=database_runtime.session_factory,
            authorization_source=authorization_source,
            wc_client=HttpWcApprovalWorkItemClient(
                base_url=environ.get("NEX_WC_BASE_URL", DEFAULT_WC_BASE_URL),
                service_token=wc_token,
            ),
            candidate_review_repository=candidate_review_repository,
        )
        if database_runtime is not None
        and authorization_source is not None
        and wc_token
        else None
    )
    accounting_posting_admission_service = (
        EosAccountingPostingAdmissionService(
            session_factory=database_runtime.session_factory,
            authorization_source=authorization_source,
            project_authorizer=project_authorizer,
            admission_ttl_seconds=int(
                environ.get("NEX_EOS_ACCOUNTING_POSTING_ADMISSION_TTL_SECONDS", "30")
            ),
        )
        if database_runtime is not None
        and authorization_source is not None
        and project_authorizer is not None
        else None
    )
    journals = (
        SqlAlchemyEosJournalRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    journal_query_service = (
        EosJournalQueryService(
            repository=journals,
            authorization_source=authorization_source,
            project_authorizer=project_authorizer,
        )
        if journals is not None
        and authorization_source is not None
        and project_authorizer is not None
        else None
    )
    journal_posting_service = (
        EosJournalPostingService(
            session_factory=database_runtime.session_factory,
            coordinator=business_transactions,
            validation_service=candidate_validation_service,
            admission_service=accounting_posting_admission_service,
            journals=journals,
            consumption=EosApprovedDocumentConsumptionAdapter(),
        )
        if database_runtime is not None
        and business_transactions is not None
        and candidate_validation_service is not None
        and accounting_posting_admission_service is not None
        and journals is not None
        else None
    )
    document_signoff_service = (
        EosDocumentSignoffService(
            session_factory=database_runtime.session_factory,
            authorization_source=authorization_source,
            wc_client=HttpWcApprovalWorkItemClient(
                base_url=environ.get("NEX_WC_BASE_URL", DEFAULT_WC_BASE_URL),
                service_token=wc_token,
            ),
            document_repository=SqlAlchemyEosApprovedDocumentRepository(
                database_runtime.session_factory
            ),
        )
        if database_runtime is not None
        and authorization_source is not None
        and wc_token
        else None
    )
    scoped_approval_decision_router = (
        EosScopedApprovalDecisionRouter(
            session_factory=database_runtime.session_factory,
            accounting_service=accounting_approval_service,
            document_signoff_service=document_signoff_service,
        )
        if database_runtime is not None
        and accounting_approval_service is not None
        and document_signoff_service is not None
        else None
    )
    project_operations = (
        EosGovernedProjectService(
            session_factory=database_runtime.session_factory,
            coordinator=business_transactions,
            authorization_source=authorization_source,
            project_authorizer=project_authorizer,
            allow_legacy_project_create=(
                environ.get("NEX_EOS_ALLOW_LEGACY_DIRECT_PROJECT_CREATE", "0") == "1"
            ),
            project_agent_profile_policy_ref=environ.get(
                "NEX_EOS_PROJECT_AGENT_PROFILE_POLICY_REF"
            ),
        )
        if database_runtime is not None
        and business_transactions is not None
        and oa_token
        else None
    )
    project_entitlement_reconciliation = (
        EosProjectEntitlementReconciliationService(
            session_factory=database_runtime.session_factory,
            projection_source=HttpOaProjectEntitlementProjectionSource(
                base_url=environ.get("NEX_OA_BASE_URL", "http://127.0.0.1:8101"),
                service_token=oa_token,
                timeout_seconds=float(
                    environ.get("NEX_EOS_OA_PROJECT_TIMEOUT_SECONDS", "10")
                ),
            ),
        )
        if database_runtime is not None and oa_token
        else None
    )
    project_business_service = (
        EosProjectBusinessService(
            session_factory=database_runtime.session_factory,
            coordinator=business_transactions,
            authorization_source=authorization_source,
            project_authorizer=project_authorizer,
        )
        if database_runtime is not None
        and business_transactions is not None
        and authorization_source is not None
        else None
    )
    project_work_assignment_service = (
        EosProjectWorkAssignmentService(
            session_factory=database_runtime.session_factory,
            coordinator=business_transactions,
            authorization_source=authorization_source,
            project_authorizer=project_authorizer,
        )
        if database_runtime is not None
        and business_transactions is not None
        and authorization_source is not None
        else None
    )
    legal_entity_service = (
        EosLegalEntityService(legal_entities, authorization_source)
        if legal_entities is not None and authorization_source is not None
        else None
    )
    account_catalog_service = (
        EosAccountCatalogService(account_catalog, authorization_source)
        if account_catalog is not None and authorization_source is not None
        else None
    )
    publication_admissions = environ.get("NEX_EOS_COA_PUBLICATION_ADMISSIONS_JSON", "")
    coa_operations_service = (
        EosCoaOperationsService(
            repository=SqlAlchemyEosCoaOperationsRepository(
                database_runtime.session_factory
            ),
            coordinator=business_transactions,
            authorization_source=authorization_source,
            publication_admission=PinnedCoaPublicationAdmission.from_json(
                publication_admissions
            ),
        )
        if business_transactions is not None
        and authorization_source is not None
        and publication_admissions
        else None
    )
    reporting_map_service = (
        EosReportingMapService(
            SqlAlchemyEosReportingMapRepository(database_runtime.session_factory),
            authorization_source,
        )
        if database_runtime is not None and authorization_source is not None
        else None
    )
    coa_release_admin_service = (
        EosCoaReleaseAdminService(
            SqlAlchemyEosCoaReleaseAdminRepository(database_runtime.session_factory),
            authorization_source,
        )
        if database_runtime is not None and authorization_source is not None
        else None
    )
    accounting_period_service = (
        EosAccountingPeriodService(
            SqlAlchemyEosAccountingPeriodRepository(database_runtime.session_factory),
            authorization_source,
        )
        if database_runtime is not None and authorization_source is not None
        else None
    )
    fx_rate_service = (
        EosFxRateService(
            SqlAlchemyEosFxRateRepository(database_runtime.session_factory),
            authorization_source,
        )
        if database_runtime is not None and authorization_source is not None
        else None
    )
    voucher_access_service = (
        EosVoucherAccessService(
            session_factory=database_runtime.session_factory,
            authorization_source=authorization_source,
        )
        if database_runtime is not None and authorization_source is not None
        else None
    )
    voucher_command_service = (
        EosCreateVoucherDraftService(
            coordinator=business_transactions,
            vouchers=vouchers,
            authorizer=EosVoucherAuthorizationClient(
                authorization_source,
                project_authorizer=project_authorizer,
            ),
            project_access=voucher_access_service,
            attachments=attachments,
        )
        if business_transactions is not None and vouchers is not None and oa_token
        else None
    )
    voucher_candidate_command_service = (
        EosCreateVoucherCandidateService(
            coordinator=business_transactions,
            candidates=voucher_candidates,
            authorizer=EosVoucherAuthorizationClient(
                authorization_source,
                required_scope=EOS_VOUCHER_CANDIDATE_CREATE_SCOPE,
                project_authorizer=project_authorizer,
            ),
        )
        if business_transactions is not None
        and voucher_candidates is not None
        and authorization_source is not None
        else None
    )
    voucher_candidate_revision_service = (
        EosReviseVoucherCandidateService(
            coordinator=business_transactions,
            candidates=voucher_candidates,
            reviews=candidate_review_repository,
            authorizer=EosVoucherAuthorizationClient(
                authorization_source,
                required_scope=EOS_VOUCHER_CANDIDATE_CREATE_SCOPE,
                project_authorizer=project_authorizer,
            ),
        )
        if business_transactions is not None
        and voucher_candidates is not None
        and candidate_review_repository is not None
        and authorization_source is not None
        else None
    )
    business_operation_query = (
        SqlAlchemyEosBusinessOperationQuery(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    voucher_verification_query = (
        SqlAlchemyEosVoucherVerificationQuery(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    return EosDependencies(
        service_token_admission=build_service_token_admission_runtime(
            expected_audience=settings.service_id,
            environ=environ,
        ),
        readiness_checks=(build_configuration_readiness_check(settings),),
        database_runtime=database_runtime,
        business_transactions=business_transactions,
        organization=organization,
        approver_resolution_service=approver_resolution_service,
        projects=projects,
        project_application_service=project_application_service,
        project_application_approval_service=project_application_approval_service,
        project_memberships=project_memberships,
        project_operations=project_operations,
        project_entitlement_reconciliation=project_entitlement_reconciliation,
        project_business_service=project_business_service,
        project_work_assignment_service=project_work_assignment_service,
        legal_entities=legal_entities,
        legal_entity_service=legal_entity_service,
        accounts=accounts,
        account_catalog=account_catalog,
        account_catalog_service=account_catalog_service,
        coa_operations_service=coa_operations_service,
        reporting_map_service=reporting_map_service,
        coa_release_admin_service=coa_release_admin_service,
        accounting_period_service=accounting_period_service,
        accounting_approval_service=accounting_approval_service,
        accounting_posting_admission_service=accounting_posting_admission_service,
        journals=journals,
        journal_query_service=journal_query_service,
        journal_posting_service=journal_posting_service,
        document_signoff_service=document_signoff_service,
        scoped_approval_decision_router=scoped_approval_decision_router,
        fx_rate_service=fx_rate_service,
        approval_policies=approval_policies,
        approval_instances=approval_instances,
        approval_transition_service=approval_transition_service,
        approved_document_service=approved_document_service,
        scoped_approval_service=scoped_approval_service,
        business_formal_wc_adapter=business_formal_wc_adapter,
        vouchers=vouchers,
        attachments=attachments,
        voucher_command_service=voucher_command_service,
        voucher_access_service=voucher_access_service,
        business_operation_query=business_operation_query,
        voucher_verification_query=voucher_verification_query,
        voucher_candidates=voucher_candidates,
        voucher_candidate_command_service=voucher_candidate_command_service,
        voucher_candidate_revision_service=voucher_candidate_revision_service,
        candidate_validation_service=candidate_validation_service,
        candidate_review_repository=candidate_review_repository,
    )
