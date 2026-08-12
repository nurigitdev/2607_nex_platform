from __future__ import annotations

import json
from pathlib import Path


WEB_ROOT = Path(__file__).parents[1] / "apps" / "nex-ae-web"


def read_web_file(relative_path: str) -> str:
    return (WEB_ROOT / relative_path).read_text(encoding="utf-8")


def test_ae_web_shell_exposes_mvp_workspace_surfaces() -> None:
    html = read_web_file("index.html")

    for required_id in [
        "workspace-summary",
        "runtime-diagnostics-panel",
        "runtime-diagnostics-status",
        "runtime-diagnostics-summary",
        "runtime-diagnostics-preview",
        "message-list",
        "progress-timeline",
        "upload-surface-panel",
        "upload-status",
        "upload-submit-button",
        "upload-retry-button",
        "upload-feedback",
        "upload-owner-scope",
        "upload-client-summary",
        "upload-payload-preview",
        "document-list",
        "document-detail-panel",
        "document-detail",
        "document-detail-status",
        "document-detail-retry-button",
        "document-detail-feedback",
        "retrieval-scope-panel",
        "retrieval-scope-status",
        "retrieval-retry-button",
        "retrieval-feedback",
        "retrieval-scope-summary",
        "retrieval-client-summary",
        "retrieval-scope-preview",
        "ae-web-runtime-config",
        "artifact-panel",
        "audit-panel",
        "retrieval-toggle",
        "format-select",
    ]:
        assert f'id="{required_id}"' in html
    assert "Slice 0227" in html
    assert "lang=\"ko\"" in html


def test_ae_web_upload_surface_tracks_owner_scope_contract() -> None:
    javascript = read_web_file("src/main.js")
    upload_surface = read_web_file("src/uploadSurface.js")
    upload_client = read_web_file("src/uploadClient.js")
    client_registry = read_web_file("src/clientRegistry.js")

    for expected in [
        "buildUploadSurfaceDraft",
        "buildUploadHandoffPayload",
        "uploadDraft",
        "uploadClient",
        "uploadSubmission",
        "submitUploadDraft",
        "safeUploadPreview",
        "renderUploadSurface",
        "uploadedByUserId",
        "ownership_ref",
        "tenant_id",
        "owner_user_id",
        "uploaded_by_user_id",
    ]:
        assert expected in javascript

    for expected in [
        "ae_web_upload_surface.v1",
        "ae_upload_handoff.v1",
        "/api/v1/uploads",
        "cx_source_ownership_ref.v1",
        "legacy_owner_fields_mapped_to_oa_subject_refs",
        "buildUploadSurfaceFromHandoff",
        "UploadSurfaceError",
        "browserServiceTokenIncluded: false",
        "cxStorageIncluded: false",
    ]:
        assert expected in upload_surface

    for expected in [
        "ae_web_upload_client.v1",
        "createMockUploadClient",
        "createFetchUploadClient",
        "submitUploadDraft",
        "credentials: \"same-origin\"",
        "Content-Type\": \"application/json\"",
        "NETWORK_ERROR",
        "FETCH_UNAVAILABLE",
        "buildUploadSubmissionResult",
    ]:
        assert expected in upload_client

    assert "createMockUploadClient" in client_registry

    for forbidden in [
        "content_text",
        "content_base64",
        "service_token",
        "api_key",
        "storage_uri",
        "storage_path",
        "provider_url",
    ]:
        assert forbidden not in javascript
        assert forbidden not in upload_surface
        assert forbidden not in upload_client
        assert forbidden not in client_registry


def test_ae_web_document_surface_tracks_detail_facade_boundary() -> None:
    javascript = read_web_file("src/main.js")
    client = read_web_file("src/documentDetailClient.js")
    client_registry = read_web_file("src/clientRegistry.js")

    for expected in [
        "selectedDocumentId",
        "renderDocumentDetail",
        "documentDetailRoute",
        "composeAuthenticatedSessionRuntime",
        "clientRegistry",
        "ae_document_detail_projection.v1",
        "ownerScope",
        "sourceKind: \"postgres-read\"",
        "nex-cx",
    ]:
        assert expected in javascript
    for expected in [
        "createMockDocumentDetailClient",
        "createFetchDocumentDetailClient",
        "DocumentDetailClientError",
        "credentials: \"same-origin\"",
        "Accept: \"application/json\"",
        "buildDocumentSurfaceFromProjection",
        "/api/v1/documents/",
        "NETWORK_ERROR",
        "PROJECTION_INVALID",
    ]:
        assert expected in client

    for forbidden in [
        "source_storage_path",
        "sourceStoragePath",
        "source_storage_uri",
        "sourceStorageUri",
        "raw_summary",
        "rawSummary",
        "embedding_vector",
        "embeddingVector",
        "markdown_text",
        "markdownText",
        "/data/nex-platform",
    ]:
        assert forbidden not in javascript
        assert forbidden not in client
        assert forbidden not in client_registry


def test_ae_web_document_scope_propagates_to_retrieval_surface() -> None:
    javascript = read_web_file("src/main.js")
    document_scope = read_web_file("src/documentScope.js")
    retrieval_client = read_web_file("src/retrievalClient.js")
    client_registry = read_web_file("src/clientRegistry.js")

    for expected in [
        "buildDocumentScope",
        "buildRetrievalRequest",
        "documentScopeLabel",
        "renderRetrievalScope",
        "renderRetrievalClientSummary",
        "submitRetrievalRequest",
        "retrievalScope",
        "retrievalClient",
        "lastRetrievalResult",
        "lastRetrievalRequest",
        "safeRetrievalPreview",
        "document_scope",
        "selected_count",
    ]:
        assert expected in javascript

    for expected in [
        "ae_web_document_scope.v1",
        "ae_retrieval_interaction.v1",
        "/api/v1/retrieval/contexts",
        "DOCUMENT_SEARCH",
        "GENERAL_CHAT",
        "include_source_preview: false",
        "DOCUMENT_SCOPE_EMPTY",
        "DOCUMENT_SCOPE_UNKNOWN_DOCUMENT",
    ]:
        assert expected in document_scope

    for expected in [
        "ae_web_retrieval_client.v1",
        "createMockRetrievalClient",
        "createFetchRetrievalClient",
        "submitRetrievalRequest",
        "credentials: \"same-origin\"",
        "Content-Type\": \"application/json\"",
        "NETWORK_ERROR",
        "FETCH_UNAVAILABLE",
        "RETRIEVAL_RECORD_INVALID",
        "NO_ANSWER",
        "NOT_REQUESTED",
    ]:
        assert expected in retrieval_client

    for forbidden in [
        "raw_prompt",
        "source_preview_text",
        "chunk_text",
        "content_text",
        "provider_url",
    ]:
        assert forbidden not in javascript
        assert forbidden not in document_scope
        assert forbidden not in retrieval_client
        assert forbidden not in client_registry


def test_ae_web_client_registry_composes_runtime_clients_safely() -> None:
    javascript = read_web_file("src/main.js")
    authenticated_runtime = read_web_file("src/authenticatedRuntime.js")
    session_bootstrap = read_web_file("src/sessionBootstrap.js")
    client_registry = read_web_file("src/clientRegistry.js")
    runtime_config = read_web_file("src/runtimeConfig.js")
    fetch_harness = read_web_file("src/fetchModeHarness.js")
    operation_state = read_web_file("src/operationState.js")
    operation_feedback = read_web_file("src/operationFeedback.js")
    runtime_diagnostics = read_web_file("src/runtimeDiagnostics.js")
    auth_boundary = read_web_file("src/authBoundary.js")
    session_client = read_web_file("src/sessionClient.js")

    for expected in [
        "buildAuthenticatedRuntimeSummary",
        "bootstrapAuthenticatedSessionRuntime",
        "buildSessionBootstrapSummary",
        "composeAuthenticatedSessionRuntime",
        "buildClientRegistrySummary",
        "loadRuntimeConfig",
        "buildRuntimeConfigSummary",
        "authenticatedRuntime",
        "sessionBootstrap",
        "sessionState",
        "sessionClient",
        "authBoundary",
        "runtimeConfig",
        "clientRegistry",
        "operations",
        "buildOperationStateSummary",
        "markOperationRunning",
        "markOperationSucceeded",
        "markOperationFailed",
        "buildOperationFeedback",
        "renderOperationFeedback",
        "retryLastRetrievalRequest",
        "documentDetailRetryButton",
        "uploadRetryButton",
        "retrievalRetryButton",
        "buildRuntimeDiagnostics",
        "buildRuntimeDiagnosticsSummary",
        "renderRuntimeDiagnostics",
    ]:
        assert expected in javascript

    for expected in [
        "ae_web_authenticated_runtime.v1",
        "createAuthenticatedAeWebRuntime",
        "buildAuthenticatedRuntimeSummary",
        "auditAuthenticatedRuntimeBoundary",
        "createFetchSessionClient",
        "createMockSessionClient",
        "AUTHENTICATED_RUNTIME_FETCH_BLOCKED",
        "AUTHENTICATED_RUNTIME_SESSION_INVALID",
        "authBoundary.fetch_mode.blocked_reasons",
        "rawTokenStored: false",
        "serviceTokenStored: false",
        "passwordStored: false",
        "claimAuthoritativeWhenAuthenticated: true",
    ]:
        assert expected in authenticated_runtime

    for expected in [
        "ae_web_session_bootstrap.v1",
        "AE_WEB_SESSION_BOOTSTRAP_PHASES",
        "bootstrapAuthenticatedSessionRuntime",
        "composeAuthenticatedSessionRuntime",
        "buildSessionBootstrapSummary",
        "SESSION_BOOTSTRAP_SUMMARY_INVALID",
        "SESSION_BOOTSTRAP_PHASE_UNSUPPORTED",
        "blockedFetchFallbackClientMode",
        "sessionReadFailed: false",
        "rawTokenStored: false",
        "serviceTokenStored: false",
        "passwordStored: false",
        "claimAuthoritativeWhenAuthenticated: true",
    ]:
        assert expected in session_bootstrap

    for expected in [
        "ae_web_client_registry.v1",
        "AE_WEB_CLIENT_MODES",
        "createMockDocumentDetailClient",
        "createFetchDocumentDetailClient",
        "createMockUploadClient",
        "createFetchUploadClient",
        "createMockRetrievalClient",
        "createFetchRetrievalClient",
        "CLIENT_MODE_UNSUPPORTED",
        "CLIENT_REGISTRY_SUMMARY_INVALID",
        "browserServiceTokenIncluded: false",
        "databaseUrlIncluded: false",
        "providerUrlIncluded: false",
    ]:
        assert expected in client_registry

    for expected in [
        "ae_web_runtime_config.v1",
        "ae-web-runtime-config",
        "loadRuntimeConfig",
        "normalizeRuntimeConfig",
        "buildRuntimeConfigSummary",
        "fetch_clients_enabled",
        "FETCH_MODE_NOT_ENABLED",
        "RUNTIME_CONFIG_FIELD_UNSUPPORTED",
        "RUNTIME_CONFIG_JSON_INVALID",
        "browserCredentialIncluded: false",
        "databaseEndpointIncluded: false",
        "providerEndpointIncluded: false",
        "storageLocationIncluded: false",
    ]:
        assert expected in runtime_config

    for expected in [
        "ae_web_fetch_mode_harness.v1",
        "runFetchModeHarness",
        "createAeWebClients",
        "normalizeRuntimeConfig",
        "HARNESS_FETCH_REQUIRED",
        "HARNESS_DOCUMENT_REQUIRED",
        "liveNetworkUsed: false",
        "rawPromptRendered: false",
        "sourcePreviewIncluded: false",
        "databaseEndpointIncluded: false",
        "providerEndpointIncluded: false",
    ]:
        assert expected in fetch_harness

    for expected in [
        "ae_web_operation_state.v1",
        "AE_WEB_OPERATION_PHASES",
        "createOperationState",
        "markOperationRunning",
        "markOperationSucceeded",
        "markOperationFailed",
        "buildOperationStateSummary",
        "OPERATION_PHASE_UNSUPPORTED",
        "OPERATION_ATTEMPT_INVALID",
        "browserServiceTokenIncluded: false",
        "rawPromptRendered: false",
        "rawSourceIncluded: false",
        "databaseEndpointIncluded: false",
        "providerEndpointIncluded: false",
    ]:
        assert expected in operation_state

    for expected in [
        "ae_web_operation_feedback.v1",
        "OperationFeedbackError",
        "buildOperationFeedback",
        "buildRetryControl",
        "OPERATION_SUMMARY_INVALID",
        "rawErrorMessageIncluded: false",
        "rawPromptRendered: false",
        "rawSourceIncluded: false",
        "databaseEndpointIncluded: false",
        "providerEndpointIncluded: false",
        "storageLocationIncluded: false",
    ]:
        assert expected in operation_feedback

    for expected in [
        "ae_web_runtime_diagnostics.v1",
        "RuntimeDiagnosticsError",
        "buildRuntimeDiagnostics",
        "buildRuntimeDiagnosticsSummary",
        "RUNTIME_DIAGNOSTICS_SCHEMA_INVALID",
        "RUNTIME_DIAGNOSTICS_OPERATIONS_INVALID",
        "browserCredentialIncluded: false",
        "serviceTokenIncluded: false",
        "rawPromptRendered: false",
        "rawSourceIncluded: false",
        "databaseEndpointIncluded: false",
        "providerEndpointIncluded: false",
        "storageLocationIncluded: false",
        "liveNetworkUsed: false",
        "session_state",
        "session_bootstrap",
        "session_bootstrap_phase",
        "auth_boundary",
        "fetch_mode_allowed",
        "buildSessionStateSummary",
        "buildSessionBootstrapSummary",
        "buildAuthBoundarySummary",
    ]:
        assert expected in runtime_diagnostics

    for expected in [
        "ae_web_auth_boundary.v1",
        "auditAuthenticatedRuntimeBoundary",
        "buildAuthBoundarySummary",
        "assertBrowserRuntimeSafe",
        "BROWSER_RUNTIME_SECRET_FIELD",
        "nex-ae-api-only",
        "serviceTokenIncluded: false",
        "databaseUrlIncluded: false",
        "providerSecretIncluded: false",
        "storagePathIncluded: false",
        "rawSourceIncluded: false",
        "browserPayloadAuthoritative: false",
        "claimAuthoritative",
    ]:
        assert expected in auth_boundary

    for expected in [
        "ae_web_session_state.v1",
        "ae_web_session_client.v1",
        "normalizeBrowserSessionSnapshot",
        "createMockSessionClient",
        "createFetchSessionClient",
        "buildSessionStateSummary",
        "buildSessionClientSummary",
        "SESSION_SECRET_FIELD",
        "credentials: \"same-origin\"",
        "rawTokenIncluded: false",
        "serviceTokenIncluded: false",
        "passwordIncluded: false",
        "claimOwnerAuthoritative: true",
    ]:
        assert expected in session_client

    for forbidden in [
        "service_token",
        "api_key",
        "database_url",
        "provider_url",
        "/data/nex-platform",
    ]:
        assert forbidden not in javascript
        assert forbidden not in authenticated_runtime
        assert forbidden not in session_bootstrap
        assert forbidden not in client_registry
        assert forbidden not in runtime_config
        assert forbidden not in fetch_harness
        assert forbidden not in operation_state
        assert forbidden not in operation_feedback
        assert forbidden not in runtime_diagnostics
        assert forbidden not in auth_boundary
        assert forbidden not in session_client


def test_ae_web_mock_state_links_generation_artifact_and_audit_contracts() -> None:
    javascript = read_web_file("src/main.js")

    for expected in [
        "generation.retrieval.ready",
        "generation.citation.validating",
        "READY_FOR_RENDERING",
        "compat-grounded-answer-v1",
        "handoff-local",
        "artifact-version-local-001",
        "artifactRefs",
        "download_md",
        "general-llm-default",
    ]:
        assert expected in javascript
    assert "raw_prompt" not in javascript
    assert "provider_url" not in javascript
    assert "/data/nex-platform" not in javascript


def test_ae_web_styles_keep_responsive_operational_layout() -> None:
    styles = read_web_file("src/styles.css")

    assert "grid-template-columns: minmax(220px, 260px) minmax(0, 1fr)" in styles
    assert "@media (max-width: 620px)" in styles
    assert "overflow-wrap: anywhere" in styles
    assert ".document-detail" in styles
    assert ".document-detail.is-loading" in styles
    assert ".payload-preview" in styles
    assert ".client-summary" in styles
    assert ".operation-feedback" in styles
    assert ".operation-feedback[data-severity=\"danger\"]" in styles
    assert ".retrieval-scope-chip" in styles
    assert ".document-row.is-selected" in styles
    assert ".document-action-row" in styles
    assert ".artifact-link" in styles
    assert ".artifact-actions" in styles
    assert "letter-spacing: 0" in styles
    assert "letter-spacing: -" not in styles
    assert "linear-gradient" not in styles


def test_ae_web_static_browser_smoke_runner_is_quality_gate_wired() -> None:
    runner = (
        Path(__file__).parents[1]
        / "scripts"
        / "smoke"
        / "run_ae_web_static_browser_smoke.py"
    ).read_text(encoding="utf-8")
    quality_gate = (
        Path(__file__).parents[1] / "scripts" / "quality" / "run_quality_gate.sh"
    ).read_text(encoding="utf-8")

    for expected in [
        "ae_web_static_browser_smoke",
        "DEFAULT_SLICE_LABEL = \"Slice 0227\"",
        "required_anchors",
        "runtime-diagnostics-panel",
        "upload-retry-button",
        "document-detail-feedback",
        "retrieval-retry-button",
        "BrowserSmokeResult",
        "validate_html",
        "wait_for_html",
        "stop_process",
    ]:
        assert expected in runner

    assert "run_ae_web_static_browser_smoke.py --summary" in quality_gate
    for forbidden in [
        "service_token",
        "api_key",
        "database_url",
        "provider_url",
        "/data/nex-platform",
    ]:
        assert forbidden not in runner


def test_ae_web_package_version_tracks_slice_0227() -> None:
    package = json.loads(read_web_file("package.json"))

    assert package["name"] == "nex-ae-web"
    assert package["version"] == "0.0.0-slice0227"
    assert package["scripts"]["dev"] == "node scripts/serve.mjs"
    assert package["scripts"]["test"] == "node --test test/*.test.mjs"
