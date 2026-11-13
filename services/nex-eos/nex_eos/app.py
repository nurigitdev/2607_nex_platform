from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import FastAPI
from nex_runtime import SERVICE_SPECS, build_service_app

from .account_api import register_account_routes
from .account_policy_api import register_account_policy_routes
from .accounting_period_api import register_accounting_period_routes
from .allocation_plan_api import register_allocation_plan_routes
from .approval_decision_api import register_approval_decision_routes
from .approved_document_api import register_approved_document_routes
from .coa_api import register_coa_routes
from .coa_release_admin_api import register_coa_release_admin_routes
from .config import EosSettings, load_eos_settings
from .cost_source_pool_api import register_cost_source_pool_routes
from .dependencies import build_eos_dependencies
from .finance_v2_api import register_finance_v2_routes
from .fx_api import register_fx_rate_routes
from .legal_entity_api import register_legal_entity_routes
from .organization_api import register_organization_routes
from .project_api import register_project_routes
from .project_application_api import register_project_application_routes
from .project_business_api import register_project_business_routes
from .project_entitlement_reconciliation_api import (
    register_project_entitlement_reconciliation_routes,
)
from .project_work_assignment_api import register_project_work_assignment_routes
from .reporting_map_api import register_reporting_map_routes
from .scoped_approval_api import register_scoped_approval_routes
from .voucher_api import register_voucher_command_routes
from .wa_project_verification import (
    EosWaProjectVerifier,
    register_wa_project_verification_routes,
)

SERVICE_SPEC = SERVICE_SPECS["nex-eos"]
CONTRACT_CATALOG_VERSION = "mybee-w30-s3-02"


def create_eos_app(
    *,
    environ: Mapping[str, str] | None = None,
    settings: EosSettings | None = None,
) -> FastAPI:
    env = dict(os.environ if environ is None else environ)
    resolved = settings or load_eos_settings(env)
    env.update(
        {
            "NEX_PROFILE": resolved.profile,
            "NEX_VERSION": resolved.version,
            "NEX_BUILD_SHA": resolved.build_sha,
        }
    )
    dependencies = build_eos_dependencies(resolved, environ=env)
    app = build_service_app(
        SERVICE_SPEC,
        readiness_checks=dependencies.readiness_checks,
        include_oa_mock_auth_routes=False,
        service_token_admission=dependencies.service_token_admission,
        environ=env,
        contract_catalog_version=CONTRACT_CATALOG_VERSION,
        description=(
            "NeX Enterprise Operations System service runtime. Business domain "
            "routes are intentionally activated only by their owning slices."
        ),
    )
    app.state.eos_settings = resolved
    app.state.eos_dependencies = dependencies
    app.state.eos_database_runtime = dependencies.database_runtime
    app.state.eos_business_transactions = dependencies.business_transactions
    app.state.eos_organization = dependencies.organization
    app.state.eos_approver_resolution_service = dependencies.approver_resolution_service
    app.state.eos_projects = dependencies.projects
    app.state.eos_project_application_service = dependencies.project_application_service
    app.state.eos_project_application_approval_service = (
        dependencies.project_application_approval_service
    )
    app.state.eos_project_memberships = dependencies.project_memberships
    app.state.eos_project_operations = dependencies.project_operations
    app.state.eos_project_entitlement_reconciliation = (
        dependencies.project_entitlement_reconciliation
    )
    app.state.eos_project_business_service = dependencies.project_business_service
    app.state.eos_project_work_assignment_service = (
        dependencies.project_work_assignment_service
    )
    app.state.eos_legal_entities = dependencies.legal_entities
    app.state.eos_legal_entity_service = dependencies.legal_entity_service
    app.state.eos_accounts = dependencies.accounts
    app.state.eos_account_catalog = dependencies.account_catalog
    app.state.eos_account_catalog_service = dependencies.account_catalog_service
    app.state.eos_coa_operations_service = dependencies.coa_operations_service
    app.state.eos_reporting_map_service = dependencies.reporting_map_service
    app.state.eos_coa_release_admin_service = dependencies.coa_release_admin_service
    app.state.eos_accounting_period_service = dependencies.accounting_period_service
    app.state.eos_accounting_approval_service = dependencies.accounting_approval_service
    app.state.eos_accounting_posting_admission_service = (
        dependencies.accounting_posting_admission_service
    )
    app.state.eos_journals = dependencies.journals
    app.state.eos_journal_query_service = dependencies.journal_query_service
    app.state.eos_journal_posting_service = dependencies.journal_posting_service
    app.state.eos_journal_operation_service = dependencies.journal_operation_service
    app.state.eos_cost_source_pool_service = dependencies.cost_source_pool_service
    app.state.eos_allocation_plan_service = dependencies.allocation_plan_service
    app.state.eos_document_signoff_service = dependencies.document_signoff_service
    app.state.eos_scoped_approval_decision_router = (
        dependencies.scoped_approval_decision_router
    )
    app.state.eos_fx_rate_service = dependencies.fx_rate_service
    app.state.eos_approval_policies = dependencies.approval_policies
    app.state.eos_approval_instances = dependencies.approval_instances
    app.state.eos_approval_transition_service = dependencies.approval_transition_service
    app.state.eos_approved_document_service = dependencies.approved_document_service
    app.state.eos_scoped_approval_service = dependencies.scoped_approval_service
    app.state.eos_business_formal_wc_adapter = dependencies.business_formal_wc_adapter
    app.state.eos_vouchers = dependencies.vouchers
    app.state.eos_attachments = dependencies.attachments
    app.state.eos_voucher_command_service = dependencies.voucher_command_service
    app.state.eos_voucher_access_service = dependencies.voucher_access_service
    app.state.eos_business_operation_query = dependencies.business_operation_query
    app.state.eos_voucher_verification_query = dependencies.voucher_verification_query
    app.state.eos_voucher_candidates = dependencies.voucher_candidates
    app.state.eos_voucher_candidate_command_service = (
        dependencies.voucher_candidate_command_service
    )
    app.state.eos_voucher_candidate_revision_service = (
        dependencies.voucher_candidate_revision_service
    )
    app.state.eos_candidate_validation_service = (
        dependencies.candidate_validation_service
    )
    app.state.eos_candidate_review_repository = dependencies.candidate_review_repository
    register_voucher_command_routes(app)
    register_finance_v2_routes(app)
    register_cost_source_pool_routes(app)
    register_allocation_plan_routes(app)
    register_approval_decision_routes(app)
    register_approved_document_routes(app)
    register_scoped_approval_routes(app)
    register_organization_routes(app)
    register_project_application_routes(app)
    register_project_routes(app)
    register_project_entitlement_reconciliation_routes(app)
    register_project_business_routes(app)
    register_project_work_assignment_routes(app)
    register_account_routes(app)
    register_account_policy_routes(app)
    register_coa_routes(app)
    register_coa_release_admin_routes(app)
    register_reporting_map_routes(app)
    register_legal_entity_routes(app)
    register_accounting_period_routes(app)
    register_fx_rate_routes(app)
    verifier = (
        EosWaProjectVerifier(
            projects=dependencies.projects,
            memberships=dependencies.project_memberships,
        )
        if dependencies.projects is not None
        and dependencies.project_memberships is not None
        else None
    )
    register_wa_project_verification_routes(app, verifier=verifier)
    return app
