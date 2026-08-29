import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildArtifactSurfaceFromRecord,
  createMockArtifactClient
} from "../src/artifactClient.js";
import {
  buildMockArtifactRecordFromRef,
  fileNameForArtifactFormat,
  mimeTypeForArtifactFormat,
  safeArtifactFileIdFromRoute
} from "../src/artifactMockRecord.js";

function artifactRef(overrides = {}) {
  return {
    artifactId: "artifact-001",
    artifactVersionId: "artifact-version-001",
    displayTitle: "Generated report",
    artifactType: "generated_document",
    artifactStatus: "READY",
    primaryFormat: "MD",
    availableFormats: ["MD"],
    previewRoute: "/api/v1/artifact-files/artifact-file-001/preview",
    downloadRoutes: {
      MD: "/api/v1/artifact-files/artifact-file-001/download"
    },
    sourceGenerationId: "cx-gen-001",
    sourceContentHash: "c".repeat(64),
    qualitySummary: {
      citationStatus: "VALIDATED",
      citationCount: 2,
      evidenceRefCount: 2,
      groundingRequired: true
    },
    ...overrides
  };
}

describe("AE Web mock artifact records", () => {
  it("builds artifact-client-compatible records from browser artifact refs", async () => {
    const record = buildMockArtifactRecordFromRef(artifactRef(), {
      chatDocumentId: "chat-doc-001",
      interactionId: "interaction-001",
      cxGenerationId: "cx-gen-fallback"
    });
    const surface = buildArtifactSurfaceFromRecord(record);
    const client = createMockArtifactClient({ artifacts: [record] });
    const preview = await client.previewArtifactFile("artifact-file-001");
    const download = await client.downloadArtifactFile("artifact-file-001");

    assert.equal(record.artifact_id, "artifact-001");
    assert.equal(record.chat_document_id, "chat-doc-001");
    assert.equal(record.interaction_id, "interaction-001");
    assert.equal(record.files.length, 1);
    assert.equal(record.links.length, 2);
    assert.equal(surface.previewRoute, "/api/v1/artifact-files/artifact-file-001/preview");
    assert.equal(preview.artifactFile.fileName, "generated-artifact.md");
    assert.equal(download.downloadFileName, "generated-artifact.md");
    assert.doesNotMatch(
      JSON.stringify(record),
      /storage_ref|storage_path|service_token|database_url|provider_url|\/data\/nex-platform/
    );
  });

  it("adds additional download files when routes point to different file ids", () => {
    const record = buildMockArtifactRecordFromRef(
      artifactRef({
        availableFormats: ["MD", "HTML_PREVIEW"],
        downloadRoutes: {
          MD: "/api/v1/artifact-files/artifact-file-001/download",
          HTML_PREVIEW: "/api/v1/artifact-files/artifact-file-html/download"
        }
      })
    );

    assert.deepEqual(record.target_formats, ["MD", "HTML_PREVIEW"]);
    assert.equal(record.files.length, 2);
    assert.equal(record.files[1].artifact_file_id, "artifact-file-html");
    assert.equal(record.files[1].mime_type, "text/html");
    assert.equal(record.files[1].file_name, "generated-artifact.html");
  });

  it("falls back safely for missing or malformed preview routes", () => {
    const record = buildMockArtifactRecordFromRef(
      artifactRef({
        previewRoute: "/api/v1/artifacts/not-a-file",
        downloadRoutes: {}
      })
    );

    assert.equal(safeArtifactFileIdFromRoute(null, "preview"), null);
    assert.equal(
      safeArtifactFileIdFromRoute("/api/v1/artifacts/not-a-file", "preview"),
      null
    );
    assert.equal(record.files[0].artifact_file_id, "artifact-file-local-001");
    assert.equal(record.links.length, 0);
  });

  it("normalizes common artifact format names", () => {
    assert.equal(mimeTypeForArtifactFormat("HTML_PREVIEW"), "text/html");
    assert.equal(mimeTypeForArtifactFormat("PDF"), "application/pdf");
    assert.equal(mimeTypeForArtifactFormat("JSON"), "application/json");
    assert.equal(mimeTypeForArtifactFormat("MD"), "text/markdown");
    assert.equal(fileNameForArtifactFormat("HTML_PREVIEW"), "generated-artifact.html");
  });
});
