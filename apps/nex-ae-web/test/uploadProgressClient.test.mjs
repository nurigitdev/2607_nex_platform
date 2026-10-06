import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  UploadProgressClientError,
  createFetchUploadProgressClient,
  createMockUploadProgressClient,
  normalizeUploadProgress,
  uploadProgressRoute
} from "../src/uploadProgressClient.js";

describe("AE Web upload ingestion progress client", () => {
  it("normalizes an owner-scoped index-ready projection", async () => {
    const client = createMockUploadProgressClient();
    const result = await client.getProgress("handoff-local-upload-001");

    assert.equal(result.status, "INDEX_READY");
    assert.equal(result.progressPercent, 100);
    assert.equal(result.terminal, true);
    assert.equal(result.ingestion.runId, "run-local-upload-001");
    assert.equal(result.vectorIndex.retrievalUsable, true);
    assert.equal(result.metadata.privatePayloadIncluded, false);
    assert.doesNotMatch(
      JSON.stringify(result),
      /raw_source|chunk_text|embedding_vector|provider_credentials/
    );
  });

  it("uses one same-origin fetch route with credentials", async () => {
    const calls = [];
    const client = createFetchUploadProgressClient({
      baseUrl: "/ae-api/",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return response(progressRecord());
      }
    });

    const result = await client.getProgress("handoff-001");

    assert.equal(result.clientMode, "fetch");
    assert.equal(calls[0].url, "/ae-api/api/v1/uploads/handoff-001/progress");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.method, "GET");
  });

  it("maps network, HTTP, and malformed JSON failures safely", async () => {
    const network = createFetchUploadProgressClient({
      fetchImpl: async () => {
        throw new Error("private network detail");
      }
    });
    await assert.rejects(
      network.getProgress("handoff-001"),
      error => error.status === "NETWORK_ERROR" && error.retryable === true
    );

    const http = createFetchUploadProgressClient({
      fetchImpl: async () => response({ error_code: "cx.unavailable", retryable: true }, false, 503)
    });
    await assert.rejects(
      http.getProgress("handoff-001"),
      error => error.status === "CX_UNAVAILABLE" && error.retryable === true
    );

    const malformed = createFetchUploadProgressClient({
      fetchImpl: async () => ({ ok: true, status: 200, async json() { throw new Error(); } })
    });
    await assert.rejects(malformed.getProgress("handoff-001"), /schema/);
  });

  it("rejects unsafe metadata, invalid values, ids, and configuration", () => {
    assert.throws(() => uploadProgressRoute("bad/id"), /reference/);
    assert.throws(
      () => createFetchUploadProgressClient({ fetchImpl: 123 }),
      error => error instanceof UploadProgressClientError && error.status === "FETCH_UNAVAILABLE"
    );
    assert.throws(
      () => createFetchUploadProgressClient({ baseUrl: 42, fetchImpl: async () => {} }),
      /must be text/
    );
    for (const record of [
      null,
      progressRecord({ progress_schema_version: "wrong" }),
      progressRecord({ status: "UNKNOWN" }),
      progressRecord({ progress_percent: 101 }),
      progressRecord({ upload_handoff_id: "/private" }),
      progressRecord({ ingestion: { ...progressRecord().ingestion, status: "bad" } }),
      progressRecord({ metadata: { ...progressRecord().metadata, raw_source_included: true } })
    ]) {
      assert.throws(() =>
        normalizeUploadProgress(record, {
          clientMode: "mock",
          route: "/api/v1/uploads/handoff-001/progress"
        })
      );
    }
  });
});

function progressRecord(overrides = {}) {
  return {
    progress_schema_version: "ae_upload_ingestion_progress.v1",
    upload_handoff_id: "handoff-001",
    workspace_id: "workspace-001",
    document_id: "document-001",
    status: "INDEX_READY",
    progress_percent: 100,
    ingestion: {
      available: true,
      run_id: "run-001",
      status: "SUCCEEDED",
      step_total: 4,
      step_completed: 4,
      attempt_count: 1,
      max_attempts: 4
    },
    vector_index: {
      available: true,
      status: "READY",
      freshness_status: "READY",
      retrieval_usable: true,
      expected_vector_count: 3,
      actual_vector_count: 3
    },
    failure: { present: false, error_code: null, retryable: false },
    metadata: {
      owner_scoped: true,
      raw_source_included: false,
      markdown_included: false,
      chunk_text_included: false,
      embedding_vector_included: false,
      provider_credentials_included: false
    },
    ...overrides
  };
}

function response(payload, ok = true, status = 200) {
  return { ok, status, async json() { return payload; } };
}
