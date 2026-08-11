import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_UPLOAD_ROUTE,
  AE_WEB_UPLOAD_SURFACE_SCHEMA_VERSION,
  UploadSurfaceError,
  buildUploadHandoffPayload,
  buildUploadOwnershipRef,
  buildUploadSurfaceDraft,
  buildUploadSurfaceFromHandoff
} from "../src/uploadSurface.js";

const sourceSha256 = "d12261539d27dcab69f873a5e1a30587919b8ce4802782151f1bc2ba5390b610";

function ownerScope(overrides = {}) {
  return {
    tenantId: "tenant-local",
    ownerUserId: "owner-local",
    uploadedByUserId: "uploader-local",
    ...overrides
  };
}

function handoff(overrides = {}) {
  return {
    upload_handoff_schema_version: "ae_upload_handoff.v1",
    upload_handoff_id: "handoff-001",
    workspace_id: "workspace-local",
    tenant_id: "tenant-local",
    owner_user_id: "owner-local",
    ownership_ref: buildUploadOwnershipRef(ownerScope()),
    status: "QUEUED",
    source: {
      filename: "new-reference-pack.md",
      content_type: "text/markdown",
      size_bytes: 4096,
      source_sha256: sourceSha256,
      source_text_hash: null
    },
    cx_document_ref: {
      document_id: "doc-001"
    },
    ...overrides
  };
}

describe("upload surface", () => {
  it("builds canonical ownership refs with legacy aliases", () => {
    const ownershipRef = buildUploadOwnershipRef(ownerScope());

    assert.equal(ownershipRef.ownership_schema_version, "cx_source_ownership_ref.v1");
    assert.deepEqual(ownershipRef.tenant_ref, { type: "oa.tenant", id: "tenant-local" });
    assert.deepEqual(ownershipRef.owner_subject_ref, { type: "oa.user", id: "owner-local" });
    assert.deepEqual(ownershipRef.uploaded_by_subject_ref, {
      type: "oa.user",
      id: "uploader-local"
    });
    assert.deepEqual(ownershipRef.legacy, {
      tenant_id: "tenant-local",
      owner_user_id: "owner-local"
    });
  });

  it("defaults uploaded_by to owner and builds a safe handoff payload", () => {
    const draft = buildUploadSurfaceDraft({
      workspaceId: "workspace-local",
      filename: "new-reference-pack.md",
      contentType: "text/markdown",
      sizeBytes: 4096,
      sourceSha256,
      ownerScope: ownerScope({ uploadedByUserId: undefined })
    });
    const payload = buildUploadHandoffPayload(draft);

    assert.equal(draft.upload_surface_schema_version, AE_WEB_UPLOAD_SURFACE_SCHEMA_VERSION);
    assert.equal(draft.uploadRoute, AE_UPLOAD_ROUTE);
    assert.equal(draft.ownerScope.uploadedByUserId, "owner-local");
    assert.equal(payload.workspace_id, "workspace-local");
    assert.equal(payload.tenant_id, "tenant-local");
    assert.equal(payload.owner_user_id, "owner-local");
    assert.equal(payload.uploaded_by_user_id, "owner-local");
    assert.equal(payload.source_sha256, sourceSha256);
    assert.equal(payload.ownership_ref.uploaded_by_subject_ref.id, "owner-local");
    assert.deepEqual(draft.metadata, {
      sourceContentIncluded: false,
      browserServiceTokenIncluded: false,
      cxStorageIncluded: false
    });
    assert.doesNotMatch(JSON.stringify(payload), /content_text|content_base64|service_token/);
  });

  it("normalizes upload handoff records back into a web surface", () => {
    const surface = buildUploadSurfaceFromHandoff(handoff());

    assert.equal(surface.upload_surface_schema_version, AE_WEB_UPLOAD_SURFACE_SCHEMA_VERSION);
    assert.equal(surface.workspaceId, "workspace-local");
    assert.equal(surface.ownerScope.uploadedByUserId, "uploader-local");
    assert.equal(surface.documentId, "doc-001");
    assert.equal(surface.status, "QUEUED");
    assert.equal(surface.metadata.sourceContentIncluded, false);
  });

  it("rejects invalid upload drafts and source metadata", () => {
    assert.throws(
      () =>
        buildUploadSurfaceDraft({
          workspaceId: "workspace-local",
          filename: "../secret.md",
          sizeBytes: 1,
          ownerScope: ownerScope()
        }),
      error => error instanceof UploadSurfaceError && error.status === "FILENAME_INVALID"
    );
    assert.throws(
      () =>
        buildUploadSurfaceDraft({
          workspaceId: "workspace-local",
          filename: "safe.md",
          sizeBytes: -1,
          ownerScope: ownerScope()
        }),
      error => error instanceof UploadSurfaceError && error.status === "SIZE_INVALID"
    );
    assert.throws(
      () =>
        buildUploadSurfaceDraft({
          workspaceId: "workspace-local",
          filename: "safe.md",
          sizeBytes: 1,
          sourceSha256: "BAD",
          ownerScope: ownerScope()
        }),
      error => error instanceof UploadSurfaceError && error.status === "SOURCE_HASH_INVALID"
    );
    assert.throws(
      () => buildUploadHandoffPayload({ upload_surface_schema_version: "wrong" }),
      error => error instanceof UploadSurfaceError && error.status === "UPLOAD_DRAFT_INVALID"
    );
    assert.throws(
      () => buildUploadSurfaceFromHandoff({ upload_handoff_schema_version: "wrong" }),
      error => error instanceof UploadSurfaceError && error.status === "UPLOAD_HANDOFF_INVALID"
    );
  });
});
