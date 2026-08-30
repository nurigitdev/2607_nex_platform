import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION,
  assertArtifactDeliveryActionStateSafe,
  buildArtifactDeliveryActionRunningState,
  buildArtifactDeliveryActionSummary,
  buildArtifactDeliveryDownloadSuccess,
  buildArtifactDeliveryFailure,
  buildArtifactDeliveryPreviewSuccess,
  createArtifactDeliveryActionContext,
  findSensitiveArtifactDeliveryActionKeys
} from "../src/artifactDeliveryActionState.js";
import {
  AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION
} from "../src/artifactDownloadSaveAdapter.js";
import {
  createOperationState
} from "../src/operationState.js";

const MAIN_SOURCE = readFileSync(
  new URL("../src/main.js", import.meta.url),
  "utf-8"
);

function baseOperation() {
  return createOperationState({
    operationId: "artifact_preview",
    label: "Artifact preview/download",
    status: "READY",
    clientMode: "fetch",
    route: "/api/v1/artifact-files/file-0436/preview"
  });
}

function context(action = "download") {
  return createArtifactDeliveryActionContext({
    action,
    artifactId: "artifact-0436",
    route: `/api/v1/artifact-files/file-0436/${action}`,
    clientMode: "fetch"
  });
}

function artifactFile() {
  return {
    artifactId: "artifact-0436",
    artifactVersionId: "version-0436",
    artifactFileId: "file-0436",
    fileName: "delivery-report.md",
    format: "MD",
    mimeType: "text/markdown",
    fileHash: "hash-0436"
  };
}

function previewSurface() {
  return {
    artifactFile: artifactFile(),
    contentType: "text/markdown",
    textPreview: "# Safe preview",
    truncated: false,
    route: "/api/v1/artifact-files/file-0436/preview",
    clientMode: "fetch"
  };
}

function downloadSurface() {
  return {
    artifactFile: artifactFile(),
    downloadFileName: "delivery-report.md",
    contentType: "text/markdown",
    content: "# Safe download body",
    contentLength: 20,
    contentEncoding: "utf-8",
    downloadPayloadKind: "text",
    route: "/api/v1/artifact-files/file-0436/download",
    clientMode: "fetch"
  };
}

function savedResult() {
  return {
    artifact_download_save_schema_version:
      AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION,
    status: "SAVED",
    artifactId: "artifact-0436",
    artifactVersionId: "version-0436",
    artifactFileId: "file-0436",
    fileName: "delivery-report.md",
    contentType: "text/markdown",
    payloadKind: "text",
    contentEncoding: "utf-8",
    contentLength: 20,
    encodedContentLength: null,
    browserSaveRequired: true,
    metadata: {
      rawPromptIncluded: false,
      rawSourceIncluded: false,
      rawDownloadContentIncluded: false,
      rawBase64PayloadIncluded: false,
      browserServiceTokenIncluded: false,
      databaseEndpointIncluded: false,
      providerEndpointIncluded: false,
      storageLocationIncluded: false,
      blobCreated: true,
      objectUrlCreated: true,
      anchorClicked: true,
      objectUrlRevoked: true,
      browserSaveAvailable: true
    }
  };
}

describe("AE Web artifact delivery action state", () => {
  it("builds running and preview success state with safe summaries", () => {
    const running = buildArtifactDeliveryActionRunningState(
      baseOperation(),
      context("preview")
    );
    const preview = buildArtifactDeliveryPreviewSuccess(
      running.operation,
      previewSurface(),
      context("preview")
    );
    const summary = buildArtifactDeliveryActionSummary(preview);

    assert.equal(
      preview.artifact_delivery_action_state_schema_version,
      AE_WEB_ARTIFACT_DELIVERY_ACTION_STATE_SCHEMA_VERSION
    );
    assert.equal(running.operation.phase, "running");
    assert.equal(preview.operation.phase, "succeeded");
    assert.equal(preview.panel.status, "PREVIEW_READY");
    assert.equal(summary.status, "PREVIEW_READY");
    assert.equal(summary.action, "preview");
    assert.equal(summary.download_save_status, null);
  });

  it("builds download success state after save adapter execution", () => {
    const running = buildArtifactDeliveryActionRunningState(
      baseOperation(),
      context("download")
    );
    const download = buildArtifactDeliveryDownloadSuccess(
      running.operation,
      downloadSurface(),
      context("download"),
      { saveDownload: () => savedResult() }
    );
    const summary = buildArtifactDeliveryActionSummary(download);

    assert.equal(download.panel.status, "DOWNLOAD_READY");
    assert.equal(download.downloadSaveSummary.status, "SAVED");
    assert.equal(download.operation.resultStatus, "SAVED");
    assert.equal(summary.download_save_status, "SAVED");
    assert.equal(summary.retryable, false);
  });

  it("keeps failure and retry state explicit without raw error details", () => {
    const error = new Error("hidden database_url should not be serialized");
    error.status = "ARTIFACT_DOWNLOAD_TIMEOUT";
    error.retryable = true;

    const failed = buildArtifactDeliveryFailure(
      baseOperation(),
      error,
      context("download")
    );
    const summary = buildArtifactDeliveryActionSummary(failed);
    const serialized = JSON.stringify(failed);

    assert.equal(failed.status, "UNAVAILABLE");
    assert.equal(failed.downloadSaveResult, null);
    assert.equal(summary.error_status, "ARTIFACT_DOWNLOAD_TIMEOUT");
    assert.equal(summary.retryable, true);
    assert.doesNotMatch(serialized, /database_url|hidden/);
  });

  it("validates action context, route action, schema, and safety branches", () => {
    assert.throws(
      () => createArtifactDeliveryActionContext({ action: "delete", route: "/x" }),
      /unsupported/
    );
    assert.throws(
      () =>
        createArtifactDeliveryActionContext({
          action: "preview",
          route: "/api/v1/artifact-files/file-0436/download"
        }),
      /does not match/
    );
    assert.throws(
      () => buildArtifactDeliveryActionSummary({}),
      /invalid/
    );
    assert.deepEqual(
      findSensitiveArtifactDeliveryActionKeys({
        nested: { service_token: "secret" }
      }),
      ["nested.service_token"]
    );
    assert.throws(
      () =>
        assertArtifactDeliveryActionStateSafe({
          safe: false,
          route: "postgresql+psycopg://nex_ae_user:nuri1004@127.0.0.1:5432/nex"
        }),
      /sensitive values/
    );
  });

  it("keeps main artifact delivery wiring delegated to the action state module", () => {
    assert.match(MAIN_SOURCE, /from "\.\/artifactDeliveryActionState\.js"/);
    assert.match(MAIN_SOURCE, /buildArtifactDeliveryActionRunningState/);
    assert.match(MAIN_SOURCE, /buildArtifactDeliveryDownloadSuccess/);
    assert.match(MAIN_SOURCE, /buildArtifactDeliveryFailure/);
    assert.match(MAIN_SOURCE, /applyArtifactDeliveryActionState/);
    assert.doesNotMatch(
      MAIN_SOURCE,
      /saveArtifactDownload\(download\)|contentBase64|database_url|service_token/
    );
  });
});
