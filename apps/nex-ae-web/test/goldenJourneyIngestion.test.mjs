import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { runGoldenJourneyIngestion } from "../src/goldenJourneyIngestion.js";
import { createGoldenJourneyState } from "../src/goldenJourneyState.js";
import { createMockSessionClient } from "../src/sessionClient.js";
import { createMockUploadClient } from "../src/uploadClient.js";
import { createMockUploadProgressClient } from "../src/uploadProgressClient.js";

describe("AE Web login-upload-ingestion golden journey", () => {
  it("derives ownership from OA session and reaches index ready", async () => {
    const result = await runGoldenJourneyIngestion({
      journeyState: initialState("journey-ingestion-001"),
      sessionClient: sessionClient(),
      loginRequest: { tenant_id: "tenant-a", employee_id: "1001", password: "not-retained" },
      uploadClient: uploadClient(),
      uploadInput: uploadInput(),
      uploadProgressClient: createMockUploadProgressClient(),
      clock: sequenceClock()
    });

    assert.equal(result.status, "INDEX_READY");
    assert.equal(result.journeyState.current_stage, "INGESTION_INDEXED");
    assert.equal(result.journeyState.completed_stages.length, 3);
    assert.deepEqual(result.session, {
      status: "authenticated",
      tenantRef: "tenant-local",
      subjectRef: "owner-local",
      scopeCount: 2
    });
    assert.equal(result.upload.uploadHandoffId, "handoff-local-upload-001");
    assert.equal(result.progress.pollCount, 1);
    assert.equal(result.progress.retrievalUsable, true);
    assert.equal(JSON.stringify(result).includes("not-retained"), false);
  });

  it("polls bounded queued progress before index readiness", async () => {
    let calls = 0;
    const progressClient = createMockUploadProgressClient({
      responseFactory: handoffId => {
        calls += 1;
        return progressRecord(handoffId, calls === 1 ? "PROCESSING" : "INDEX_READY");
      }
    });
    const result = await runGoldenJourneyIngestion({
      journeyState: initialState("journey-ingestion-002"),
      sessionClient: sessionClient(),
      loginRequest: {},
      uploadClient: uploadClient(),
      uploadInput: uploadInput(),
      uploadProgressClient: progressClient,
      maxPolls: 2,
      clock: sequenceClock()
    });

    assert.equal(result.status, "INDEX_READY");
    assert.equal(result.progress.pollCount, 2);
  });

  it("fails closed for browser owner injection and owner mismatch", async () => {
    const forbidden = await runGoldenJourneyIngestion({
      journeyState: initialState("journey-ingestion-003"),
      sessionClient: sessionClient(),
      loginRequest: {},
      uploadClient: uploadClient(),
      uploadInput: { ...uploadInput(), ownerScope: { ownerUserId: "attacker" } },
      uploadProgressClient: createMockUploadProgressClient(),
      clock: sequenceClock()
    });
    assert.equal(forbidden.status, "FAILED");
    assert.equal(forbidden.failure.failureCode, "LOGIN_FAILED");

    const mismatch = await runGoldenJourneyIngestion({
      journeyState: initialState("journey-ingestion-004"),
      sessionClient: sessionClient(),
      loginRequest: {},
      uploadClient: uploadClient({ ownerUserId: "another-owner" }),
      uploadInput: uploadInput(),
      uploadProgressClient: createMockUploadProgressClient(),
      clock: sequenceClock()
    });
    assert.equal(mismatch.status, "FAILED");
    assert.equal(mismatch.failure.failureCode, "UPLOAD_FAILED");
    assert.equal(mismatch.evidence.failure.failed_stage, "UPLOAD_ACCEPTED");
  });

  it("records bounded ingestion failure without private error detail", async () => {
    const result = await runGoldenJourneyIngestion({
      journeyState: initialState("journey-ingestion-005"),
      sessionClient: sessionClient(),
      loginRequest: {},
      uploadClient: uploadClient(),
      uploadInput: uploadInput(),
      uploadProgressClient: {
        async getProgress() {
          throw Object.assign(new Error("private source text"), { retryable: true });
        }
      },
      maxPolls: 1,
      clock: sequenceClock()
    });

    assert.equal(result.status, "FAILED");
    assert.equal(result.failure.failureCode, "INGESTION_FAILED");
    assert.equal(result.failure.retryable, true);
    assert.equal(JSON.stringify(result).includes("private source text"), false);
  });

  it("rejects invalid dependencies and poll limits as bounded failures", async () => {
    const dependencies = await runGoldenJourneyIngestion({
      journeyState: initialState("journey-ingestion-006"),
      sessionClient: {},
      uploadClient: {},
      uploadProgressClient: {},
      uploadInput: uploadInput(),
      clock: sequenceClock()
    });
    assert.equal(dependencies.failure.failureCode, "LOGIN_FAILED");

    const polls = await runGoldenJourneyIngestion({
      journeyState: initialState("journey-ingestion-007"),
      sessionClient: sessionClient(),
      uploadClient: uploadClient(),
      uploadProgressClient: createMockUploadProgressClient(),
      uploadInput: uploadInput(),
      maxPolls: 0,
      clock: sequenceClock()
    });
    assert.equal(polls.failure.failureCode, "LOGIN_FAILED");
  });
});

function initialState(journeyId) {
  return createGoldenJourneyState({
    journeyId,
    startedAt: "2026-10-06T00:00:00.000Z"
  });
}

function sessionClient() {
  return createMockSessionClient({
    sessionSnapshot: {
      browser_session_schema_version: "oa_browser_session.v1",
      session_id: "session-001",
      status: "ACTIVE",
      issuer: "nex-oa",
      audience: "nex-ae-api",
      token_use: "user",
      tenant_ref: { type: "oa.tenant", id: "tenant-local" },
      subject_ref: { type: "oa.user", id: "owner-local" },
      scopes: ["workspace:use", "documents:upload"],
      roles: ["employee"],
      issued_at: "2026-10-06T00:00:00Z",
      expires_at: "2026-10-06T01:00:00Z",
      metadata: {
        raw_token_included: false,
        service_token_included: false,
        password_included: false,
        browser_payload_owner_authoritative: false,
        claim_owner_authoritative: true
      }
    }
  });
}

function uploadClient({ ownerUserId } = {}) {
  return createMockUploadClient({
    responseFactory: payload => ({
      upload_handoff_schema_version: "ae_upload_handoff.v1",
      upload_handoff_id: "handoff-local-upload-001",
      workspace_id: payload.workspace_id,
      tenant_id: payload.tenant_id,
      owner_user_id: ownerUserId || payload.owner_user_id,
      ownership_ref: payload.ownership_ref,
      status: "QUEUED",
      dedupe: { status: "CREATED" },
      source: {
        filename: payload.filename,
        content_type: payload.content_type,
        size_bytes: payload.size_bytes,
        source_sha256: payload.source_sha256
      },
      cx_document_ref: { document_id: "doc-local-upload-001" },
      links: {}
    })
  });
}

function uploadInput() {
  return {
    workspaceId: "workspace-local",
    filename: "reference.md",
    contentType: "text/markdown",
    sizeBytes: 100,
    sourceSha256: "a".repeat(64)
  };
}

function sequenceClock() {
  let second = 1;
  return () => `2026-10-06T00:00:${String(second++).padStart(2, "0")}.000Z`;
}

function progressRecord(handoffId, status) {
  const ready = status === "INDEX_READY";
  return {
    progress_schema_version: "ae_upload_ingestion_progress.v1",
    upload_handoff_id: handoffId,
    workspace_id: "workspace-local",
    document_id: "doc-local-upload-001",
    status,
    progress_percent: ready ? 100 : 50,
    ingestion: {
      available: true,
      run_id: "run-local-upload-001",
      status: ready ? "SUCCEEDED" : "RUNNING",
      step_total: 4,
      step_completed: ready ? 4 : 2,
      attempt_count: 1,
      max_attempts: 4
    },
    vector_index: {
      available: ready,
      status: ready ? "READY" : "PENDING",
      freshness_status: ready ? "READY" : "PENDING",
      retrieval_usable: ready,
      expected_vector_count: 3,
      actual_vector_count: ready ? 3 : 0
    },
    failure: { present: false, error_code: null, retryable: false },
    metadata: {
      owner_scoped: true,
      raw_source_included: false,
      markdown_included: false,
      chunk_text_included: false,
      embedding_vector_included: false,
      provider_credentials_included: false
    }
  };
}
