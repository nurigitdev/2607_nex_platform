import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION,
  AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION,
  buildArtifactDownloadSurface,
  buildArtifactPreviewSurface
} from "../src/artifactClient.js";
import {
  AE_WEB_ARTIFACT_PREVIEW_PANEL_SCHEMA_VERSION,
  ArtifactPreviewPanelError,
  artifactFileIdFromRoute,
  assertArtifactPreviewPanelSafe,
  buildArtifactPreviewPanelStateFromDownload,
  buildArtifactPreviewPanelStateFromError,
  buildArtifactPreviewPanelStateFromPreview,
  buildArtifactPreviewPanelSummary,
  createArtifactPreviewPanelState,
  createRunningArtifactPreviewPanelState,
  findSensitiveArtifactPreviewPanelKeys,
  renderArtifactPreviewPanel
} from "../src/artifactPreviewPanel.js";

function artifactFile(overrides = {}) {
  return {
    artifact_file_id: "artifact-file-001",
    artifact_id: "artifact-001",
    artifact_version_id: "artifact-version-001",
    format: "MD",
    mime_type: "text/markdown",
    file_name: "generated-report.md",
    file_size_bytes: 512,
    file_hash: "f".repeat(64),
    ...overrides
  };
}

function artifactLink(type = "preview", overrides = {}) {
  return {
    artifact_link_id: `artifact-link-${type}-001`,
    artifact_file_id: "artifact-file-001",
    link_type: type,
    access_policy: "owner_only",
    link_route: `/api/v1/artifact-files/artifact-file-001/${type}`,
    ...overrides
  };
}

function previewSurface(overrides = {}) {
  return buildArtifactPreviewSurface(
    {
      preview_schema_version: AE_ARTIFACT_FILE_PREVIEW_SCHEMA_VERSION,
      artifact_file: artifactFile(),
      artifact_link: artifactLink("preview"),
      content_type: "text/markdown",
      text_preview: "# Preview\n\n본문 <script>alert(1)</script>",
      truncated: false,
      ...overrides
    },
    {
      clientMode: "mock",
      route: "/api/v1/artifact-files/artifact-file-001/preview"
    }
  );
}

function downloadSurface(overrides = {}) {
  return buildArtifactDownloadSurface(
    {
      download_schema_version: AE_ARTIFACT_FILE_DOWNLOAD_SCHEMA_VERSION,
      artifact_file: artifactFile(),
      artifact_link: artifactLink("download"),
      download_file_name: "generated-report.md",
      content_type: "text/markdown",
      content_hash: "f".repeat(64),
      content: "downloaded artifact body must stay out of panel state",
      ...overrides
    },
    {
      clientMode: "mock",
      route: "/api/v1/artifact-files/artifact-file-001/download"
    }
  );
}

describe("AE Web artifact preview/download panel", () => {
  it("parses artifact file ids from protected preview and download routes", () => {
    assert.equal(
      artifactFileIdFromRoute("/api/v1/artifact-files/artifact-file-001/preview", "preview"),
      "artifact-file-001"
    );
    assert.equal(
      artifactFileIdFromRoute("/api/v1/artifact-files/artifact%20file/download", "download"),
      "artifact file"
    );
    assert.throws(
      () => artifactFileIdFromRoute("/api/v1/artifact-files/artifact-file-001/download", "preview"),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_FILE_ROUTE_ACTION_MISMATCH"
    );
    assert.throws(
      () => artifactFileIdFromRoute("https://example.test/file"),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_ROUTE_INVALID"
    );
    assert.throws(
      () => artifactFileIdFromRoute("/api/v1/artifacts/artifact-001"),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_FILE_ROUTE_INVALID"
    );
    assert.throws(
      () => artifactFileIdFromRoute("/api/v1/artifact-files/%E0%A4%A/preview"),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_FILE_ROUTE_ENCODING_INVALID"
    );
  });

  it("creates idle and running states with browser-safe summaries", () => {
    const idle = createArtifactPreviewPanelState({ clientMode: "mock" });
    const running = createRunningArtifactPreviewPanelState({
      action: "preview",
      artifactId: "artifact-001",
      artifactFileId: "artifact-file-001",
      route: "/api/v1/artifact-files/artifact-file-001/preview",
      clientMode: "mock"
    });

    assert.equal(
      idle.artifact_preview_panel_schema_version,
      AE_WEB_ARTIFACT_PREVIEW_PANEL_SCHEMA_VERSION
    );
    assert.equal(buildArtifactPreviewPanelSummary(idle).status, "READY");
    assert.equal(running.status, "RUNNING");
    assert.equal(renderArtifactPreviewPanel(running).severity, "running");
    assert.doesNotMatch(
      JSON.stringify(buildArtifactPreviewPanelSummary(running)),
      /service_token|database_url|provider_url|storage_ref|\/data\/nex-platform/
    );
  });

  it("builds preview-ready panel state and escaped summary html", () => {
    const state = buildArtifactPreviewPanelStateFromPreview(previewSurface(), {
      artifactId: "artifact-001"
    });
    const summary = buildArtifactPreviewPanelSummary(state);
    const view = renderArtifactPreviewPanel(state);

    assert.equal(state.status, "PREVIEW_READY");
    assert.equal(summary.file_name, "generated-report.md");
    assert.equal(summary.truncated, false);
    assert.match(view.bodyText, /본문 <script>/);
    assert.doesNotMatch(view.summaryHtml, /<script>/);
    assert.equal(view.metadata.contentRendered, true);
    assert.equal(view.metadata.downloadedContentRendered, false);
  });

  it("keeps downloaded content out of panel state, summary, and view", () => {
    const state = buildArtifactPreviewPanelStateFromDownload(downloadSurface(), {
      artifactId: "artifact-001"
    });
    const summary = buildArtifactPreviewPanelSummary(state);
    const view = renderArtifactPreviewPanel(state);
    const serialized = JSON.stringify({ state, summary, view });

    assert.equal(state.status, "DOWNLOAD_READY");
    assert.equal(summary.content_hash_present, true);
    assert.equal(summary.content_length, 53);
    assert.match(view.bodyText, /Downloaded content is not rendered/);
    assert.doesNotMatch(serialized, /downloaded artifact body/);
    assert.equal(state.metadata.downloadedContentRendered, false);
    assert.equal(view.metadata.downloadedContentRendered, false);
  });

  it("normalizes failures as retryable unavailable states", () => {
    const error = new Error("offline");
    error.status = "NETWORK_ERROR";
    error.retryable = true;
    const state = buildArtifactPreviewPanelStateFromError(error, {
      action: "download",
      artifactId: "artifact-001",
      artifactFileId: "artifact-file-001",
      route: "/api/v1/artifact-files/artifact-file-001/download",
      clientMode: "fetch"
    });
    const view = renderArtifactPreviewPanel(state);

    assert.equal(state.status, "UNAVAILABLE");
    assert.equal(state.retryable, true);
    assert.equal(buildArtifactPreviewPanelSummary(state).client_mode, "fetch");
    assert.equal(view.severity, "danger");
    assert.match(view.bodyText, /NETWORK_ERROR/);
  });

  it("rejects unsupported states and unsafe payloads", () => {
    assert.throws(
      () => createArtifactPreviewPanelState({ status: "DONE" }),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_PREVIEW_STATUS_UNSUPPORTED"
    );
    assert.throws(
      () => createArtifactPreviewPanelState({ action: "open" }),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_PREVIEW_ACTION_UNSUPPORTED"
    );
    assert.throws(
      () => createArtifactPreviewPanelState({
        status: "DOWNLOAD_READY",
        action: "download",
        download: { contentLength: -1 }
      }),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_DOWNLOAD_LENGTH_INVALID"
    );
    assert.throws(
      () => buildArtifactPreviewPanelSummary({}),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_PREVIEW_PANEL_SCHEMA_INVALID"
    );
    assert.deepEqual(
      findSensitiveArtifactPreviewPanelKeys({
        nested: { storage_ref: "hidden" },
        metadata: { rawPromptRendered: false }
      }),
      ["nested.storage_ref"]
    );
    assert.throws(
      () => assertArtifactPreviewPanelSafe({ safe: "/data/nex-platform/cx/source-files" }),
      error =>
        error instanceof ArtifactPreviewPanelError &&
        error.status === "ARTIFACT_PREVIEW_PANEL_SENSITIVE_VALUE"
    );
  });
});
