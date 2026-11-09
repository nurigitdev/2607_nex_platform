import { Inbox } from "lucide-react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Card, DataTable, List } from "./layout";
import { NavItem, Tabs } from "./navigation";

describe("design system navigation and data display", () => {
  it("supports keyboard tab selection with count and disabled state", async () => {
    const user = userEvent.setup();
    render(<Tabs label="승인 분류" defaultValue="pending" items={[
      { id: "pending", label: "대기", count: 2, content: <p>대기 목록</p> },
      { id: "done", label: "완료", content: <p>완료 목록</p> },
      { id: "blocked", label: "차단", disabled: true, content: null },
    ]} />);
    const pending = screen.getByRole("tab", { name: "대기 2건" });
    pending.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "완료" })).toHaveAttribute("data-state", "active");
    expect(screen.getByText("완료 목록")).toBeVisible();
    expect(screen.getByRole("tab", { name: "차단" })).toBeDisabled();
  });

  it("exposes current navigation without hiding its text label", () => {
    render(<NavItem href="#approvals" label="승인함" icon={<Inbox />} active count={3} />);
    const link = screen.getByRole("link", { name: "승인함 3건" });
    expect(link).toHaveAttribute("aria-current", "page");
  });

  it("renders bounded cards, lists, and accessible tables", () => {
    render(<Card aria-label="요약"><List label="작업"><li>검토</li></List><DataTable caption="승인 요청" rows={[{ id: "A1", status: "대기" }]} rowKey={row => row.id} columns={[
      { key: "id", header: "ID", cell: row => row.id },
      { key: "status", header: "상태", cell: row => row.status },
    ]} /></Card>);
    expect(screen.getByRole("region", { name: "승인 요청" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "상태" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "작업" })).toBeInTheDocument();
  });
});
