from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime import build_service_token_admission_runtime
from nex_runtime.service_token_admission import ServiceTokenAdmissionRuntime

from .accounts import SqlAlchemyEosAccountRepository
from .approval_instances import SqlAlchemyEosApprovalInstanceRepository
from .approval_policies import SqlAlchemyEosApprovalPolicyRepository
from .approval_transitions import (
    EosBusinessApprovalTransitionService,
    SqlAlchemyEosApprovalTransitionRepository,
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
from .config import EosSettings
from .health import build_configuration_readiness_check
from .organization import SqlAlchemyEosOrganizationRepository
from .persistence import EosDatabaseRuntime, build_eos_database_runtime
from .projects import SqlAlchemyEosProjectRepository
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
    accounts: SqlAlchemyEosAccountRepository | None
    approval_policies: SqlAlchemyEosApprovalPolicyRepository | None
    approval_instances: SqlAlchemyEosApprovalInstanceRepository | None
    approval_transition_service: EosBusinessApprovalTransitionService | None
    business_formal_wc_adapter: EosBusinessFormalWcAdapter | None
    vouchers: SqlAlchemyEosVoucherRepository | None
    attachments: SqlAlchemyEosAttachmentRepository | None
    voucher_command_service: EosCreateVoucherDraftService | None
    business_operation_query: SqlAlchemyEosBusinessOperationQuery | None
    voucher_verification_query: SqlAlchemyEosVoucherVerificationQuery | None


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
    accounts = (
        SqlAlchemyEosAccountRepository(database_runtime.session_factory)
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
    voucher_command_service = (
        EosCreateVoucherDraftService(
            coordinator=business_transactions,
            vouchers=vouchers,
            authorizer=EosVoucherAuthorizationClient(
                HttpOaAuthorizationSource(
                    base_url=environ.get("NEX_OA_BASE_URL", "http://127.0.0.1:8101"),
                    service_token=oa_token,
                )
            ),
            attachments=attachments,
        )
        if business_transactions is not None and vouchers is not None and oa_token
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
        accounts=accounts,
        approval_policies=approval_policies,
        approval_instances=approval_instances,
        approval_transition_service=approval_transition_service,
        business_formal_wc_adapter=business_formal_wc_adapter,
        vouchers=vouchers,
        attachments=attachments,
        voucher_command_service=voucher_command_service,
        business_operation_query=business_operation_query,
        voucher_verification_query=voucher_verification_query,
    )
