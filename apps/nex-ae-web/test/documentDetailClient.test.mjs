import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION,
  DocumentDetailClientError,
  buildDocumentSurface,
  buildDocumentSurfaceFromProjection,
  createFetchDocumentDetailClient,
  createMockDocumentDetailClient,
  documentDetailRoute
} from "../src/documentDetailClient.js";

const sourceHash = "a".repeat(64);

function mockDocument(overrides = {}) {
  return {
    documentId: "doc-001",
    filename: "29_mvp_srs.md",
    projectionSchemaVersion: AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION,
    detailRoute: documentDetailRoute("doc-001"),
    ownerScope: {
      tenantId: "tenant-local",
      ownerUserId: "owner-local"
    },
    sourceService: "nex-cx",
    sourceKind: "postgres-read",
    processingStatus: "COMPLETED",
    extractionStatus: "COMPLETED",
    summaryStatus: "READY",
    confidenceBucket: "HIGH",
    bestScore: 0.91,
    ...overrides
  };
}

function aeProjection(overrides = {}) {
  return {
    projection_schema_version: AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION,
    service_id: "nex-ae-api",
    workspace_id: "workspace-local",
    tenant_id: "tenant-local",
    owner_user_id: "owner-local",
    document: {
      document_detail_schema_version: "ae_document_detail_item.v1",
      document_id: "doc-001",
      upload_handoff_id: "handoff-001",
      filename: "29_mvp_srs.md",
      content_type: "text/markdown",
      size_bytes: 128,
      source_sha256: sourceHash,
      status: {
        dedupe_status: "CREATED",
        extraction_status: "SUCCEEDED",
        markdown_available: true,
        summary_status: "SUCCEEDED",
        summary_embedding_status: "READY",
        processing_status: "SUCCEEDED"
      },
      summary: {
        summary_available: true,
        summary_text_sha256: sourceHash,
        summary_preview: "Safe summary preview.",
        summary_char_count: 21,
        summary_embedding_available: true,
        summary_embedding_model: "qwen3-embedding-4b-bf16",
        summary_embedding_dimension: 1024
      },
      processing: {
        available: true,
        latest_pipeline_run_id: "run-001",
        status: "SUCCEEDED",
        step_total: 4,
        step_failed: 0,
        updated_at: "2026-08-11T00:00:00Z"
      },
      source_lineage: {
        source_file_id: "source-001",
        source_sha256: sourceHash,
        content_type: "text/markdown",
        size_bytes: 128,
        storage_key_included: false,
        storage_uri_included: false,
        storage_path_included: false
      },
      links: {
        upload_handoff: "/api/v1/uploads/handoff-001",
        cx_document: "/api/v1/documents/doc-001",
        cx_summary: "/api/v1/documents/doc-001/summary",
        cx_summary_embedding: "/api/v1/documents/doc-001/summary-embedding",
        cx_processing: "/api/v1/documents/doc-001/processing"
      }
    },
    cx: {
      projection_schema_version: "cx_document_detail_projection.v1",
      document_detail_schema_version: "cx_document_detail_item.v1",
      source_kind: "postgres-read",
      owner_scoped: true,
      not_found_and_not_authorized_collapsed: true
    },
    metadata: {
      cx_storage_redacted: true,
      cx_detail_passthrough: false
    },
    ...overrides
  };
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

describe("document detail client adapters", () => {
  it("normalizes mock document detail without raw payload fields", async () => {
    const client = createMockDocumentDetailClient({
      documents: [mockDocument()]
    });

    const surface = await client.getDocumentDetail("doc-001");

    assert.equal(client.clientMode, "mock");
    assert.equal(surface.clientMode, "mock");
    assert.equal(surface.projectionSchemaVersion, AE_DOCUMENT_DETAIL_PROJECTION_SCHEMA_VERSION);
    assert.equal(surface.detailRoute, "/api/v1/documents/doc-001");
    assert.equal(surface.tenantId, "tenant-local");
    assert.equal(surface.ownerUserId, "owner-local");
    assert.equal(surface.sourceKind, "postgres-read");
    assert.equal(surface.bestScore, 0.91);
    assert.doesNotMatch(JSON.stringify(surface), /source_storage|storage_path|markdown_text/);
  });

  it("maps missing mock documents to a typed error", async () => {
    const client = createMockDocumentDetailClient({
      documents: [mockDocument()]
    });

    await assert.rejects(
      () => client.getDocumentDetail("missing"),
      error =>
        error instanceof DocumentDetailClientError &&
        error.status === "NOT_FOUND" &&
        error.retryable === false
    );
  });

  it("fetches and normalizes AE projection through the facade route", async () => {
    const calls = [];
    const client = createFetchDocumentDetailClient({
      baseUrl: "https://ae.local",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse({ payload: aeProjection() });
      }
    });

    const surface = await client.getDocumentDetail("doc 001");

    assert.equal(calls[0].url, "https://ae.local/api/v1/documents/doc%20001");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.headers.Accept, "application/json");
    assert.equal(surface.clientMode, "fetch");
    assert.equal(surface.processingStatus, "SUCCEEDED");
    assert.equal(surface.summaryStatus, "SUCCEEDED");
    assert.equal(surface.confidenceBucket, "READY");
  });

  it("maps failed fetch responses to a retry-aware typed error", async () => {
    const client = createFetchDocumentDetailClient({
      fetchImpl: async () =>
        jsonResponse({
          ok: false,
          status: 503,
          payload: {
            error_code: "ae.document_detail_unavailable",
            detail: "Temporarily unavailable.",
            retryable: true
          }
        })
    });

    await assert.rejects(
      () => client.getDocumentDetail("doc-001"),
      error =>
        error instanceof DocumentDetailClientError &&
        error.status === "ae.document_detail_unavailable" &&
        error.retryable === true
    );
  });

  it("maps network and projection failures to typed errors", async () => {
    const networkClient = createFetchDocumentDetailClient({
      fetchImpl: async () => {
        throw new Error("offline");
      }
    });
    await assert.rejects(
      () => networkClient.getDocumentDetail("doc-001"),
      error =>
        error instanceof DocumentDetailClientError &&
        error.status === "NETWORK_ERROR" &&
        error.retryable === true
    );

    assert.throws(
      () => buildDocumentSurfaceFromProjection({}, { clientMode: "fetch" }),
      error =>
        error instanceof DocumentDetailClientError &&
        error.status === "PROJECTION_INVALID"
    );
    assert.throws(
      () => buildDocumentSurface(null),
      error =>
        error instanceof DocumentDetailClientError &&
        error.status === "DOCUMENT_SURFACE_INVALID"
    );
  });
});
