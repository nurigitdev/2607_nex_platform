import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_UPLOAD_CLIENT_SCHEMA_VERSION,
  UploadClientError,
  buildUploadSubmissionResult,
  createFetchUploadClient,
  createMockUploadClient
} from "../src/uploadClient.js";
import {
  AE_UPLOAD_HANDOFF_SCHEMA_VERSION,
  AE_MULTIPART_UPLOAD_ROUTE,
  AE_UPLOAD_ROUTE,
  buildUploadOwnershipRef,
  buildUploadSurfaceDraft
} from "../src/uploadSurface.js";

const sourceSha256 = "d12261539d27dcab69f873a5e1a30587919b8ce4802782151f1bc2ba5390b610";

class FakeFormData {
  constructor() {
    this.entries = [];
  }

  append(name, value, filename) {
    this.entries.push({ name, value, filename });
  }
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

function handoff(overrides = {}) {
  return {
    upload_handoff_schema_version: AE_UPLOAD_HANDOFF_SCHEMA_VERSION,
    upload_handoff_id: "handoff-001",
    workspace_id: "workspace-local",
    tenant_id: "tenant-local",
    owner_user_id: "owner-local",
    ownership_ref: buildUploadOwnershipRef({
      tenantId: "tenant-local",
      ownerUserId: "owner-local"
    }),
    status: "QUEUED",
    dedupe: {
      status: "CREATED"
    },
    source: {
      filename: "new-reference-pack.md",
      content_type: "text/markdown",
      size_bytes: 4096,
      source_sha256: sourceSha256
    },
    cx_document_ref: {
      document_id: "doc-001"
    },
    links: {
      upload_handoff: "/api/v1/uploads/handoff-001",
      document_detail: "/api/v1/documents/doc-001",
      ignored: 123
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

describe("upload client adapters", () => {
  it("submits a mock upload draft and returns a safe normalized result", async () => {
    const client = createMockUploadClient();

    const result = await client.submitUploadDraft(uploadDraft());

    assert.equal(client.clientMode, "mock");
    assert.equal(result.upload_client_schema_version, AE_WEB_UPLOAD_CLIENT_SCHEMA_VERSION);
    assert.equal(result.clientMode, "mock");
    assert.equal(result.uploadRoute, AE_UPLOAD_ROUTE);
    assert.equal(result.status, "QUEUED");
    assert.equal(result.dedupeStatus, "CREATED");
    assert.equal(result.source.sourceSha256, sourceSha256);
    assert.equal(result.ownerScope.ownerUserId, "owner-local");
    assert.equal(result.metadata.sourceContentIncluded, false);
    assert.equal(result.metadata.browserServiceTokenIncluded, false);
    assert.equal(result.metadata.providerUrlIncluded, false);
    assert.doesNotMatch(JSON.stringify(result), /content_text|content_base64|service_token|storage_path|provider_url/);
  });

  it("preserves duplicate upload outcomes without treating them as transport failures", async () => {
    const client = createMockUploadClient({
      responseFactory: payload =>
        handoff({
          upload_handoff_id: "handoff-duplicate",
          status: "ALREADY_EXISTS",
          dedupe: {
            status: "ALREADY_EXISTS",
            reused_document_id: "doc-001"
          },
          source: {
            filename: payload.filename,
            content_type: payload.content_type,
            size_bytes: payload.size_bytes,
            source_sha256: payload.source_sha256
          }
        })
    });

    const result = await client.submitUploadDraft(uploadDraft());

    assert.equal(result.status, "ALREADY_EXISTS");
    assert.equal(result.dedupeStatus, "ALREADY_EXISTS");
    assert.equal(result.uploadHandoffId, "handoff-duplicate");
    assert.equal(result.retryable, false);
  });

  it("posts upload handoff metadata through the AE facade route", async () => {
    const calls = [];
    const client = createFetchUploadClient({
      baseUrl: "https://ae.local",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse({ payload: handoff() });
      }
    });

    const result = await client.submitUploadDraft(uploadDraft());
    const body = JSON.parse(calls[0].options.body);

    assert.equal(calls[0].url, "https://ae.local/api/v1/uploads");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.headers.Accept, "application/json");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.equal(body.filename, "new-reference-pack.md");
    assert.equal(body.owner_user_id, "owner-local");
    assert.equal(body.ownership_ref.owner_subject_ref.type, "oa.user");
    assert.equal(result.clientMode, "fetch");
    assert.equal(result.documentId, "doc-001");
  });

  it("posts selected browser files as multipart FormData through the AE facade", async () => {
    const calls = [];
    const selectedFile = {
      name: "new-reference-pack.md",
      type: "text/markdown",
      size: 4096
    };
    const client = createFetchUploadClient({
      baseUrl: "https://ae.local",
      FormDataImpl: FakeFormData,
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return jsonResponse({ payload: handoff() });
      }
    });

    const result = await client.submitUploadDraft(uploadDraft(), { file: selectedFile });
    const body = calls[0].options.body;

    assert.equal(calls[0].url, "https://ae.local/api/v1/uploads/files");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.credentials, "same-origin");
    assert.equal(calls[0].options.headers.Accept, "application/json");
    assert.equal("Content-Type" in calls[0].options.headers, false);
    assert.equal(body.entries[0].name, "file");
    assert.equal(body.entries[0].value, selectedFile);
    assert.equal(body.entries[0].filename, "new-reference-pack.md");
    assert.equal(
      body.entries.find(entry => entry.name === "source_sha256").value,
      sourceSha256
    );
    assert.equal(result.uploadRoute, AE_MULTIPART_UPLOAD_ROUTE);
    assert.equal(result.metadata.sourceContentIncluded, true);
    assert.doesNotMatch(
      JSON.stringify(result),
      /service_token|storage_path|provider_url/
    );
  });

  it("maps HTTP, network, missing fetch, and invalid handoff failures to typed errors", async () => {
    const httpClient = createFetchUploadClient({
      fetchImpl: async () =>
        jsonResponse({
          ok: false,
          status: 409,
          payload: {
            error_code: "ae.upload_owner_invalid",
            detail: "Owner is invalid.",
            retryable: false
          }
        })
    });
    await assert.rejects(
      () => httpClient.submitUploadDraft(uploadDraft()),
      error =>
        error instanceof UploadClientError &&
        error.status === "ae.upload_owner_invalid" &&
        error.retryable === false
    );

    const networkClient = createFetchUploadClient({
      fetchImpl: async () => {
        throw new Error("offline");
      }
    });
    await assert.rejects(
      () => networkClient.submitUploadDraft(uploadDraft()),
      error =>
        error instanceof UploadClientError &&
        error.status === "NETWORK_ERROR" &&
        error.retryable === true
    );

    assert.throws(
      () => createFetchUploadClient({ fetchImpl: "bad" }),
      error => error instanceof UploadClientError && error.status === "FETCH_UNAVAILABLE"
    );
    assert.throws(
      () => buildUploadSubmissionResult({ upload_handoff_schema_version: "wrong" }),
      error => error.status === "UPLOAD_HANDOFF_INVALID"
    );
  });
});
