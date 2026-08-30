import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION,
  ArtifactExportResultReadModelError,
  assertArtifactExportResultReadModelSafe,
  buildArtifactExportResultReadModel,
  buildArtifactExportResultSummary,
  findSensitiveArtifactExportResultReadModelKeys,
  renderArtifactExportResultReadModel
} from "../src/artifactExportResultReadModel.js";

const MAIN_SOURCE = readFileSync(
  new URL("../src/main.js", import.meta.url),
  "utf-8"
);
const STYLES_SOURCE = readFileSync(
  new URL("../src/styles.css", import.meta.url),
  "utf-8"
);

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
    const view = renderArtifactExportResultReadModel(model);
    const serialized = JSON.stringify({ model, summary, view });

    assert.equal(
      model.artifact_export_result_read_model_schema_version,
      AE_WEB_ARTIFACT_EXPORT_RESULT_READ_MODEL_SCHEMA_VERSION
    );
    assert.equal(model.status, "DOWNLOAD_READY");
    assert.equal(summary.downloadable_format_count, 2);
    assert.deepEqual(summary.downloadable_formats, ["MD", "PDF"]);
    assert.equal(summary.primary_download_format, "PDF");
    assert.equal(view.severity, "success");
    assert.doesNotMatch(view.summaryHtml, /<Report>/);
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
    const view = renderArtifactExportResultReadModel(model);
    const serialized = JSON.stringify({ model, summary, view });

    assert.equal(model.status, "SAVED");
    assert.equal(model.artifactVersionId, "artifact-version-002");
    assert.equal(summary.render_job_id, "render-job-001");
    assert.equal(summary.latest_save_status, "SAVED");
    assert.equal(summary.browser_save_available, true);
    assert.equal(summary.payload_kind, "base64");
    assert.equal(model.metadata.browserSaveAttempted, true);
    assert.equal(model.metadata.browserSaveSucceeded, true);
    assert.match(view.feedback, /generated-report.pdf/);
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
    assert.equal(renderArtifactExportResultReadModel(pending).severity, "running");
    assert.equal(failed.status, "UNAVAILABLE");
    assert.equal(renderArtifactExportResultReadModel(failed).severity, "danger");
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

  it("is wired into the artifact summary without raw download fields", () => {
    assert.match(MAIN_SOURCE, /artifactExportResult: null/);
    assert.match(MAIN_SOURCE, /refreshArtifactExportResult/);
    assert.match(MAIN_SOURCE, /renderArtifactExportResultReadModel/);
    assert.match(MAIN_SOURCE, /data-artifact-export-result-status/);
    assert.match(STYLES_SOURCE, /\.artifact-export-result/);
    assert.doesNotMatch(
      MAIN_SOURCE,
      /contentBase64|content_base64|storage_ref|database_url|provider_url|service_token|\/data\/nex-platform/
    );
  });
});
