import { Save } from "lucide-react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button, Checkbox, IconButton, Input, Radio, Select, Textarea } from "./controls";

describe("design system controls", () => {
  it("supports command variants, disabled state, focus, and loading", async () => {
    const user = userEvent.setup();
    const action = vi.fn();
    render(<Button variant="danger" onClick={action}>삭제</Button>);
    const button = screen.getByRole("button", { name: "삭제" });

    await user.tab();
    expect(button).toHaveFocus();
    await user.click(button);
    expect(action).toHaveBeenCalledOnce();

    cleanupAndRender(<Button loading>저장</Button>);
    expect(screen.getByRole("button", { name: "저장" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "저장" })).toHaveAttribute("aria-busy", "true");
  });

  it("requires an accessible name for icon-only commands", () => {
    render(<IconButton label="저장" icon={<Save aria-hidden="true" />} />);
    expect(screen.getByRole("button", { name: "저장" })).toBeInTheDocument();
    expect(() => render(<IconButton label=" " icon={<Save />} />)).toThrow(
      "IconButton requires an accessible label",
    );
  });

  it("connects labels, descriptions, and invalid state to form controls", () => {
    render(
      <>
        <Input label="사번" error="사번을 확인하세요" />
        <Select label="상태" defaultValue="ready"><option value="ready">준비</option></Select>
        <Textarea label="설명" hint="간단히 입력하세요" />
      </>,
    );

    const input = screen.getByLabelText("사번");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("사번을 확인하세요");
    expect(screen.getByLabelText("상태")).toHaveValue("ready");
    expect(screen.getByLabelText("설명")).toHaveAccessibleDescription("간단히 입력하세요");
  });

  it("supports native keyboard-safe checkbox and radio choices", async () => {
    const user = userEvent.setup();
    render(
      <>
        <Checkbox label="알림 받기" />
        <Radio label="직접 승인" name="approval" value="direct" />
      </>,
    );
    const checkbox = screen.getByRole("checkbox", { name: "알림 받기" });
    await user.click(checkbox);
    expect(checkbox).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "직접 승인" }));
    expect(screen.getByRole("radio", { name: "직접 승인" })).toBeChecked();
  });
});

function cleanupAndRender(node: React.ReactNode) {
  document.body.replaceChildren();
  return render(node);
}
