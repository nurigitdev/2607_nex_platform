import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildDocumentScope,
  buildRetrievalRequest
} from "../src/documentScope.js";
import {
  AE_WEB_FETCH_MODE_HARNESS_SCHEMA_VERSION,
  FetchModeHarnessError,
  runFetchModeHarness
} from "../src/fetchModeHarness.js";
import {
  buildUploadOwnershipRef,
  buildUploadSurfaceDraft
} from "../src/uploadSurface.js";

const sourceSha256 = "d12261539d27dcab69f873a5e1a30587919b8ce4802782151f1bc2ba5390b610";

function documents() {
  return [
    {
      documentId: "doc-001",
      filename: "29_mvp_srs.md",
      detailRoute: "/api/v1/documents/doc-001",
      ownerScope: {
        tenantId: "tenant-local",
        ownerUserId: "owner-local"
      },
      sourceKind: "postgres-read",
      processingStatus: "COMPLETED",
      summaryStatus: "READY",
      confidenceBucket: "HIGH"
    }
  ];
}

function uploadDraft() {
  return buildUploadSurfaceDraft({
    workspaceId: "workspace-local",
    filename: "new-reference-pack.md",
    contentType: "text/markdown",
    sizeBytes: 4096,
    sourceSha256,
    ownerScope: {
      tenantId: "tenant-local",
      ownerUserId: "owner-local",
      uploadedByUserId: "owner-local"
    }
  });
}

function retrievalRequest() {
  const scope = buildDocumentScope({
    documents: documents(),
    selectedDocumentIds: ["doc-001"]
  });
  return buildRetrievalRequest({
    userMessage: "Find selected evidence",
    chatDocumentId: "chat-doc-local",
    documentScope: scope,
    grounded: true,
    topK: 4
  });
}

function createFakeFetch() {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url === "/ae-api/api/v1/documents/doc-001") {
      return jsonResponse({
        payload: {
          projection_schema_version: "ae_document_detail_projection.v1",
          tenant_id: "tenant-local",
          owner_user_id: "owner-local",
          document: {
            document_id: "doc-001",
            filename: "29_mvp_srs.md",
            status: {
              processing_status: "SUCCEEDED",
              extraction_status: "SUCCEEDED",
              summary_status: "SUCCEEDED"
            },
            summary: {
              summary_available: true
            }
          },
          cx: {
            source_kind: "ae-facade"
          }
        }
      });
    }
    if (url === "/ae-api/api/v1/uploads") {
      const body = JSON.parse(options.body);
      return jsonResponse({
        payload: {
          upload_handoff_schema_version: "ae_upload_handoff.v1",
          upload_handoff_id: "handoff-001",
          workspace_id: body.workspace_id,
          tenant_id: body.tenant_id,
          owner_user_id: body.owner_user_id,
          ownership_ref: buildUploadOwnershipRef({
            tenantId: body.tenant_id,
            ownerUserId: body.owner_user_id,
            uploadedByUserId: body.uploaded_by_user_id
          }),
          status: "QUEUED",
          dedupe: {
            status: "CREATED"
          },
          source: {
            filename: body.filename,
            content_type: body.content_type,
            size_bytes: body.size_bytes,
            source_sha256: body.source_sha256
          },
          cx_document_ref: {
            document_id: "doc-upload-001"
          }
        }
      });
    }
    if (url === "/ae-api/api/v1/retrieval/contexts") {
      const body = JSON.parse(options.body);
      return jsonResponse({
        payload: {
          retrieval_interaction_schema_version: "ae_retrieval_interaction.v1",
          retrieval_interaction_id: "ret-001",
          chat_document_id: body.chat_document_id,
          status: "COMPLETED",
          trace_id: "trace-local",
          request_id: "request-local",
          user_message_hash: "f".repeat(64),
          cx_retrieval_package_id: "cx-ret-001",
          cx_package_hash: "d".repeat(64),
          cx_status: "READY",
          purpose: body.retrieval.purpose,
          retrieval: {
            evidence_count: 2,
            best_score: 0.91,
            confidence_bucket: "READY",
            no_answer_reason: null,
            warnings: []
          }
        }
      });
    }

    return jsonResponse({
      ok: false,
      status: 404,
      payload: {
        error_code: "ae.fake_route_not_found",
        detail: "Fake route not found."
      }
    });
  };
  fetchImpl.calls = calls;
  return fetchImpl;
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

describe("AE Web fetch mode regression harness", () => {
  it("runs document detail, upload, and retrieval fetch clients through fake fetch", async () => {
    const fetchImpl = createFakeFetch();

    const result = await runFetchModeHarness({
      baseUrl: "/ae-api/",
      fetchImpl,
      documents: documents(),
      uploadDraft: uploadDraft(),
      retrievalRequest: retrievalRequest()
    });

    assert.equal(
      result.fetch_mode_harness_schema_version,
      AE_WEB_FETCH_MODE_HARNESS_SCHEMA_VERSION
    );
    assert.equal(result.client_mode, "fetch");
    assert.equal(result.base_url, "/ae-api");
    assert.equal(result.document_detail.document_id, "doc-001");
    assert.equal(result.document_detail.status, "SUCCEEDED");
    assert.equal(result.upload.status, "QUEUED");
    assert.equal(result.upload.dedupe_status, "CREATED");
    assert.equal(result.retrieval.status, "COMPLETED");
    assert.equal(result.retrieval.cx_status, "READY");
    assert.equal(result.retrieval.evidence_count, 2);
    assert.equal(result.metadata.liveNetworkUsed, false);
    assert.deepEqual(
      fetchImpl.calls.map(call => call.url).sort(),
      [
        "/ae-api/api/v1/documents/doc-001",
        "/ae-api/api/v1/retrieval/contexts",
        "/ae-api/api/v1/uploads"
      ].sort()
    );
    assert.doesNotMatch(JSON.stringify(result), /Find selected evidence|source_text|chunk_text|service_token|provider_url|\/data\/nex-platform/);
  });

  it("requires injected fetch and a document item to stay static", async () => {
    await assert.rejects(
      () =>
        runFetchModeHarness({
          documents: documents(),
          uploadDraft: uploadDraft(),
          retrievalRequest: retrievalRequest()
        }),
      error =>
        error instanceof FetchModeHarnessError &&
        error.status === "HARNESS_FETCH_REQUIRED"
    );
    await assert.rejects(
      () =>
        runFetchModeHarness({
          fetchImpl: async () => jsonResponse({ payload: {} }),
          documents: [],
          uploadDraft: uploadDraft(),
          retrievalRequest: retrievalRequest()
        }),
      error =>
        error instanceof FetchModeHarnessError &&
        error.status === "HARNESS_DOCUMENT_REQUIRED"
    );
  });
});
