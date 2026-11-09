import { describe, expect, it, vi } from "vitest";

import {
  createDocumentLibraryClient,
  projectDocumentLibraryItem,
} from "./documentLibraryClientPort";

const ITEM = Object.freeze({
  document_library_schema_version: "ae_document_library_item.v1",
  document_id: "document-1",
  filename: "출장비.pdf",
  content_type: "application/pdf",
  size_bytes: 1200,
  status: {
    dedupe_status: "CREATED",
    extraction_status: "SUCCEEDED",
    summary_status: "READY",
  },
  summary: { summary_available: true, summary_preview: "출장비 정산 근거입니다." },
  metadata: { cx_storage_redacted: true },
});

describe("owner-scoped document library client", () => {
  it("projects only the display-safe document surface", () => {
    expect(projectDocumentLibraryItem({ ...ITEM, source_sha256: "secret-hash" })).toEqual({
      documentId: "document-1",
      filename: "출장비.pdf",
      contentType: "application/pdf",
      sizeBytes: 1200,
      extractionStatus: "SUCCEEDED",
      summaryStatus: "READY",
      summaryAvailable: true,
      summaryPreview: "출장비 정산 근거입니다.",
      dedupeStatus: "CREATED",
    });
  });

  it("uses a same-origin owner-scoped list route", async () => {
    const fetchImpl = vi.fn<typeof globalThis.fetch>(async () => new Response(JSON.stringify({
      workspace_id: "workspace-1",
      documents: [ITEM],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const client = createDocumentLibraryClient({ mode: "fetch", baseUrl: "/ae-api", fetchImpl });
    await expect(client.listWorkspaceDocuments("workspace-1")).resolves.toHaveLength(1);
    expect(fetchImpl).toHaveBeenCalledWith(
      "/ae-api/api/v1/workspaces/workspace-1/documents",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("fails closed for wrong-owner and malformed responses", async () => {
    const denied = createDocumentLibraryClient({
      mode: "fetch",
      fetchImpl: async () => new Response(JSON.stringify({
        error_code: "ae.browser_owner_scope_mismatch",
        detail: "private owner detail",
      }), { status: 403, headers: { "Content-Type": "application/json" } }),
    });
    await expect(denied.listWorkspaceDocuments("workspace-1")).rejects.toMatchObject({
      statusCode: 403,
      message: "문서 목록을 불러오지 못했습니다.",
    });
    expect(() => projectDocumentLibraryItem({ ...ITEM, document_id: "../private" })).toThrow();
  });
});
