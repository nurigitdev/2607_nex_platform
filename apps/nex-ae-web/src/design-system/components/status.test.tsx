import { FileQuestion } from "lucide-react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./controls";
import { Avatar, Badge, EmptyState, StatusPill, Stepper, Toast } from "./status";

describe("design system status and feedback", () => {
  it("keeps status meaning visible as icon and text", () => {
    render(<><Badge tone="warning">주의</Badge><StatusPill tone="success">승인됨</StatusPill></>);
    expect(screen.getByText("주의")).toBeInTheDocument();
    expect(screen.getByText("승인됨").parentElement?.querySelector("svg")).not.toBeNull();
  });

  it("announces toast severity and supports dismissal", async () => {
    const dismiss = vi.fn();
    const user = userEvent.setup();
    render(<Toast title="저장 실패" description="다시 시도하세요" tone="danger" onDismiss={dismiss} />);
    expect(screen.getByRole("alert")).toHaveTextContent("저장 실패");
    await user.click(screen.getByRole("button", { name: "알림 닫기" }));
    expect(dismiss).toHaveBeenCalledOnce();
  });

  it("marks only the current step and preserves all labels", () => {
    render(<Stepper items={[
      { id: "one", label: "요청", state: "complete" },
      { id: "two", label: "승인", state: "current" },
      { id: "three", label: "완료", state: "pending" },
    ]} />);
    expect(screen.getByText("승인").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("renders useful empty and identity states", () => {
    render(<><EmptyState icon={FileQuestion} title="결과 없음" description="조건을 변경하세요" action={<Button>초기화</Button>} /><Avatar name="홍 길동" /></>);
    expect(screen.getByText("결과 없음")).toBeInTheDocument();
    expect(screen.getByLabelText("홍 길동")).toHaveTextContent("홍길");
  });
});
