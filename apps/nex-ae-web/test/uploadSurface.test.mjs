import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_MULTIPART_UPLOAD_ROUTE,
  AE_UPLOAD_ROUTE,
  AE_WEB_UPLOAD_FILE_METADATA_SCHEMA_VERSION,
  AE_WEB_UPLOAD_SURFACE_SCHEMA_VERSION,
  UploadSurfaceError,
  buildUploadFileMetadata,
  buildUploadFormDataPayload,
  buildUploadHandoffPayload,
  buildUploadOwnershipRef,
  buildUploadSurfaceDraft,
  buildUploadSurfaceDraftFromFileMetadata,
  buildUploadSurfaceFromHandoff
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

  it("builds upload drafts from browser file metadata without source bytes", () => {
    const fileMetadata = buildUploadFileMetadata({
      file: {
        name: "selected-report.md",
        type: "text/markdown",
        size: 2048,
        lastModified: 1770000000000,
        webkitRelativePath: "private/selected-report.md"
      },
      sourceSha256
    });
    const draft = buildUploadSurfaceDraftFromFileMetadata({
      workspaceId: "workspace-local",
      fileMetadata,
      ownerScope: ownerScope()
    });
    const payload = buildUploadHandoffPayload(draft);
    const serialized = JSON.stringify({ fileMetadata, draft, payload });

    assert.equal(
      fileMetadata.upload_file_metadata_schema_version,
      AE_WEB_UPLOAD_FILE_METADATA_SCHEMA_VERSION
    );
    assert.equal(fileMetadata.filename, "selected-report.md");
    assert.equal(fileMetadata.contentType, "text/markdown");
    assert.equal(fileMetadata.sizeBytes, 2048);
    assert.equal(fileMetadata.fileSelected, true);
    assert.equal(fileMetadata.metadata.sourceContentIncluded, false);
    assert.equal(fileMetadata.metadata.localPathIncluded, false);
    assert.equal(fileMetadata.metadata.lastModifiedIncluded, false);
    assert.equal(draft.fileMetadata.filename, "selected-report.md");
    assert.equal(draft.uploadRoute, AE_MULTIPART_UPLOAD_ROUTE);
    assert.equal(payload.filename, "selected-report.md");
    assert.doesNotMatch(
      serialized,
      /content_text|content_base64|service_token|webkitRelativePath|private\//
    );
    assert.doesNotMatch(serialized, /1770000000000/);
  });

  it("builds multipart FormData without browser service or CX storage fields", () => {
    const file = {
      name: "selected-report.md",
      type: "text/markdown",
      size: 2048
    };
    const fileMetadata = buildUploadFileMetadata({ file, sourceSha256 });
    const draft = buildUploadSurfaceDraftFromFileMetadata({
      workspaceId: "workspace-local",
      fileMetadata,
      ownerScope: ownerScope()
    });
    const formData = buildUploadFormDataPayload(draft, {
      file,
      FormDataImpl: FakeFormData
    });

    assert.deepEqual(
      formData.entries.map(entry => [entry.name, entry.filename || null]),
      [
        ["file", "selected-report.md"],
        ["workspace_id", null],
        ["tenant_id", null],
        ["owner_user_id", null],
        ["uploaded_by_user_id", null],
        ["filename", null],
        ["content_type", null],
        ["size_bytes", null],
        ["source_sha256", null]
      ]
    );
    assert.equal(formData.entries[0].value, file);
    assert.equal(
      formData.entries.find(entry => entry.name === "source_sha256").value,
      sourceSha256
    );
    assert.doesNotMatch(
      JSON.stringify(formData.entries),
      /service_token|storage_path|provider_url|webkitRelativePath/
    );
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
      () => buildUploadFileMetadata(),
      error => error instanceof UploadSurfaceError && error.status === "TEXT_INVALID"
    );
    assert.throws(
      () =>
        buildUploadFileMetadata({
          filename: "safe.md",
          sizeBytes: 1,
          sourceSha256: "BAD"
        }),
      error => error instanceof UploadSurfaceError && error.status === "SOURCE_HASH_INVALID"
    );
    assert.throws(
      () =>
        buildUploadSurfaceDraftFromFileMetadata({
          workspaceId: "workspace-local",
          fileMetadata: { upload_file_metadata_schema_version: "wrong" },
          ownerScope: ownerScope()
        }),
      error =>
        error instanceof UploadSurfaceError &&
        error.status === "UPLOAD_FILE_METADATA_INVALID"
    );
    assert.throws(
      () => buildUploadHandoffPayload({ upload_surface_schema_version: "wrong" }),
      error => error instanceof UploadSurfaceError && error.status === "UPLOAD_DRAFT_INVALID"
    );
    assert.throws(
      () => buildUploadFormDataPayload(buildUploadSurfaceDraft({
        workspaceId: "workspace-local",
        filename: "safe.md",
        sizeBytes: 1,
        ownerScope: ownerScope()
      })),
      error => error instanceof UploadSurfaceError && error.status === "UPLOAD_FILE_REQUIRED"
    );
    assert.throws(
      () =>
        buildUploadFormDataPayload(
          buildUploadSurfaceDraft({
            workspaceId: "workspace-local",
            filename: "safe.md",
            sizeBytes: 1,
            ownerScope: ownerScope()
          }),
          { file: { name: "safe.md" }, FormDataImpl: null }
        ),
      error => error instanceof UploadSurfaceError && error.status === "FORM_DATA_UNAVAILABLE"
    );
    assert.throws(
      () => buildUploadSurfaceFromHandoff({ upload_handoff_schema_version: "wrong" }),
      error => error instanceof UploadSurfaceError && error.status === "UPLOAD_HANDOFF_INVALID"
    );
  });
});
