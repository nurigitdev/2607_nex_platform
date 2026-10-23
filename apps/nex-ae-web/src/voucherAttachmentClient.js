export const VOUCHER_ATTACHMENT_BATCH_SCHEMA_VERSION =
  "ae_voucher_attachment_batch.v1";
export const VOUCHER_ATTACHMENT_MANIFEST_SCHEMA_VERSION =
  "ae_voucher_attachment_manifest.v1";
export const MAX_VOUCHER_ATTACHMENT_COUNT = 20;
export const MAX_VOUCHER_ATTACHMENT_FILE_BYTES = 25 * 1024 * 1024;
export const MAX_VOUCHER_ATTACHMENT_BATCH_BYTES = 100 * 1024 * 1024;

export const VOUCHER_ATTACHMENT_MEDIA_TYPES = new Set([
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
  "application/zip",
  "application/x-zip-compressed",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/x-hwp",
  "application/vnd.hancom.hwp"
]);

const BATCH_STATES = new Set([
  "DRAFT",
  "UPLOADING",
  "READY",
  "QUARANTINED",
  "FAILED",
  "LOCKED",
  "ABANDONED"
]);
const ITEM_STATES = new Set([
  "UPLOADING",
  "READY",
  "QUARANTINED",
  "FAILED",
  "LOCKED",
  "REMOVED"
]);
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HASH_REF_PATTERN = /^sha256:[0-9a-f]{64}$/;

export class VoucherAttachmentClientError extends Error {
  constructor(
    message,
    {
      status = "VOUCHER_ATTACHMENT_CLIENT_ERROR",
      httpStatus = 0,
      retryable = false
    } = {}
  ) {
    super(message);
    this.name = "VoucherAttachmentClientError";
    this.status = status;
    this.httpStatus = httpStatus;
    this.retryable = retryable;
  }
}

export function voucherAttachmentBatchRoute(batchId = null) {
  const root = "/api/v1/voucher-attachments/batches";
  return batchId == null ? root : `${root}/${encodeURIComponent(requiredUuid(batchId))}`;
}

export function voucherAttachmentItemRoute(batchId, attachmentId = null) {
  const root = `${voucherAttachmentBatchRoute(batchId)}/items`;
  return attachmentId == null
    ? root
    : `${root}/${encodeURIComponent(requiredUuid(attachmentId))}`;
}

export function voucherAttachmentContentRoute(
  batchId,
  attachmentId,
  { download = false } = {}
) {
  return `${voucherAttachmentItemRoute(batchId, attachmentId)}/content?download=${
    download ? "true" : "false"
  }`;
}

export function createFetchVoucherAttachmentClient({ baseUrl = "", fetchImpl } = {}) {
  const request = requiredFetch(fetchImpl);
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
  return {
    clientMode: "fetch",
    async createBatch({ conversationId, interactionId }) {
      const route = voucherAttachmentBatchRoute();
      const payload = await fetchJson(request, `${normalizedBaseUrl}${route}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          conversation_id: requiredText(conversationId, "conversationId"),
          interaction_id: requiredText(interactionId, "interactionId")
        })
      });
      return normalizeVoucherAttachmentBatch(payload);
    },
    async getBatch(batchId) {
      const route = voucherAttachmentBatchRoute(batchId);
      return normalizeVoucherAttachmentBatch(
        await fetchJson(request, `${normalizedBaseUrl}${route}`)
      );
    },
    async uploadItem(batchId, { attachmentId, file }) {
      assertVoucherAttachmentFile(file);
      const form = new FormData();
      form.append("attachment_id", requiredUuid(attachmentId));
      form.append("file", file, file.name);
      const route = voucherAttachmentItemRoute(batchId);
      const payload = await fetchJson(request, `${normalizedBaseUrl}${route}`, {
        method: "POST",
        credentials: "same-origin",
        body: form
      });
      return normalizeUploadedAttachment(payload);
    },
    async removeItem(batchId, attachmentId) {
      const route = voucherAttachmentItemRoute(batchId, attachmentId);
      return fetchJson(request, `${normalizedBaseUrl}${route}`, {
        method: "DELETE",
        credentials: "same-origin"
      });
    },
    async finalizeBatch(batchId) {
      const route = `${voucherAttachmentBatchRoute(batchId)}/finalize`;
      return normalizeVoucherAttachmentBatch(
        await fetchJson(request, `${normalizedBaseUrl}${route}`, {
          method: "POST",
          credentials: "same-origin"
        })
      );
    },
    async lockBatch(batchId) {
      const route = `${voucherAttachmentBatchRoute(batchId)}/lock`;
      return normalizeVoucherAttachmentManifest(
        await fetchJson(request, `${normalizedBaseUrl}${route}`, {
          method: "POST",
          credentials: "same-origin"
        })
      );
    },
    contentRoute(batchId, attachmentId, options) {
      return `${normalizedBaseUrl}${voucherAttachmentContentRoute(
        batchId,
        attachmentId,
        options
      )}`;
    }
  };
}

export function createMockVoucherAttachmentClient({ now = () => new Date() } = {}) {
  const batches = new Map();
  return {
    clientMode: "mock",
    async createBatch({ conversationId, interactionId }) {
      const batchId = crypto.randomUUID();
      const timestamp = wireTime(now());
      const batch = {
        schema_version: VOUCHER_ATTACHMENT_BATCH_SCHEMA_VERSION,
        attachment_batch_id: batchId,
        tenant_id: "tenant-local",
        owner_subject_ref: { type: "oa.user", id: "owner-local" },
        conversation_id: requiredText(conversationId, "conversationId"),
        interaction_id: requiredText(interactionId, "interactionId"),
        state: "DRAFT",
        attachment_count: 0,
        total_size_bytes: 0,
        attachment_manifest_hash: null,
        locked_at: null,
        created_at: timestamp,
        updated_at: timestamp,
        trace: {
          trace_id: "1".repeat(32),
          correlation_id: "mock-voucher-attachment",
          causation_id: interactionId
        },
        items: []
      };
      batches.set(batchId, batch);
      return structuredClone(batch);
    },
    async getBatch(batchId) {
      return structuredClone(requiredBatch(batches, batchId));
    },
    async uploadItem(batchId, { attachmentId, file }) {
      assertVoucherAttachmentFile(file);
      const batch = requiredMutableBatch(batches, batchId);
      const admittedId = requiredUuid(attachmentId);
      const digest = await fileDigest(file);
      const existing = batch.items.find(item => item.attachment_id === admittedId);
      const item = existing || {
        attachment_id: admittedId,
        attachment_batch_id: batch.attachment_batch_id,
        state: "READY",
        display_name: file.name,
        media_type: file.type,
        size_bytes: file.size,
        content_sha256: digest,
        object_ref: `voucher-attachment:${admittedId.replaceAll("-", "")}`,
        object_version_ref: `mock-${digest.slice(0, 16)}`,
        scan_status: "CLEAN",
        evidence_ref: null,
        created_at: wireTime(now()),
        updated_at: wireTime(now())
      };
      if (!existing) batch.items.push(item);
      refreshMockBatch(batch, now());
      return {
        attachment_batch_id: batch.attachment_batch_id,
        attachment: structuredClone(item),
        resolution: {
          status: "READY",
          immutable: true
        }
      };
    },
    async removeItem(batchId, attachmentId) {
      const batch = requiredMutableBatch(batches, batchId);
      const index = batch.items.findIndex(
        item => item.attachment_id === requiredUuid(attachmentId)
      );
      if (index < 0) throw mockNotFound();
      batch.items.splice(index, 1);
      refreshMockBatch(batch, now());
      return { state: "REMOVED" };
    },
    async finalizeBatch(batchId) {
      const batch = requiredMutableBatch(batches, batchId);
      if (batch.items.length === 0 || batch.items.some(item => item.state !== "READY")) {
        throw new VoucherAttachmentClientError("Attachment batch is not ready.", {
          status: "VOUCHER_ATTACHMENT_BATCH_NOT_READY",
          httpStatus: 409
        });
      }
      batch.state = "READY";
      batch.updated_at = wireTime(now());
      return structuredClone(batch);
    },
    async lockBatch(batchId) {
      const batch = requiredMutableBatch(batches, batchId);
      if (batch.state !== "READY" && batch.state !== "LOCKED") {
        throw new VoucherAttachmentClientError("Attachment batch is not ready.", {
          status: "VOUCHER_ATTACHMENT_BATCH_NOT_READY",
          httpStatus: 409
        });
      }
      batch.state = "LOCKED";
      batch.locked_at ||= wireTime(now());
      batch.items = batch.items.map(item => ({ ...item, state: "LOCKED" }));
      const manifest = await mockManifest(batch);
      batch.attachment_manifest_hash = manifest.attachment_manifest_hash;
      batch.updated_at = wireTime(now());
      return structuredClone(manifest);
    },
    contentRoute(batchId, attachmentId, options) {
      return voucherAttachmentContentRoute(batchId, attachmentId, options);
    }
  };
}

export function assertVoucherAttachmentFile(file) {
  if (
    !file ||
    typeof file.name !== "string" ||
    !file.name.trim() ||
    file.name.includes("/") ||
    file.name.includes("\\")
  ) {
    throw invalidFile("첨부 파일 이름이 올바르지 않습니다.");
  }
  if (!VOUCHER_ATTACHMENT_MEDIA_TYPES.has(file.type)) {
    throw invalidFile("지원하지 않는 첨부 파일 형식입니다.");
  }
  if (!Number.isInteger(file.size) || file.size < 1) {
    throw invalidFile("빈 파일은 첨부할 수 없습니다.");
  }
  if (file.size > MAX_VOUCHER_ATTACHMENT_FILE_BYTES) {
    throw invalidFile("파일 하나의 크기는 25MB를 넘을 수 없습니다.");
  }
  return file;
}

export function normalizeVoucherAttachmentBatch(payload) {
  if (
    !isObject(payload) ||
    payload.schema_version !== VOUCHER_ATTACHMENT_BATCH_SCHEMA_VERSION ||
    !BATCH_STATES.has(payload.state) ||
    !Array.isArray(payload.items)
  ) {
    throw invalidResponse("Attachment batch response is invalid.");
  }
  const items = payload.items.map(normalizeVoucherAttachmentItem);
  if (
    payload.attachment_count !== items.filter(item => item.state !== "REMOVED").length ||
    payload.total_size_bytes !==
      items
        .filter(item => item.state !== "REMOVED")
        .reduce((total, item) => total + item.size_bytes, 0)
  ) {
    throw invalidResponse("Attachment batch totals are invalid.");
  }
  return {
    schema_version: payload.schema_version,
    attachment_batch_id: requiredUuid(payload.attachment_batch_id),
    tenant_id: requiredText(payload.tenant_id, "tenant_id"),
    owner_subject_ref: normalizeOwner(payload.owner_subject_ref),
    conversation_id: requiredText(payload.conversation_id, "conversation_id"),
    interaction_id: requiredText(payload.interaction_id, "interaction_id"),
    state: payload.state,
    attachment_count: payload.attachment_count,
    total_size_bytes: payload.total_size_bytes,
    attachment_manifest_hash: optionalHashRef(payload.attachment_manifest_hash),
    locked_at: optionalText(payload.locked_at),
    created_at: requiredText(payload.created_at, "created_at"),
    updated_at: requiredText(payload.updated_at, "updated_at"),
    items
  };
}

export function normalizeVoucherAttachmentManifest(payload) {
  if (
    !isObject(payload) ||
    payload.schema_version !== VOUCHER_ATTACHMENT_MANIFEST_SCHEMA_VERSION ||
    !Array.isArray(payload.items)
  ) {
    throw invalidResponse("Attachment manifest response is invalid.");
  }
  const items = payload.items.map(normalizeVoucherAttachmentManifestItem);
  if (
    payload.attachment_count !== items.length ||
    payload.total_size_bytes !== items.reduce((total, item) => total + item.size_bytes, 0)
  ) {
    throw invalidResponse("Attachment manifest totals are invalid.");
  }
  return {
    schema_version: payload.schema_version,
    attachment_batch_id: requiredUuid(payload.attachment_batch_id),
    tenant_id: requiredText(payload.tenant_id, "tenant_id"),
    owner_subject_ref: normalizeOwner(payload.owner_subject_ref),
    conversation_id: requiredText(payload.conversation_id, "conversation_id"),
    interaction_id: requiredText(payload.interaction_id, "interaction_id"),
    attachment_count: payload.attachment_count,
    total_size_bytes: payload.total_size_bytes,
    items,
    attachment_manifest_hash: requiredHashRef(payload.attachment_manifest_hash)
  };
}

function normalizeUploadedAttachment(payload) {
  if (!isObject(payload) || !isObject(payload.attachment)) {
    throw invalidResponse("Attachment upload response is invalid.");
  }
  return {
    attachment_batch_id: requiredUuid(payload.attachment_batch_id),
    attachment: normalizeVoucherAttachmentItem(payload.attachment)
  };
}

function normalizeVoucherAttachmentItem(value) {
  if (!isObject(value) || !ITEM_STATES.has(value.state)) {
    throw invalidResponse("Attachment item response is invalid.");
  }
  return {
    attachment_id: requiredUuid(value.attachment_id),
    attachment_batch_id: requiredUuid(value.attachment_batch_id),
    state: value.state,
    display_name: requiredText(value.display_name, "display_name"),
    media_type: requiredText(value.media_type, "media_type"),
    size_bytes: nonNegativeInteger(value.size_bytes, "size_bytes"),
    content_sha256: optionalDigest(value.content_sha256),
    scan_status: optionalText(value.scan_status),
    created_at: optionalText(value.created_at),
    updated_at: optionalText(value.updated_at)
  };
}

function normalizeVoucherAttachmentManifestItem(value) {
  if (!isObject(value)) {
    throw invalidResponse("Attachment manifest item response is invalid.");
  }
  return {
    attachment_id: requiredUuid(value.attachment_id),
    object_ref: requiredText(value.object_ref, "object_ref"),
    object_version_ref: optionalText(value.object_version_ref),
    display_name: requiredText(value.display_name, "display_name"),
    media_type: requiredText(value.media_type, "media_type"),
    size_bytes: positiveInteger(value.size_bytes, "size_bytes"),
    content_sha256: requiredDigest(value.content_sha256),
    evidence_ref: optionalText(value.evidence_ref)
  };
}

async function fetchJson(fetchImpl, url, options = {}) {
  let response;
  try {
    response = await fetchImpl(url, { credentials: "same-origin", ...options });
  } catch (error) {
    throw new VoucherAttachmentClientError("첨부 서비스에 연결할 수 없습니다.", {
      status: "VOUCHER_ATTACHMENT_UNAVAILABLE",
      retryable: true
    });
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const expired = response.status === 401;
    throw new VoucherAttachmentClientError(
      expired
        ? "로그인 세션이 만료되었습니다."
        : payload?.detail || "첨부 요청을 처리하지 못했습니다.",
      {
        status: expired
          ? "SESSION_EXPIRED"
          : payload?.error_code || "VOUCHER_ATTACHMENT_REQUEST_FAILED",
        httpStatus: response.status,
        retryable: Boolean(payload?.retryable)
      }
    );
  }
  if (!isObject(payload)) throw invalidResponse("Attachment response is not JSON.");
  return payload;
}

function requiredFetch(fetchImpl) {
  const request = fetchImpl || globalThis.fetch;
  if (typeof request !== "function") {
    throw new VoucherAttachmentClientError("fetch is unavailable.", {
      status: "VOUCHER_ATTACHMENT_FETCH_UNAVAILABLE"
    });
  }
  return request;
}

function normalizeBaseUrl(baseUrl) {
  if (baseUrl == null || baseUrl === "") return "";
  if (typeof baseUrl !== "string") throw invalidResponse("baseUrl is invalid.");
  return baseUrl.replace(/\/+$/, "");
}

function requiredBatch(batches, batchId) {
  const batch = batches.get(requiredUuid(batchId));
  if (!batch) throw mockNotFound();
  return batch;
}

function requiredMutableBatch(batches, batchId) {
  const batch = requiredBatch(batches, batchId);
  if (batch.state === "LOCKED") {
    throw new VoucherAttachmentClientError("Locked attachments cannot be changed.", {
      status: "VOUCHER_ATTACHMENT_BATCH_LOCKED",
      httpStatus: 409
    });
  }
  return batch;
}

function refreshMockBatch(batch, now) {
  batch.attachment_count = batch.items.length;
  batch.total_size_bytes = batch.items.reduce((total, item) => total + item.size_bytes, 0);
  batch.state = batch.items.length > 0 ? "UPLOADING" : "DRAFT";
  batch.updated_at = wireTime(now);
}

async function mockManifest(batch) {
  const core = {
    schema_version: VOUCHER_ATTACHMENT_MANIFEST_SCHEMA_VERSION,
    attachment_batch_id: batch.attachment_batch_id,
    tenant_id: batch.tenant_id,
    owner_subject_ref: batch.owner_subject_ref,
    conversation_id: batch.conversation_id,
    interaction_id: batch.interaction_id,
    attachment_count: batch.items.length,
    total_size_bytes: batch.items.reduce((total, item) => total + item.size_bytes, 0),
    items: [...batch.items]
      .sort((left, right) => left.attachment_id.localeCompare(right.attachment_id))
      .map(item => ({
        attachment_id: item.attachment_id,
        object_ref: item.object_ref,
        object_version_ref: item.object_version_ref,
        display_name: item.display_name,
        media_type: item.media_type,
        size_bytes: item.size_bytes,
        content_sha256: item.content_sha256,
        evidence_ref: item.evidence_ref
      }))
  };
  return {
    ...core,
    attachment_manifest_hash: `sha256:${await sha256Text(stableJson(core))}`
  };
}

async function fileDigest(file) {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)]
    .map(value => value.toString(16).padStart(2, "0"))
    .join("");
}

async function sha256Text(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)]
    .map(item => item.toString(16).padStart(2, "0"))
    .join("");
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (isObject(value)) {
    return `{${Object.keys(value)
      .sort()
      .map(key => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function normalizeOwner(value) {
  if (!isObject(value) || value.type !== "oa.user") {
    throw invalidResponse("Attachment owner is invalid.");
  }
  return { type: "oa.user", id: requiredText(value.id, "owner_subject_ref.id") };
}

function requiredUuid(value) {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    throw new VoucherAttachmentClientError("Attachment identity is invalid.", {
      status: "VOUCHER_ATTACHMENT_ID_INVALID"
    });
  }
  return value.toLowerCase();
}

function requiredHashRef(value) {
  if (typeof value !== "string" || !HASH_REF_PATTERN.test(value)) {
    throw invalidResponse("Attachment manifest hash is invalid.");
  }
  return value;
}

function optionalHashRef(value) {
  return value == null ? null : requiredHashRef(value);
}

function optionalDigest(value) {
  if (value == null) return null;
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw invalidResponse("Attachment digest is invalid.");
  }
  return value;
}

function requiredDigest(value) {
  const digest = optionalDigest(value);
  if (digest == null) throw invalidResponse("Attachment digest is required.");
  return digest;
}

function requiredText(value, field) {
  if (typeof value !== "string" || !value.trim()) {
    throw new VoucherAttachmentClientError(`${field} is required.`, {
      status: "VOUCHER_ATTACHMENT_INPUT_INVALID"
    });
  }
  return value.trim();
}

function optionalText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function nonNegativeInteger(value, field) {
  if (!Number.isInteger(value) || value < 0) {
    throw invalidResponse(`Attachment ${field} is invalid.`);
  }
  return value;
}

function positiveInteger(value, field) {
  if (!Number.isInteger(value) || value < 1) {
    throw invalidResponse(`Attachment ${field} is invalid.`);
  }
  return value;
}

function invalidFile(message) {
  return new VoucherAttachmentClientError(message, {
    status: "VOUCHER_ATTACHMENT_FILE_INVALID"
  });
}

function invalidResponse(message) {
  return new VoucherAttachmentClientError(message, {
    status: "VOUCHER_ATTACHMENT_RESPONSE_INVALID"
  });
}

function mockNotFound() {
  return new VoucherAttachmentClientError("Attachment batch was not found.", {
    status: "VOUCHER_ATTACHMENT_NOT_FOUND",
    httpStatus: 404
  });
}

function wireTime(value) {
  return new Date(value).toISOString();
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
