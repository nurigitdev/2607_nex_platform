import { HelpCircle } from "lucide-react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button, IconButton } from "./controls";
import { ConfirmDialog, Drawer, Modal, Tooltip } from "./overlays";

function ControlledModal({ drawer = false }: { readonly drawer?: boolean }) {
  const [open, setOpen] = useState(true);
  const Surface = drawer ? Drawer : Modal;
  return <Surface open={open} onOpenChange={setOpen} title={drawer ? "상세" : "승인 확인"} description="내용을 검토하세요"><p>본문</p></Surface>;
}

describe("design system overlays", () => {
  it("closes modal with Escape and restores controlled state", async () => {
    const user = userEvent.setup();
    render(<ControlledModal />);
    expect(screen.getByRole("dialog", { name: "승인 확인" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("provides a labelled drawer and explicit close command", async () => {
    const user = userEvent.setup();
    render(<ControlledModal drawer />);
    expect(screen.getByRole("dialog", { name: "상세" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("requires confirmation before a destructive command", async () => {
    const confirm = vi.fn();
    const user = userEvent.setup();
    render(<ConfirmDialog trigger={<Button>삭제 요청</Button>} title="삭제할까요?" description="되돌릴 수 없습니다" confirmLabel="삭제" destructive onConfirm={confirm} />);
    await user.click(screen.getByRole("button", { name: "삭제 요청" }));
    expect(screen.getByRole("alertdialog", { name: "삭제할까요?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "삭제" }));
    expect(confirm).toHaveBeenCalledOnce();
  });

  it("keeps unfamiliar icon commands labelled when wrapped by a tooltip", () => {
    render(<Tooltip content="도움말" trigger={<IconButton label="도움말 열기" icon={<HelpCircle />} />} />);
    expect(screen.getByRole("button", { name: "도움말 열기" })).toBeInTheDocument();
  });
});
