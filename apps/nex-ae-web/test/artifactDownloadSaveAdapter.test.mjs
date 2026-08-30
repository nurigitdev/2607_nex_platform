import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION,
  ArtifactDownloadSaveError,
  assertArtifactDownloadSaveResultSafe,
  buildArtifactDownloadSavePlan,
  buildArtifactDownloadSaveSummary,
  createArtifactDownloadBlob,
  findSensitiveArtifactDownloadSaveKeys,
  sanitizeDownloadFileName,
  saveArtifactDownload
} from "../src/artifactDownloadSaveAdapter.js";

function textDownloadSurface(overrides = {}) {
  return {
    downloadSchemaVersion: "ae_artifact_file_download.v1",
    artifactFile: {
      artifactFileId: "artifact-file-md-001",
      artifactId: "artifact-001",
      artifactVersionId: "artifact-version-001",
      format: "MD",
      mimeType: "text/markdown",
      fileName: "generated-report.md",
      fileHash: "f".repeat(64)
    },
    downloadFileName: "../unsafe/generated-report.md",
    contentType: "text/markdown",
    contentHash: "f".repeat(64),
    content: "# Generated report\n\nPrivate body",
    contentEncoding: "utf-8",
    downloadPayloadKind: "text",
    contentLength: 32,
    encodedContentLength: null,
    ...overrides
  };
}

function binaryDownloadSurface(overrides = {}) {
  return textDownloadSurface({
    artifactFile: {
      artifactFileId: "artifact-file-pdf-001",
      artifactId: "artifact-001",
      artifactVersionId: "artifact-version-001",
      format: "PDF",
      mimeType: "application/pdf",
      fileName: "generated-report.pdf",
      fileHash: "b".repeat(64)
    },
    downloadFileName: "generated-report.pdf",
    contentType: "application/pdf",
    contentHash: "b".repeat(64),
    content: null,
    contentBase64: "JVBERi0xLjQKJQ==",
    contentEncoding: "base64",
    downloadPayloadKind: "base64",
    contentLength: 10,
    encodedContentLength: 16,
    ...overrides
  });
}

class FakeBlob {
  constructor(parts, options = {}) {
    this.parts = parts;
    this.type = options.type || "";
    this.size = parts.reduce((total, part) => {
      if (typeof part === "string") return total + part.length;
      if (part instanceof Uint8Array) return total + part.byteLength;
      return total;
    }, 0);
  }
}

function fakeBrowser() {
  const calls = [];
  const body = {
    appendChild(anchor) {
      calls.push(["append", anchor.download]);
    },
    removeChild(anchor) {
      calls.push(["remove", anchor.download]);
    }
  };
  return {
    calls,
    documentRef: {
      body,
      createElement(tagName) {
        calls.push(["create", tagName]);
        return {
          tagName,
          style: {},
          click() {
            calls.push(["click", this.download]);
          }
        };
      }
    },
    urlRef: {
      createObjectURL(blob) {
        calls.push(["object-url", blob.type, blob.size]);
        return "blob://artifact-download";
      },
      revokeObjectURL(url) {
        calls.push(["revoke", url]);
      }
    }
  };
}

describe("AE Web artifact download save adapter", () => {
  it("builds browser-safe save plans without raw download content", () => {
    const plan = buildArtifactDownloadSavePlan(textDownloadSurface());
    const serialized = JSON.stringify(plan);

    assert.equal(
      plan.artifact_download_save_schema_version,
      AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION
    );
    assert.equal(plan.status, "READY");
    assert.equal(plan.fileName, "generated-report.md");
    assert.equal(plan.payloadKind, "text");
    assert.equal(plan.contentEncoding, "utf-8");
    assert.equal(plan.contentLength, 32);
    assert.equal(plan.metadata.rawDownloadContentIncluded, false);
    assert.doesNotMatch(serialized, /Private body|contentBase64|storage_ref/);
  });

  it("creates a text blob and clicks a temporary browser anchor", () => {
    const browser = fakeBrowser();
    const result = saveArtifactDownload(textDownloadSurface(), {
      BlobCtor: FakeBlob,
      documentRef: browser.documentRef,
      urlRef: browser.urlRef
    });
    const summary = buildArtifactDownloadSaveSummary(result);

    assert.equal(result.status, "SAVED");
    assert.equal(summary.status, "SAVED");
    assert.equal(summary.file_name, "generated-report.md");
    assert.equal(summary.browser_save_available, true);
    assert.equal(summary.blob_created, true);
    assert.equal(summary.object_url_created, true);
    assert.equal(summary.anchor_clicked, true);
    assert.equal(summary.object_url_revoked, true);
    assert.deepEqual(browser.calls, [
      ["object-url", "text/markdown", 32],
      ["create", "a"],
      ["append", "generated-report.md"],
      ["click", "generated-report.md"],
      ["remove", "generated-report.md"],
      ["revoke", "blob://artifact-download"]
    ]);
  });

  it("creates a binary PDF blob from base64 without leaking the encoded payload", () => {
    const { blob, plan } = createArtifactDownloadBlob(binaryDownloadSurface(), {
      BlobCtor: FakeBlob
    });
    const result = saveArtifactDownload(binaryDownloadSurface(), {
      BlobCtor: FakeBlob,
      documentRef: null,
      urlRef: null
    });
    const serialized = JSON.stringify({ plan, result });

    assert.equal(blob.type, "application/pdf");
    assert.equal(blob.size, 10);
    assert.equal(plan.payloadKind, "base64");
    assert.equal(plan.contentLength, 10);
    assert.equal(plan.encodedContentLength, 16);
    assert.equal(result.status, "PREPARED");
    assert.equal(buildArtifactDownloadSaveSummary(result).browser_save_available, false);
    assert.doesNotMatch(serialized, /JVBERi0xLjQKJQ==|contentBase64/);
  });

  it("sanitizes unsafe filenames and appends known extensions when missing", () => {
    assert.equal(
      sanitizeDownloadFileName("..\\folder/report:name", {
        contentType: "application/pdf"
      }),
      "report-name.pdf"
    );
    assert.equal(
      sanitizeDownloadFileName("\u0000\n", { fallback: "artifact" }),
      "artifact"
    );
    assert.equal(
      sanitizeDownloadFileName("x".repeat(200)).length,
      160
    );
  });

  it("rejects invalid download surfaces and unsupported browser primitives", () => {
    assert.throws(
      () => buildArtifactDownloadSavePlan({}),
      error =>
        error instanceof ArtifactDownloadSaveError &&
        error.status === "DOWNLOAD_SURFACE_INVALID"
    );
    assert.throws(
      () =>
        buildArtifactDownloadSavePlan(
          textDownloadSurface({ downloadPayloadKind: "stream" })
        ),
      error =>
        error instanceof ArtifactDownloadSaveError &&
        error.status === "DOWNLOAD_PAYLOAD_KIND_UNSUPPORTED"
    );
    assert.throws(
      () =>
        buildArtifactDownloadSavePlan(
          textDownloadSurface({ content: undefined })
        ),
      error =>
        error instanceof ArtifactDownloadSaveError &&
        error.status === "DOWNLOAD_TEXT_CONTENT_MISSING"
    );
    assert.throws(
      () =>
        createArtifactDownloadBlob(
          binaryDownloadSurface({ contentBase64: "not-base64" }),
          { BlobCtor: FakeBlob }
        ),
      error =>
        error instanceof ArtifactDownloadSaveError &&
        error.status === "DOWNLOAD_BASE64_CONTENT_INVALID"
    );
    assert.throws(
      () => createArtifactDownloadBlob(textDownloadSurface(), { BlobCtor: null }),
      error =>
        error instanceof ArtifactDownloadSaveError &&
        error.status === "BLOB_UNAVAILABLE"
    );
  });

  it("guards save summaries from raw payload keys and sensitive values", () => {
    assert.deepEqual(
      findSensitiveArtifactDownloadSaveKeys({
        metadata: { raw_payload: "hidden" },
        safe: true
      }),
      ["metadata.raw_payload"]
    );
    assert.throws(
      () => buildArtifactDownloadSaveSummary({}),
      error =>
        error instanceof ArtifactDownloadSaveError &&
        error.status === "DOWNLOAD_SAVE_RESULT_INVALID"
    );
    assert.throws(
      () =>
        assertArtifactDownloadSaveResultSafe({
          artifact_download_save_schema_version:
            AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION,
          contentBase64: "leak"
        }),
      error =>
        error instanceof ArtifactDownloadSaveError &&
        error.status === "DOWNLOAD_SAVE_RESULT_SENSITIVE_KEY"
    );
    assert.throws(
      () =>
        assertArtifactDownloadSaveResultSafe({
          artifact_download_save_schema_version:
            AE_WEB_ARTIFACT_DOWNLOAD_SAVE_SCHEMA_VERSION,
          fileName: "/data/nex-platform/ae/leak.pdf"
        }),
      error =>
        error instanceof ArtifactDownloadSaveError &&
        error.status === "DOWNLOAD_SAVE_RESULT_SENSITIVE_VALUE"
    );
  });
});
