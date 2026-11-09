import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DocumentWorkspacePage } from "./DocumentWorkspacePage";

const DOCUMENT = Object.freeze({
  documentId: "document-1",
  filename: "출장비.pdf",
  contentType: "application/pdf",
  sizeBytes: 4096,
  extractionStatus: "SUCCEEDED",
  summaryStatus: "READY",
  summaryAvailable: true,
  summaryPreview: "NVT 프로젝트 출장비 정산 근거",
  dedupeStatus: "CREATED",
});

describe("Document Workspace page", () => {
  it("renders list, safe detail, processing progress, and duplicate guidance", () => {
    render(<DocumentWorkspacePage
      documents={[DOCUMENT]}
      detail={{
        documentId: "document-1",
        filename: "출장비.pdf",
        processingStatus: "SUCCEEDED",
        extractionStatus: "SUCCEEDED",
        summaryStatus: "READY",
        confidenceBucket: "READY",
      }}
      progress={{ status: "INDEX_READY", progressPercent: 100, terminal: true, retrievalUsable: true, retryable: false }}
      duplicate
    />);
    expect(screen.getByRole("heading", { name: "문서" })).toBeInTheDocument();
    expect(screen.getByText("NVT 프로젝트 출장비 정산 근거")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "문서 상세" })).toBeInTheDocument();
  });

  it("submits selected file and owner-safe document retrieval", async () => {
    const user = userEvent.setup();
    const upload = vi.fn();
    const search = vi.fn();
    render(<DocumentWorkspacePage
      controller={{ refresh: vi.fn(), upload, openDetail: vi.fn(), search }}
      documents={[DOCUMENT]}
      initialTab="upload"
    />);
    const file = new File(["receipt"], "receipt.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("업무에 사용할 파일 선택"), file);
    await user.click(screen.getByRole("button", { name: "파일 첨부" }));
    expect(upload).toHaveBeenCalledWith(file);

    await user.click(screen.getByRole("tab", { name: "문서 근거 찾기" }));
    await user.click(screen.getByRole("checkbox", { name: "출장비.pdf" }));
    await user.type(screen.getByLabelText("찾을 내용"), "교통비 근거");
    await user.click(screen.getByRole("button", { name: "근거 찾기" }));
    expect(search).toHaveBeenCalledWith("교통비 근거", ["document-1"]);
  });

  it("renders no-answer and low-confidence guidance without raw source", async () => {
    const user = userEvent.setup();
    render(<DocumentWorkspacePage
      documents={[DOCUMENT]}
      initialTab="retrieval"
      retrieval={{
        status: "NO_ANSWER",
        evidenceCount: 0,
        confidenceBucket: "LOW",
        warningVisible: true,
        warningTitle: "근거 부족",
        warningMessage: "선택 범위에서 충분한 근거를 찾지 못했습니다.",
        noAnswer: true,
      }}
    />);
    expect(screen.getByText("선택한 문서에서 충분한 근거를 찾지 못했습니다.")).toBeInTheDocument();
    expect(screen.getByText(/근거 부족:/)).toBeInTheDocument();
    expect(screen.queryByText(/storage|provider|source_sha256/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "내 문서 1건" }));
  });
});
