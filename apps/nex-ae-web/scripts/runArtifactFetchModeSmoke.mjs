#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import {
  createAuthenticatedAeWebRuntime
} from "../src/authenticatedRuntime.js";
import {
  buildArtifactClientSummary
} from "../src/artifactClient.js";
import {
  buildArtifactPreviewPanelStateFromDownload,
  buildArtifactPreviewPanelStateFromPreview,
  buildArtifactPreviewPanelSummary
} from "../src/artifactPreviewPanel.js";
import {
  buildArtifactVersionPanelState,
  buildArtifactVersionPanelSummary
} from "../src/artifactVersionPanel.js";
import {
  normalizeBrowserSessionSnapshot
} from "../src/sessionClient.js";

export const AE_WEB_ARTIFACT_FETCH_MODE_SMOKE_SCHEMA_VERSION =
  "ae_web_artifact_fetch_mode_smoke.v1";

const ARTIFACT_ID = "artifact-slice-0417";
const ARTIFACT_VERSION_ID = "artifact-version-slice-0417";
const ARTIFACT_FILE_ID = "artifact-file-slice-0417";
const EXPORT_RENDER_REQUEST_ID = "artifact-export-slice-0428-pdf";
const EXPORT_ARTIFACT_VERSION_ID = "artifact-version-slice-0428-pdf";
const PDF_ARTIFACT_FILE_ID = "artifact-file-slice-0428-pdf";
const RAW_DOWNLOAD_CONTENT =
  "# Artifact Slice 0417\n\nThis private artifact body must not appear in evidence.";
const RAW_BINARY_DOWNLOAD_CONTENT_BASE64 = "JVBERi0xLjQKJQ==";

export async function runArtifactFetchModeSmoke() {
  const fakeFetch = createFakeArtifactFetch();
  const sessionState = normalizeBrowserSessionSnapshot(activeSession());
  const runtime = createAuthenticatedAeWebRuntime({
    runtimeConfig: {
      client_mode: "fetch",
      ae_base_url: "/ae-api",
      features: {
        fetch_clients_enabled: true
      }
    },
    sessionState,
    fetchImpl: fakeFetch.fetchImpl
  });
  const artifactClient = runtime.clientRegistry.artifactClient;
  const artifactSurface = await artifactClient.getArtifact(ARTIFACT_ID);
  const versionsSurface = await artifactClient.listArtifactVersions(ARTIFACT_ID);
  const artifactFile = await artifactClient.getArtifactFile(ARTIFACT_FILE_ID);
  const previewSurface = await artifactClient.previewArtifactFile(ARTIFACT_FILE_ID);
  const downloadSurface = await artifactClient.downloadArtifactFile(ARTIFACT_FILE_ID);
  const exportSurface = await artifactClient.submitArtifactExportRequest({
    artifactId: ARTIFACT_ID,
    renderRequestId: EXPORT_RENDER_REQUEST_ID,
    targetFormats: ["PDF"]
  });
  const pdfFile = await artifactClient.getArtifactFile(PDF_ARTIFACT_FILE_ID);
  const binaryDownloadSurface = await artifactClient.downloadArtifactFile(
    PDF_ARTIFACT_FILE_ID
  );

  const versionPanel = buildArtifactVersionPanelState({
    artifactSurface,
    versionsSurface
  });
  const previewPanel = buildArtifactPreviewPanelStateFromPreview(previewSurface, {
    artifactId: ARTIFACT_ID
  });
  const downloadPanel = buildArtifactPreviewPanelStateFromDownload(downloadSurface, {
    artifactId: ARTIFACT_ID
  });
  const binaryDownloadPanel =
    buildArtifactPreviewPanelStateFromDownload(binaryDownloadSurface, {
      artifactId: ARTIFACT_ID
    });
  const checks = {
    runtime_fetch_mode_allowed: runtime.authBoundary.fetch_mode.allowed === true,
    runtime_uses_fetch_artifact_client: artifactClient.clientMode === "fetch",
    same_origin_route_sequence_matches: artifactRouteSequence(fakeFetch.calls),
    no_authorization_header_in_browser_fetch: fakeFetch.calls.every(
      call => !Object.keys(call.headers).some(key => key.toLowerCase() === "authorization")
    ),
    artifact_summary_safe:
      buildArtifactClientSummary(artifactSurface).content_included === false,
    version_panel_ready:
      buildArtifactVersionPanelSummary(versionPanel).status === "VERSION_READY",
    file_metadata_readback: artifactFile.artifactFileId === ARTIFACT_FILE_ID,
    preview_panel_ready:
      buildArtifactPreviewPanelSummary(previewPanel).status === "PREVIEW_READY",
    download_panel_metadata_only:
      buildArtifactPreviewPanelSummary(downloadPanel).status === "DOWNLOAD_READY" &&
      !JSON.stringify(downloadPanel).includes(RAW_DOWNLOAD_CONTENT),
    export_submit_route_same_origin: exportSubmitRouteMatches(fakeFetch.calls),
    export_result_ready:
      buildArtifactClientSummary(exportSurface.artifactSurface).available_format_count === 2,
    binary_file_metadata_readback: pdfFile.artifactFileId === PDF_ARTIFACT_FILE_ID,
    binary_download_surface_base64:
      binaryDownloadSurface.downloadPayloadKind === "base64" &&
      binaryDownloadSurface.contentEncoding === "base64" &&
      binaryDownloadSurface.contentLength === 10 &&
      binaryDownloadSurface.encodedContentLength === RAW_BINARY_DOWNLOAD_CONTENT_BASE64.length,
    binary_download_panel_metadata_only:
      buildArtifactPreviewPanelSummary(binaryDownloadPanel).status === "DOWNLOAD_READY" &&
      buildArtifactPreviewPanelSummary(binaryDownloadPanel).download_payload_kind === "base64" &&
      !JSON.stringify(binaryDownloadPanel).includes(RAW_BINARY_DOWNLOAD_CONTENT_BASE64),
    live_network_not_used: true,
    postgresql_not_used: true
  };
  const evidence = {
    smoke_schema_version: AE_WEB_ARTIFACT_FETCH_MODE_SMOKE_SCHEMA_VERSION,
    evidence_generated_at: new Date().toISOString(),
    status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
    runner: {
      mode: "deterministic_fake_fetch",
      slice: "Slice 0417",
      browser_api_path: "/ae-api",
      live_network_used: false,
      postgresql_used: false
    },
    runtime: {
      client_mode: runtime.runtimeConfig.clientMode,
      fetch_mode_allowed: runtime.authBoundary.fetch_mode.allowed,
      session_state: runtime.sessionState.status
    },
    artifact: {
      summary: buildArtifactClientSummary(artifactSurface),
      export_summary: buildArtifactClientSummary(exportSurface.artifactSurface),
      version_panel: buildArtifactVersionPanelSummary(versionPanel),
      preview_panel: buildArtifactPreviewPanelSummary(previewPanel),
      download_panel: buildArtifactPreviewPanelSummary(downloadPanel),
      binary_download_panel: buildArtifactPreviewPanelSummary(binaryDownloadPanel)
    },
    request_observations: {
      fetch_call_count: fakeFetch.calls.length,
      routes: fakeFetch.calls
    },
    checks,
    redaction: {
      rawDownloadContentInEvidence: false,
      rawHashInEvidence: false,
      rawStorageRefInEvidence: false,
      serviceCredentialInEvidence: false,
      databaseEndpointInEvidence: false,
      providerEndpointInEvidence: false
    }
  };
  assertArtifactFetchModeSmokeEvidenceRedacted(evidence, {
    rawDownloadContent: RAW_DOWNLOAD_CONTENT,
    rawBinaryDownloadContentBase64: RAW_BINARY_DOWNLOAD_CONTENT_BASE64
  });
  return evidence;
}

export function formatSummary(evidence) {
  if (evidence.status === "PASS") {
    return (
      "ae_web_artifact_fetch_mode_smoke=pass " +
      `mode=${evidence.runner.mode} ` +
      `artifact=${evidence.artifact.summary.artifact_id} ` +
      `versions=${evidence.artifact.version_panel.version_count} ` +
      `export_formats=${evidence.artifact.export_summary.available_format_count} ` +
      `fetch_calls=${evidence.request_observations.fetch_call_count}`
    );
  }
  return "ae_web_artifact_fetch_mode_smoke=fail";
}

export function assertArtifactFetchModeSmokeEvidenceRedacted(
  evidence,
  { rawDownloadContent, rawBinaryDownloadContentBase64 } = {}
) {
  const serialized = JSON.stringify(evidence);
  if (rawDownloadContent && serialized.includes(rawDownloadContent)) {
    throw new Error("artifact fetch-mode smoke leaked raw download content");
  }
  if (
    rawBinaryDownloadContentBase64 &&
    serialized.includes(rawBinaryDownloadContentBase64)
  ) {
    throw new Error("artifact fetch-mode smoke leaked raw binary download content");
  }
  for (const fragment of [
    "storage_" + "ref",
    "storage_" + "path",
    `database_${"url"}`,
    `provider_${"url"}`,
    `service_${"token"}`,
    "access_" + "token",
    "/data/" + "nex-platform",
    "ed6@c496em",
    "nuri1004"
  ]) {
    if (serialized.includes(fragment)) {
      throw new Error("artifact fetch-mode smoke leaked server material");
    }
  }
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  const summary = argv.includes("--summary");
  try {
    const evidence = await runArtifactFetchModeSmoke();
    output(summary ? formatSummary(evidence) : JSON.stringify(evidence, null, 2));
    return evidence.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(
      "ae_web_artifact_fetch_mode_smoke=fail " +
      `error=${error?.constructor?.name || "Error"}`
    );
    return 1;
  }
}

function createFakeArtifactFetch() {
  const state = {
    calls: [],
    fetchImpl: null
  };
  state.fetchImpl = async (url, options = {}) => {
    const method = options.method || "GET";
    const headers = options.headers || {};
    state.calls.push({
      method,
      url,
      credentials: options.credentials || "same-origin",
      headers: Object.fromEntries(Object.entries(headers).sort()),
      body: safeRequestObservationBody(options.body)
    });
    if (url === `/ae-api/api/v1/artifacts/${ARTIFACT_ID}` && method === "GET") {
      return jsonResponse({ payload: artifactRecord() });
    }
    if (
      url === `/ae-api/api/v1/artifacts/${ARTIFACT_ID}/versions` &&
      method === "GET"
    ) {
      return jsonResponse({
        payload: {
          artifact_id: ARTIFACT_ID,
          current_version_id: ARTIFACT_VERSION_ID,
          versions: artifactRecord().versions
        }
      });
    }
    if (
      url === `/ae-api/api/v1/artifact-files/${ARTIFACT_FILE_ID}` &&
      method === "GET"
    ) {
      return jsonResponse({ payload: artifactRecord().files[0] });
    }
    if (
      url === `/ae-api/api/v1/artifact-files/${ARTIFACT_FILE_ID}/preview` &&
      method === "GET"
    ) {
      return jsonResponse({ payload: previewPayload() });
    }
    if (
      url === `/ae-api/api/v1/artifact-files/${ARTIFACT_FILE_ID}/download` &&
      method === "GET"
    ) {
      return jsonResponse({ payload: downloadPayload() });
    }
    if (
      url === `/ae-api/api/v1/artifacts/${ARTIFACT_ID}/render-jobs` &&
      method === "POST"
    ) {
      return jsonResponse({ payload: exportPayload() });
    }
    if (
      url === `/ae-api/api/v1/artifact-files/${PDF_ARTIFACT_FILE_ID}` &&
      method === "GET"
    ) {
      return jsonResponse({ payload: exportedArtifactRecord().files.at(-1) });
    }
    if (
      url === `/ae-api/api/v1/artifact-files/${PDF_ARTIFACT_FILE_ID}/download` &&
      method === "GET"
    ) {
      return jsonResponse({ payload: binaryDownloadPayload() });
    }
    return jsonResponse({
      ok: false,
      status: 404,
      payload: { error_code: "ae.fake_artifact_route_not_found" }
    });
  };
  return state;
}

function artifactRecord() {
  return {
    artifact_schema_version: "ae_artifact_record.v1",
    artifact_id: ARTIFACT_ID,
    artifact_type: "generated_document",
    artifact_status: "READY",
    current_version_id: ARTIFACT_VERSION_ID,
    chat_document_id: "chat-doc-slice-0417",
    interaction_id: "interaction-slice-0417",
    display_title: "Artifact fetch-mode smoke",
    target_formats: ["MD"],
    source_refs: [
      {
        cx_generation_id: "cx-generation-slice-0417",
        structured_draft_content_hash: "c".repeat(64),
        evidence_ref_count: 2,
        quality_summary: {
          citation_status: "VALIDATED",
          citation_count: 2,
          evidence_ref_count: 2,
          grounding_required: true
        }
      }
    ],
    versions: [
      {
        artifact_version_id: ARTIFACT_VERSION_ID,
        version_no: 1,
        source_content_hash: "c".repeat(64),
        artifact_content_hash: "d".repeat(64),
        rendered_formats: ["MD"]
      }
    ],
    files: [
      {
        artifact_file_id: ARTIFACT_FILE_ID,
        artifact_id: ARTIFACT_ID,
        artifact_version_id: ARTIFACT_VERSION_ID,
        format: "MD",
        mime_type: "text/markdown",
        file_name: "artifact-slice-0417.md",
        storage_ref: "ae://artifacts/slice-0417/private-storage-ref.md",
        file_size_bytes: 1024,
        file_hash: "f".repeat(64),
        source_version_hash: "d".repeat(64)
      }
    ],
    links: [
      {
        artifact_file_id: ARTIFACT_FILE_ID,
        link_type: "preview",
        link_route: `/api/v1/artifact-files/${ARTIFACT_FILE_ID}/preview`,
        access_policy: "owner_only"
      },
      {
        artifact_file_id: ARTIFACT_FILE_ID,
        link_type: "download",
        link_route: `/api/v1/artifact-files/${ARTIFACT_FILE_ID}/download`,
        access_policy: "owner_only"
      }
    ]
  };
}

function exportedArtifactRecord() {
  const record = artifactRecord();
  const pdfFile = {
    artifact_file_id: PDF_ARTIFACT_FILE_ID,
    artifact_id: ARTIFACT_ID,
    artifact_version_id: EXPORT_ARTIFACT_VERSION_ID,
    format: "PDF",
    mime_type: "application/pdf",
    file_name: "artifact-slice-0428.pdf",
    storage_ref: "ae://artifacts/slice-0428/private-storage-ref.pdf",
    file_size_bytes: 4096,
    file_hash: "b".repeat(64),
    source_version_hash: "d".repeat(64)
  };
  return {
    ...record,
    current_version_id: EXPORT_ARTIFACT_VERSION_ID,
    target_formats: ["MD", "PDF"],
    versions: [
      ...record.versions,
      {
        artifact_version_id: EXPORT_ARTIFACT_VERSION_ID,
        version_no: 2,
        source_content_hash: "c".repeat(64),
        artifact_content_hash: "b".repeat(64),
        rendered_formats: ["PDF"]
      }
    ],
    files: [...record.files, pdfFile],
    links: [
      ...record.links,
      {
        artifact_file_id: PDF_ARTIFACT_FILE_ID,
        link_type: "download",
        link_route: `/api/v1/artifact-files/${PDF_ARTIFACT_FILE_ID}/download`,
        access_policy: "owner_only"
      }
    ]
  };
}

function exportPayload() {
  return {
    render_result_schema_version: "ae_markdown_render_result.v1",
    render_job: {
      render_job_id: "artifact-render-job-slice-0428-pdf",
      artifact_id: ARTIFACT_ID,
      artifact_version_id: EXPORT_ARTIFACT_VERSION_ID,
      job_status: "COMPLETED",
      current_stage: "FINALIZING",
      progress_percent: 100
    },
    artifact: exportedArtifactRecord()
  };
}

function previewPayload() {
  return {
    preview_schema_version: "ae_artifact_file_preview.v1",
    artifact_file: artifactRecord().files[0],
    artifact_link: artifactRecord().links[0],
    content_type: "text/markdown",
    text_preview: "# Artifact Slice 0417\n\nPreview text is safe to render.",
    truncated: false
  };
}

function downloadPayload() {
  return {
    download_schema_version: "ae_artifact_file_download.v1",
    artifact_file: artifactRecord().files[0],
    artifact_link: artifactRecord().links[1],
    download_file_name: "artifact-slice-0417.md",
    content_type: "text/markdown",
    content_hash: "f".repeat(64),
    content: RAW_DOWNLOAD_CONTENT
  };
}

function binaryDownloadPayload() {
  return {
    download_schema_version: "ae_artifact_file_download.v1",
    artifact_file: exportedArtifactRecord().files.at(-1),
    artifact_link: exportedArtifactRecord().links.at(-1),
    download_file_name: "artifact-slice-0428.pdf",
    content_type: "application/pdf",
    content_hash: "b".repeat(64),
    content_encoding: "base64",
    content_base64: RAW_BINARY_DOWNLOAD_CONTENT_BASE64
  };
}

function activeSession() {
  return {
    browser_session_schema_version: "oa_browser_session.v1",
    session_id: "session-slice-0417",
    status: "ACTIVE",
    issuer: "nex-oa",
    audience: "nex-ae-api",
    token_use: "user",
    tenant_ref: { type: "oa.tenant", id: "tenant-slice-0417" },
    subject_ref: { type: "oa.user", id: "user-slice-0417" },
    scopes: ["workspace:use", "documents:upload"],
    roles: ["employee"],
    issued_at: "2026-08-30T00:00:00Z",
    expires_at: "2026-08-30T01:00:00Z",
    auth_time: "2026-08-30T00:00:00Z",
    metadata: {
      raw_token_included: false,
      service_token_included: false,
      password_included: false,
      browser_payload_owner_authoritative: false,
      claim_owner_authoritative: true
    }
  };
}

function artifactRouteSequence(calls) {
  return (
    Array.isArray(calls) &&
    calls.map(call => `${call.method} ${call.url}`).join("|") ===
      [
        `GET /ae-api/api/v1/artifacts/${ARTIFACT_ID}`,
        `GET /ae-api/api/v1/artifacts/${ARTIFACT_ID}/versions`,
        `GET /ae-api/api/v1/artifact-files/${ARTIFACT_FILE_ID}`,
        `GET /ae-api/api/v1/artifact-files/${ARTIFACT_FILE_ID}/preview`,
        `GET /ae-api/api/v1/artifact-files/${ARTIFACT_FILE_ID}/download`,
        `POST /ae-api/api/v1/artifacts/${ARTIFACT_ID}/render-jobs`,
        `GET /ae-api/api/v1/artifact-files/${PDF_ARTIFACT_FILE_ID}`,
        `GET /ae-api/api/v1/artifact-files/${PDF_ARTIFACT_FILE_ID}/download`
      ].join("|") &&
    calls.every(call => call.credentials === "same-origin")
  );
}

function exportSubmitRouteMatches(calls) {
  const call = calls.find(item => item.method === "POST");
  return (
    call?.url === `/ae-api/api/v1/artifacts/${ARTIFACT_ID}/render-jobs` &&
    call.headers["Content-Type"] === "application/json" &&
    call.headers["Idempotency-Key"] === EXPORT_RENDER_REQUEST_ID &&
    call.body?.render_request_id_present === true &&
    Array.isArray(call.body?.target_formats) &&
    call.body.target_formats.join(",") === "PDF"
  );
}

function safeRequestObservationBody(body) {
  if (typeof body !== "string" || !body.trim()) return null;
  try {
    const payload = JSON.parse(body);
    return {
      render_request_id_present: typeof payload.render_request_id === "string",
      target_formats: Array.isArray(payload.target_formats)
        ? payload.target_formats.map(String)
        : []
    };
  } catch {
    return { parse_error: true, target_formats: [] };
  }
}

function jsonResponse({ ok = true, status = 200, payload }) {
  return {
    ok,
    status,
    async json() {
      return payload;
    }
  };
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().then(code => {
    process.exitCode = code;
  });
}
