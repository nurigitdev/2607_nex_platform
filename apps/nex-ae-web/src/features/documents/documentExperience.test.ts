import { describe, expect, it, vi } from "vitest";

import {
  searchDocumentEvidence,
  submitDocumentUpload,
} from "./documentExperience";

const FILE = new File(["evidence"], "receipt.pdf", { type: "application/pdf" });
const DOCUMENT = Object.freeze({
  documentId: "document-1",
  filename: "receipt.pdf",
  contentType: "application/pdf",
  sizeBytes: 8,
  extractionStatus: "SUCCEEDED",
  summaryStatus: "READY",
  summaryAvailable: true,
  summaryPreview: "교통비 영수증",
  dedupeStatus: "CREATED",
});

describe("document upload and retrieval experience", () => {
  it("uploads owner-scoped file content and reaches retrieval-ready progress", async () => {
    const submitUploadDraft = vi.fn(async (draft, options) => ({
      uploadHandoffId: "handoff-1",
      documentId: "document-1",
      dedupeStatus: "CREATED",
      draft,
      file: options.file,
    }));
    const updates: string[] = [];
    const result = await submitDocumentUpload({
      file: FILE,
      workspaceId: "workspace-1",
      tenantId: "VO00",
      ownerUserId: "subject-1",
      uploadClient: { submitUploadDraft },
      progressClient: {
        clientMode: "mock",
        async getProgress() {
          return {
            status: "INDEX_READY",
            progressPercent: 100,
            terminal: true,
            vectorIndex: { retrievalUsable: true },
            failure: { retryable: false },
          };
        },
      },
      onProgress: progress => updates.push(progress.status),
    });

    expect(result).toMatchObject({
      documentId: "document-1",
      dedupeStatus: "CREATED",
      progress: { retrievalUsable: true },
    });
    expect(updates).toEqual(["INDEX_READY"]);
    expect(submitUploadDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        workspaceId: "workspace-1",
        ownerScope: expect.objectContaining({ tenantId: "VO00", ownerUserId: "subject-1" }),
      }),
      { file: FILE },
    );
  });

  it("preserves duplicate outcome and fails closed at a bounded poll limit", async () => {
    const base = {
      file: FILE,
      workspaceId: "workspace-1",
      tenantId: "VO00",
      ownerUserId: "subject-1",
      uploadClient: {
        async submitUploadDraft() {
          return { uploadHandoffId: "handoff-1", documentId: "document-1", dedupeStatus: "DUPLICATE" };
        },
      },
    } as const;
    const duplicate = await submitDocumentUpload({
      ...base,
      progressClient: {
        clientMode: "mock",
        async getProgress() {
          return { status: "INDEX_READY", progressPercent: 100, terminal: true, vectorIndex: { retrievalUsable: true }, failure: {} };
        },
      },
    });
    expect(duplicate.dedupeStatus).toBe("DUPLICATE");

    await expect(submitDocumentUpload({
      ...base,
      maxPolls: 1,
      progressClient: {
        clientMode: "mock",
        async getProgress() {
          return { status: "PROCESSING", progressPercent: 40, terminal: false, vectorIndex: {}, failure: {} };
        },
      },
    })).rejects.toMatchObject({ status: "UPLOAD_PROGRESS_TIMEOUT", retryable: true });
  });

  it("builds selected-document retrieval and surfaces low-confidence/no-answer", async () => {
    const submitRetrievalRequest = vi.fn(async (request) => ({
      cxStatus: "NO_ANSWER",
      evidenceCount: 0,
      confidenceBucket: "LOW",
      qualityWarnings: {
        recommended_action: "show_no_answer",
        warning_count: 0,
        quality_flag_count: 1,
      },
      request,
    }));
    const result = await searchDocumentEvidence({
      query: "교통비 근거",
      conversationId: "conversation-1",
      documents: [DOCUMENT],
      selectedDocumentIds: ["document-1"],
      retrievalClient: { submitRetrievalRequest },
    });
    expect(result).toMatchObject({ noAnswer: true, evidenceCount: 0, warningVisible: true });
    expect(submitRetrievalRequest).toHaveBeenCalledWith(expect.objectContaining({
      retrieval: expect.objectContaining({ document_scope: { document_ids: ["document-1"] } }),
    }));
  });
});
