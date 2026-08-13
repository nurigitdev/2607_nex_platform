export const AE_WEB_UPLOAD_SURFACE_SCHEMA_VERSION = "ae_web_upload_surface.v1";
export const AE_WEB_UPLOAD_FILE_METADATA_SCHEMA_VERSION =
  "ae_web_upload_file_metadata.v1";
export const AE_UPLOAD_HANDOFF_SCHEMA_VERSION = "ae_upload_handoff.v1";
export const CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION = "cx_source_ownership_ref.v1";
export const AE_UPLOAD_ROUTE = "/api/v1/uploads";

export class UploadSurfaceError extends Error {
  constructor(message, { status = "UPLOAD_SURFACE_INVALID" } = {}) {
    super(message);
    this.name = "UploadSurfaceError";
    this.status = status;
  }
}

export function buildUploadOwnershipRef({
  tenantId,
  ownerUserId,
  uploadedByUserId = ownerUserId
}) {
  const normalizedTenantId = requiredText(tenantId, "tenantId");
  const normalizedOwnerUserId = requiredText(ownerUserId, "ownerUserId");
  const normalizedUploadedByUserId = requiredText(uploadedByUserId, "uploadedByUserId");

  return {
    ownership_schema_version: CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION,
    tenant_ref: {
      type: "oa.tenant",
      id: normalizedTenantId
    },
    owner_subject_ref: {
      type: "oa.user",
      id: normalizedOwnerUserId
    },
    uploaded_by_subject_ref: {
      type: "oa.user",
      id: normalizedUploadedByUserId
    },
    legacy: {
      tenant_id: normalizedTenantId,
      owner_user_id: normalizedOwnerUserId
    },
    compatibility_mode: "legacy_owner_fields_mapped_to_oa_subject_refs"
  };
}

export function buildUploadSurfaceDraft({
  workspaceId,
  filename,
  contentType = "application/octet-stream",
  sizeBytes,
  sourceSha256,
  ownerScope
}) {
  const ownershipRef = buildUploadOwnershipRef(ownerScope || {});
  const normalizedFilename = requiredFilename(filename);
  const normalizedContentType = requiredText(contentType, "contentType");
  const normalizedSizeBytes = nonNegativeInteger(sizeBytes, "sizeBytes");
  const normalizedSourceSha256 = optionalSha256(sourceSha256);

  return {
    upload_surface_schema_version: AE_WEB_UPLOAD_SURFACE_SCHEMA_VERSION,
    target_handoff_schema_version: AE_UPLOAD_HANDOFF_SCHEMA_VERSION,
    uploadRoute: AE_UPLOAD_ROUTE,
    workspaceId: requiredText(workspaceId, "workspaceId"),
    filename: normalizedFilename,
    contentType: normalizedContentType,
    sizeBytes: normalizedSizeBytes,
    sourceSha256: normalizedSourceSha256,
    ownerScope: {
      tenantId: ownershipRef.legacy.tenant_id,
      ownerUserId: ownershipRef.legacy.owner_user_id,
      uploadedByUserId: ownershipRef.uploaded_by_subject_ref.id
    },
    ownershipRef,
    status: "READY_FOR_HANDOFF",
    metadata: {
      sourceContentIncluded: false,
      browserServiceTokenIncluded: false,
      cxStorageIncluded: false
    }
  };
}

export function buildUploadFileMetadata({
  file,
  filename = file?.name,
  contentType = file?.type || "application/octet-stream",
  sizeBytes = file?.size,
  sourceSha256
} = {}) {
  const normalizedFilename = requiredFilename(filename);
  const normalizedContentType = requiredText(contentType, "contentType");
  const normalizedSizeBytes = nonNegativeInteger(sizeBytes, "sizeBytes");
  const normalizedSourceSha256 = optionalSha256(sourceSha256);

  return {
    upload_file_metadata_schema_version: AE_WEB_UPLOAD_FILE_METADATA_SCHEMA_VERSION,
    filename: normalizedFilename,
    contentType: normalizedContentType,
    sizeBytes: normalizedSizeBytes,
    sourceSha256: normalizedSourceSha256,
    fileSelected: Boolean(file),
    metadata: {
      sourceContentIncluded: false,
      browserServiceTokenIncluded: false,
      localPathIncluded: false,
      lastModifiedIncluded: false
    }
  };
}

export function buildUploadSurfaceDraftFromFileMetadata({
  workspaceId,
  fileMetadata,
  ownerScope
}) {
  if (
    !fileMetadata ||
    fileMetadata.upload_file_metadata_schema_version !==
      AE_WEB_UPLOAD_FILE_METADATA_SCHEMA_VERSION
  ) {
    throw new UploadSurfaceError("Upload file metadata is invalid.", {
      status: "UPLOAD_FILE_METADATA_INVALID"
    });
  }

  return {
    ...buildUploadSurfaceDraft({
      workspaceId,
      filename: fileMetadata.filename,
      contentType: fileMetadata.contentType,
      sizeBytes: fileMetadata.sizeBytes,
      sourceSha256: fileMetadata.sourceSha256,
      ownerScope
    }),
    fileMetadata
  };
}

export function buildUploadHandoffPayload(draft) {
  if (!draft || draft.upload_surface_schema_version !== AE_WEB_UPLOAD_SURFACE_SCHEMA_VERSION) {
    throw new UploadSurfaceError("Upload draft is invalid.", {
      status: "UPLOAD_DRAFT_INVALID"
    });
  }

  const payload = {
    workspace_id: draft.workspaceId,
    filename: draft.filename,
    content_type: draft.contentType,
    size_bytes: draft.sizeBytes,
    tenant_id: draft.ownerScope.tenantId,
    owner_user_id: draft.ownerScope.ownerUserId,
    uploaded_by_user_id: draft.ownerScope.uploadedByUserId,
    ownership_ref: draft.ownershipRef
  };
  if (draft.sourceSha256) {
    payload.source_sha256 = draft.sourceSha256;
  }
  return payload;
}

export function buildUploadSurfaceFromHandoff(handoff) {
  if (!handoff || handoff.upload_handoff_schema_version !== AE_UPLOAD_HANDOFF_SCHEMA_VERSION) {
    throw new UploadSurfaceError("Upload handoff is invalid.", {
      status: "UPLOAD_HANDOFF_INVALID"
    });
  }

  return {
    upload_surface_schema_version: AE_WEB_UPLOAD_SURFACE_SCHEMA_VERSION,
    target_handoff_schema_version: handoff.upload_handoff_schema_version,
    uploadRoute: AE_UPLOAD_ROUTE,
    workspaceId: handoff.workspace_id,
    filename: handoff.source?.filename || "unknown",
    contentType: handoff.source?.content_type || "application/octet-stream",
    sizeBytes: handoff.source?.size_bytes ?? 0,
    sourceSha256: handoff.source?.source_sha256 || null,
    ownerScope: {
      tenantId: handoff.tenant_id,
      ownerUserId: handoff.owner_user_id,
      uploadedByUserId:
        handoff.ownership_ref?.uploaded_by_subject_ref?.id || handoff.owner_user_id
    },
    ownershipRef: handoff.ownership_ref,
    status: handoff.status,
    documentId: handoff.cx_document_ref?.document_id || null,
    metadata: {
      sourceContentIncluded: false,
      browserServiceTokenIncluded: false,
      cxStorageIncluded: false
    }
  };
}

function requiredText(value, fieldName) {
  if (typeof value !== "string" || !value.trim()) {
    throw new UploadSurfaceError(`${fieldName} must be a non-empty string.`, {
      status: "TEXT_INVALID"
    });
  }
  return value.trim();
}

function requiredFilename(value) {
  const filename = requiredText(value, "filename");
  if (filename.includes("/") || filename.includes("\\")) {
    throw new UploadSurfaceError("filename must not include path separators.", {
      status: "FILENAME_INVALID"
    });
  }
  return filename;
}

function nonNegativeInteger(value, fieldName) {
  if (!Number.isInteger(value) || value < 0) {
    throw new UploadSurfaceError(`${fieldName} must be a non-negative integer.`, {
      status: "SIZE_INVALID"
    });
  }
  return value;
}

function optionalSha256(value) {
  if (value == null || value === "") return null;
  const normalized = requiredText(value, "sourceSha256");
  if (!/^[0-9a-f]{64}$/.test(normalized)) {
    throw new UploadSurfaceError("sourceSha256 must be a lowercase SHA-256 hex string.", {
      status: "SOURCE_HASH_INVALID"
    });
  }
  return normalized;
}
