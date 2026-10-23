import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createMockVoucherAttachmentClient } from "../src/voucherAttachmentClient.js";
import {
  createVoucherAttachmentUiController,
  createVoucherAttachmentUiState,
  renderVoucherAttachmentUi
} from "../src/voucherAttachmentUi.js";

describe("AE Web Voucher attachment composer", () => {
  it("uploads multiple files and locks editing at approval submission", async () => {
    const container = fakeContainer();
    const controller = createVoucherAttachmentUiController({
      container,
      client: createMockVoucherAttachmentClient(),
      context: {
        conversationId: "conversation-p8-s75g",
        interactionId: "interaction-p8-s75g"
      }
    });

    await controller.addFiles([
      testFile("영수증.png", "image/png", "receipt"),
      testFile("계약서.pdf", "application/pdf", "contract")
    ]);
    assert.equal(controller.getState().phase, "READY");
    assert.equal(controller.getState().items.length, 2);
    assert.match(container.innerHTML, /data-state="READY"/);

    const manifest = await controller.prepareForSubmission();

    assert.equal(manifest.attachment_count, 2);
    assert.equal(controller.getState().phase, "LOCKED");
    assert.equal(controller.getState().locked, true);
    assert.match(container.innerHTML, /data-voucher-attachment-locked="true"/);
    assert.match(container.innerHTML, /새 승인 버전/);
    assert.match(container.innerHTML, /다운로드/);
    assert.doesNotMatch(container.innerHTML, /object_ref|bucket|rustfs|credential/i);
  });

  it("requires a new approval version before changing locked evidence", async () => {
    const controller = createVoucherAttachmentUiController({
      container: fakeContainer(),
      client: createMockVoucherAttachmentClient(),
      context: {
        conversationId: "conversation-p8-s75g",
        interactionId: "interaction-p8-s75g"
      }
    });
    await controller.addFiles([testFile("receipt.pdf", "application/pdf", "one")]);
    await controller.prepareForSubmission();
    await controller.addFiles([testFile("later.pdf", "application/pdf", "two")]);
    assert.equal(controller.getState().items.length, 1);

    controller.beginNewApprovalVersion();
    assert.equal(controller.getState().approvalVersion, 2);
    assert.equal(controller.getState().items.length, 0);
    assert.equal(controller.getState().locked, false);
  });

  it("does not reuse a locked manifest for a later interaction", async () => {
    let interactionId = "interaction-p8-s75g-first";
    const controller = createVoucherAttachmentUiController({
      container: fakeContainer(),
      client: createMockVoucherAttachmentClient(),
      context: () => ({
        conversationId: "conversation-p8-s75g",
        interactionId
      })
    });
    await controller.addFiles([
      testFile("receipt.pdf", "application/pdf", "receipt")
    ]);
    const first = await controller.prepareForSubmission();

    interactionId = "interaction-p8-s75g-next";
    assert.equal(await controller.prepareForSubmission(), null);
    assert.equal(first.interaction_id, "interaction-p8-s75g-first");
    assert.equal(controller.getState().phase, "LOCKED");
  });

  it("renders a keyboard target and concise responsive state", () => {
    const html = renderVoucherAttachmentUi(createVoucherAttachmentUiState(), {
      contentRoute() {
        throw new Error("content route is not needed for an empty state");
      }
    });
    assert.match(html, /data-voucher-attachment-dropzone/);
    assert.match(html, /role="button"/);
    assert.match(html, /tabindex="0"/);
    assert.match(html, /type="file"/);
    assert.match(html, /multiple/);
  });

  it("returns the caller to login when an attachment request reports expiry", async () => {
    let expired = 0;
    const controller = createVoucherAttachmentUiController({
      container: fakeContainer(),
      client: {
        clientMode: "fetch",
        async createBatch() {
          const error = new Error("expired");
          error.status = "SESSION_EXPIRED";
          error.httpStatus = 401;
          throw error;
        },
        contentRoute() {
          return "/api/v1/voucher-attachments/content";
        }
      },
      context: {
        conversationId: "conversation-p8-s75g",
        interactionId: "interaction-p8-s75g"
      },
      onSessionExpired() {
        expired += 1;
      }
    });
    await controller.addFiles([testFile("receipt.pdf", "application/pdf", "one")]);
    assert.equal(expired, 1);
  });
});

function fakeContainer() {
  return {
    innerHTML: "",
    addEventListener() {},
    querySelector() {
      return null;
    }
  };
}

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
