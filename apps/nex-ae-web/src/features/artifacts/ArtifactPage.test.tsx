import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ArtifactPage } from "./ArtifactPage";

const ITEM = Object.freeze({
  artifactId: "artifact-1",
  displayTitle: "NVT 프로젝트 정산 보고서",
  artifactStatus: "READY",
  primaryFormat: "MD",
  availableFormats: Object.freeze(["MD", "PDF"]),
  previewReady: true,
  downloadReady: true,
  versionCount: 2,
  citationStatus: "VALIDATED",
  evidenceRefCount: 3,
});

const DETAIL = Object.freeze({
  artifactId: "artifact-1",
  displayTitle: "NVT 프로젝트 정산 보고서",
  artifactStatus: "READY",
  currentVersionId: "version-2",
  versions: Object.freeze([
    Object.freeze({ id: "version-2", number: 2, current: true, formats: Object.freeze(["MD", "PDF"]) }),
    Object.freeze({ id: "version-1", number: 1, current: false, formats: Object.freeze(["MD"]) }),
  ]),
  files: Object.freeze([
    Object.freeze({ artifactFileId: "file-1", fileName: "nvt-report.md", format: "MD", previewAvailable: true, downloadAvailable: true }),
  ]),
});

describe("Artifact page", () => {
  it("renders owner-safe result, versions, and preview without technical storage data", () => {
    render(<ArtifactPage items={[ITEM]} selected={DETAIL} preview={{ fileName: "nvt-report.md", format: "MD", text: "# 정산 결과", truncated: false }} />);
    expect(screen.getByRole("heading", { name: "결과물" })).toBeInTheDocument();
    expect(screen.getByText("근거 3건 · 준비됨")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "버전" })).toBeInTheDocument();
    expect(screen.getByText("# 정산 결과")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/storage_ref|ae:\/\/|provider_endpoint|service_token/i);
  });

  it("wires preview, download, export, archive, and delete commands", async () => {
    const user = userEvent.setup();
    const controller = {
      refresh: vi.fn(), select: vi.fn(), preview: vi.fn(), download: vi.fn(),
      lifecycle: vi.fn(), export: vi.fn(),
    };
    render(<ArtifactPage controller={controller} items={[ITEM]} selected={DETAIL} />);
    await user.click(screen.getByRole("button", { name: "미리보기" }));
    await user.click(screen.getByRole("button", { name: "다운로드" }));
    await user.click(screen.getByRole("button", { name: "PDF 만들기" }));
    await user.click(screen.getByRole("button", { name: "보관" }));
    await user.click(screen.getByRole("button", { name: "삭제" }));
    expect(controller.preview).toHaveBeenCalledWith("artifact-1", "file-1");
    expect(controller.download).toHaveBeenCalledWith("file-1");
    expect(controller.export).toHaveBeenCalledWith("artifact-1", ["PDF"]);
    expect(controller.lifecycle).toHaveBeenNthCalledWith(1, "artifact-1", "ARCHIVE");
    expect(controller.lifecycle).toHaveBeenNthCalledWith(2, "artifact-1", "MARK_DELETED");
  });

  it("offers restore for archived results and reports errors", async () => {
    const user = userEvent.setup();
    const lifecycle = vi.fn();
    render(<ArtifactPage
      controller={{ refresh: vi.fn(), select: vi.fn(), preview: vi.fn(), download: vi.fn(), lifecycle, export: vi.fn() }}
      items={[{ ...ITEM, artifactStatus: "ARCHIVED" }]}
      selected={{ ...DETAIL, artifactStatus: "ARCHIVED" }}
      error="결과물을 불러오지 못했습니다."
    />);
    expect(screen.getByRole("alert")).toHaveTextContent("결과물을 불러오지 못했습니다.");
    await user.click(screen.getByRole("button", { name: "복원" }));
    expect(lifecycle).toHaveBeenCalledWith("artifact-1", "RESTORE");
  });
});
