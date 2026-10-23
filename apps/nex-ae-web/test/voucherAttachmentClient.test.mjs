import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  MAX_VOUCHER_ATTACHMENT_BATCH_BYTES,
  VoucherAttachmentClientError,
  assertVoucherAttachmentFile,
  createFetchVoucherAttachmentClient,
  createMockVoucherAttachmentClient,
  normalizeVoucherAttachmentManifest,
  voucherAttachmentContentRoute
} from "../src/voucherAttachmentClient.js";

const CONTEXT = {
  conversationId: "conversation-p8-s75g",
  interactionId: "interaction-p8-s75g"
};

describe("AE Web Voucher attachment client", () => {
  it("creates, uploads, finalizes and locks a deterministic mock batch", async () => {
    const client = createMockVoucherAttachmentClient({
      now: () => new Date("2026-10-23T00:00:00Z")
    });
    const batch = await client.createBatch(CONTEXT);
    const firstId = crypto.randomUUID();
    const secondId = crypto.randomUUID();

    await client.uploadItem(batch.attachment_batch_id, {
      attachmentId: firstId,
      file: testFile("영수증.png", "image/png", "receipt")
    });
    await client.uploadItem(batch.attachment_batch_id, {
      attachmentId: secondId,
      file: testFile("내역.pdf", "application/pdf", "statement")
    });
    const ready = await client.finalizeBatch(batch.attachment_batch_id);
    const manifest = await client.lockBatch(batch.attachment_batch_id);

    assert.equal(ready.state, "READY");
    assert.equal(manifest.attachment_count, 2);
    assert.match(manifest.attachment_manifest_hash, /^sha256:[0-9a-f]{64}$/);
    assert.deepEqual(
      manifest.items.map(item => item.attachment_id),
      [firstId, secondId].sort()
    );
    assert.equal(manifest.items.every(item => !("state" in item)), true);
    assert.equal("locked_at" in manifest, false);
  });

  it("normalizes the exact runtime manifest contract without batch lifecycle fields", () => {
    const manifest = normalizeVoucherAttachmentManifest({
      schema_version: "ae_voucher_attachment_manifest.v1",
      attachment_batch_id: "750a0000-0000-4000-8000-000000000001",
      tenant_id: "tenant-p8-7a",
      owner_subject_ref: { type: "oa.user", id: "employee-1001" },
      conversation_id: "750a0000-0000-4000-8000-000000000002",
      interaction_id: "750a0000-0000-4000-8000-000000000003",
      attachment_count: 1,
      total_size_bytes: 7,
      items: [
        {
          attachment_id: "750a0000-0000-4000-8000-000000000004",
          object_ref: "objref:ae-voucher-evidence-0001",
          object_version_ref: "version-0001",
          display_name: "receipt.pdf",
          media_type: "application/pdf",
          size_bytes: 7,
          content_sha256: "a".repeat(64),
          evidence_ref: null
        }
      ],
      attachment_manifest_hash: `sha256:${"b".repeat(64)}`
    });

    assert.equal(manifest.attachment_count, 1);
    assert.equal(manifest.items[0].object_ref, "objref:ae-voucher-evidence-0001");
    assert.deepEqual(Object.keys(manifest).sort(), [
      "attachment_batch_id",
      "attachment_count",
      "attachment_manifest_hash",
      "conversation_id",
      "interaction_id",
      "items",
      "owner_subject_ref",
      "schema_version",
      "tenant_id",
      "total_size_bytes"
    ]);
  });

  it("removes a ready item before lock and rejects a locked mutation", async () => {
    const client = createMockVoucherAttachmentClient();
    const batch = await client.createBatch(CONTEXT);
    const attachmentId = crypto.randomUUID();
    await client.uploadItem(batch.attachment_batch_id, {
      attachmentId,
      file: testFile("receipt.webp", "image/webp", "payload")
    });
    await client.removeItem(batch.attachment_batch_id, attachmentId);
    assert.equal((await client.getBatch(batch.attachment_batch_id)).attachment_count, 0);

    const nextId = crypto.randomUUID();
    await client.uploadItem(batch.attachment_batch_id, {
      attachmentId: nextId,
      file: testFile("receipt.pdf", "application/pdf", "payload")
    });
    await client.finalizeBatch(batch.attachment_batch_id);
    await client.lockBatch(batch.attachment_batch_id);
    await assert.rejects(
      client.removeItem(batch.attachment_batch_id, nextId),
      error => error.status === "VOUCHER_ATTACHMENT_BATCH_LOCKED"
    );
  });

  it("enforces media, file and batch limits before network transfer", () => {
    assert.throws(
      () => assertVoucherAttachmentFile(testFile("script.sh", "text/x-shellscript", "x")),
      VoucherAttachmentClientError
    );
    assert.throws(
      () =>
        assertVoucherAttachmentFile({
          ...testFile("too-large.pdf", "application/pdf", "x"),
          size: MAX_VOUCHER_ATTACHMENT_BATCH_BYTES
        }),
      error => error.status === "VOUCHER_ATTACHMENT_FILE_INVALID"
    );
  });

  it("maps unauthorized fetch responses to immediate session expiry", async () => {
    const client = createFetchVoucherAttachmentClient({
      fetchImpl: async () => ({
        ok: false,
        status: 401,
        async json() {
          return { detail: "expired" };
        }
      })
    });
    await assert.rejects(
      client.getBatch("75a70000-0000-4000-8000-000000000001"),
      error => error.status === "SESSION_EXPIRED" && error.httpStatus === 401
    );
  });

  it("builds only protected AE content routes", () => {
    const route = voucherAttachmentContentRoute(
      "75a70000-0000-4000-8000-000000000001",
      "75a70000-0000-4000-8000-000000000002",
      { download: true }
    );
    assert.equal(
      route,
      "/api/v1/voucher-attachments/batches/75a70000-0000-4000-8000-000000000001/items/75a70000-0000-4000-8000-000000000002/content?download=true"
    );
    assert.doesNotMatch(route, /bucket|object_key|credential|rustfs/i);
  });
});

function testFile(name, type, text) {
  const bytes = new TextEncoder().encode(text);
  return {
    name,
    type,
    size: bytes.byteLength,
    async arrayBuffer() {
      return bytes.buffer.slice(0);
    }
  };
}
