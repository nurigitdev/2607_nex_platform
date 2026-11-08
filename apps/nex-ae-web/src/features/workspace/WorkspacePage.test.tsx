import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { mapWorkState } from "../../ux/workState";
import { WorkspacePage, type WorkspaceController } from "./WorkspacePage";

describe("WorkspacePage", () => {
  it("renders a Korean-default empty workspace without invented recent work", () => {
    render(<WorkspacePage />);

    expect(screen.getByRole("heading", { name: "작업 공간" })).toBeInTheDocument();
    expect(screen.getByText("무엇을 도와드릴까요?")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "최근 작업" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "보내기" })).toBeDisabled();
    expect(screen.queryByText(/workspace-|provider|route|operation/i)).not.toBeInTheDocument();
  });

  it("moves a recommended task into the auto-grow composer", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage />);

    await user.click(screen.getByRole("button", { name: "근거와 함께 질문에 답해 주세요." }));
    const composer = screen.getByRole("textbox", { name: "업무 요청" });
    expect(composer).toHaveValue("근거와 함께 질문에 답해 주세요.");
    fireEvent.input(composer);
    expect((composer as HTMLTextAreaElement).style.height).not.toBe("");
  });

  it("submits a bounded draft and clears the prompt", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue(undefined);
    render(<WorkspacePage controller={{ submit }} />);

    await user.type(screen.getByRole("textbox", { name: "업무 요청" }), "월간 현황을 정리해 주세요.");
    await user.selectOptions(screen.getByRole("combobox", { name: "출력 형식" }), "report");
    await user.click(screen.getByRole("button", { name: "보내기" }));

    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit).toHaveBeenCalledWith({
      prompt: "월간 현황을 정리해 주세요.",
      useEvidence: true,
      outputFormat: "report",
      attachments: [],
    });
    expect(screen.getByRole("textbox", { name: "업무 요청" })).toHaveValue("");
  });

  it("adds, deduplicates, and removes attachment chips", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage controller={{ submit: vi.fn() }} />);
    const input = screen.getByLabelText("파일 선택");
    const file = new File(["receipt"], "교통비-영수증.pdf", { type: "application/pdf" });

    await user.upload(input, [file, file]);
    expect(screen.getAllByText("교통비-영수증.pdf")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: "첨부 1건" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "교통비-영수증.pdf 제거" }));
    expect(screen.queryByText("교통비-영수증.pdf")).not.toBeInTheDocument();
  });

  it("offers cancel only for active work and retry only after failure", async () => {
    const user = userEvent.setup();
    const cancel = vi.fn();
    const retry = vi.fn();
    const controller: WorkspaceController = { submit: vi.fn(), cancel, retry };
    const { rerender } = render(
      <WorkspacePage controller={controller} workState={mapWorkState("RUNNING")} />,
    );

    await user.click(screen.getByRole("button", { name: "처리 취소" }));
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "다시 시도" })).not.toBeInTheDocument();

    rerender(<WorkspacePage controller={controller} workState={mapWorkState("FAILED")} />);
    await user.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(retry).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "처리 취소" })).not.toBeInTheDocument();
  });

  it("renders source-backed conversation, sources, and recent work", async () => {
    const user = userEvent.setup();
    render(
      <WorkspacePage
        messages={[{ id: "m1", role: "assistant", content: "업무를 확인했습니다." }]}
        sources={[{ id: "s1", label: "출장 규정", detail: "문서" }]}
        recentTasks={["지난 월간 현황"]}
      />,
    );

    expect(screen.getByText("업무를 확인했습니다.")).toBeInTheDocument();
    expect(screen.queryByText("지난 월간 현황")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "출처 1건" }));
    expect(screen.getByText("출장 규정")).toBeVisible();
  });

  it("shows a safe retry message when submission fails", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage controller={{ submit: vi.fn().mockRejectedValue(new Error("secret")) }} />);

    await user.type(screen.getByRole("textbox", { name: "업무 요청" }), "실패 경로");
    await user.click(screen.getByRole("button", { name: "보내기" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("다시 시도해 주세요");
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("uses a single-column context layout at tablet and mobile widths", () => {
    const css = readFileSync(resolve(process.cwd(), "src/features/workspace/WorkspacePage.module.css"), "utf8");
    expect(css).toContain("@media (max-width: 980px)");
    expect(css).toContain("grid-template-columns: minmax(0, 1fr)");
    expect(css).toContain("@media (max-width: 560px)");
    expect(css).toContain("flex-direction: column");
  });
});
