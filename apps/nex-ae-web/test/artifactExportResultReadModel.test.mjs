import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION,
  ArtifactExportResultReadModelError,
  assertArtifactExportResultReadModelSafe,
  buildArtifactExportResultReadModel,
  buildArtifactExportResultSummary,
  findSensitiveArtifactExportResultReadModelKeys
} from "../src/artifactExportResultReadModel.js";

function artifactRef(overrides = {}) {
  return {
    artifactId: "artifact-001",
    artifactVersionId: "artifact-version-001",
    displayTitle: "Generated <Report>",
    artifactStatus: "READY",
    primaryFormat: "PDF",
    availableFormats: ["MD", "PDF"],
    downloadRoutes: {
      MD: "/api/v1/artifact-files/artifact-file-md-001/download",
      PDF: "/api/v1/artifact-files/artifact-file-pdf-001/download"
    },
    ...overrides
  };
}

function exportSurface(overrides = {}) {
  return {
    artifactId: "artifact-001",
    artifactVersionId: "artifact-version-002",
    renderJobId: "render-job-001",
    jobStatus: "COMPLETED",
    currentStage: "COMPLETED",
    requestedFormats: ["PDF"],
    renderedFormats: ["MD", "PDF"],
    artifactSurface: {
      artifactId: "artifact-001",
      artifactVersionId: "artifact-version-002",
      displayTitle: "Generated <Report>",
      availableFormats: ["MD", "PDF"],
      downloadRoutes: {
        MD: "/api/v1/artifact-files/artifact-file-md-001/download",
        PDF: "/api/v1/artifact-files/artifact-file-pdf-001/download"
      },
      clientMode: "fetch"
    },
    clientMode: "fetch",
    ...overrides
  };
}

function saveSummary(overrides = {}) {
  return {
    status: "SAVED",
    file_name: "generated-report.pdf",
    content_type: "application/pdf",
    payload_kind: "base64",
    browser_save_available: true,
    metadata: {
      rawDownloadContentIncluded: false,
      rawBase64PayloadIncluded: false
    },
    ...overrides
  };
}

describe("AE Web artifact export result read-model", () => {
  it("builds a safe download-ready read-model from an artifact ref", () => {
    const model = buildArtifactExportResultReadModel({ artifactRef: artifactRef() });
    const summary = buildArtifactExportResultSummary(model);
    const serialized = JSON.stringify({ model, summary });

    assert.equal(
      model.artifact_export_result_read_model_schema_version,
      AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION
    );
    assert.equal(model.status, "DOWNLOAD_READY");
    assert.equal(summary.downloadable_format_count, 2);
    assert.deepEqual(summary.downloadable_formats, ["MD", "PDF"]);
    assert.equal(summary.primary_download_format, "PDF");
    assert.doesNotMatch(
      serialized,
      /storage_ref|database_url|provider_url|service_token|contentBase64|JVBERi0xLjQKJQ==/
    );
  });

  it("combines export result and save summary without carrying raw routes", () => {
    const model = buildArtifactExportResultReadModel({
      artifactRef: artifactRef(),
      exportSurface: exportSurface(),
      downloadSaveSummary: saveSummary()
    });
    const summary = buildArtifactExportResultSummary(model);
    const serialized = JSON.stringify({ model, summary });

    assert.equal(model.status, "SAVED");
    assert.equal(model.artifactVersionId, "artifact-version-002");
    assert.equal(summary.render_job_id, "render-job-001");
    assert.equal(summary.latest_save_status, "SAVED");
    assert.equal(summary.browser_save_available, true);
    assert.equal(summary.payload_kind, "base64");
    assert.equal(model.metadata.browserSaveAttempted, true);
    assert.equal(model.metadata.browserSaveSucceeded, true);
    assert.doesNotMatch(serialized, /\/api\/v1\/artifact-files/);
  });

  it("distinguishes pending exports, failed exports, and prepared saves", () => {
    const pending = buildArtifactExportResultReadModel({
      artifactRef: artifactRef({ downloadRoutes: {} }),
      exportSurface: exportSurface({
        jobStatus: "RUNNING",
        currentStage: "PDF_RENDERING",
        renderedFormats: []
      })
    });
    const failed = buildArtifactExportResultReadModel({
      artifactRef: artifactRef({ artifactStatus: "FAILED", downloadRoutes: {} })
    });
    const prepared = buildArtifactExportResultReadModel({
      artifactRef: artifactRef(),
      downloadSaveSummary: saveSummary({
        status: "PREPARED",
        browser_save_available: false
      })
    });

    assert.equal(pending.status, "EXPORT_PENDING");
    assert.equal(failed.status, "UNAVAILABLE");
    assert.equal(prepared.status, "DOWNLOAD_READY");
    assert.equal(prepared.metadata.browserSaveAttempted, true);
    assert.equal(prepared.metadata.browserSaveSucceeded, false);
  });

  it("rejects invalid models and sensitive keys or values", () => {
    assert.throws(
      () => buildArtifactExportResultSummary({}),
      error =>
        error instanceof ArtifactExportResultReadModelError &&
        error.status === "ARTIFACT_EXPORT_RESULT_SCHEMA_INVALID"
    );
    assert.throws(
      () =>
        buildArtifactExportResultSummary({
          artifact_export_result_read_model_schema_version:
            AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION,
          status: "DONE"
        }),
      error =>
        error instanceof ArtifactExportResultReadModelError &&
        error.status === "ARTIFACT_EXPORT_RESULT_STATUS_UNSUPPORTED"
    );
    assert.deepEqual(
      findSensitiveArtifactExportResultReadModelKeys({
        nested: { raw_payload: "hidden" }
      }),
      ["nested.raw_payload"]
    );
    assert.throws(
      () =>
        assertArtifactExportResultReadModelSafe({
          artifact_export_result_read_model_schema_version:
            AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION,
          storage_ref: "ae://artifacts/private"
        }),
      error =>
        error instanceof ArtifactExportResultReadModelError &&
        error.status === "ARTIFACT_EXPORT_RESULT_SENSITIVE_KEY"
    );
    assert.throws(
      () =>
        assertArtifactExportResultReadModelSafe({
          artifact_export_result_read_model_schema_version:
            AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION,
          fileName: "/data/nex-platform/ae/private.pdf"
        }),
      error =>
        error instanceof ArtifactExportResultReadModelError &&
        error.status === "ARTIFACT_EXPORT_RESULT_SENSITIVE_VALUE"
    );
  });
});
