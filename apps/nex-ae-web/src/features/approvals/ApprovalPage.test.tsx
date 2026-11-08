import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApprovalClientPort, ApprovalInbox } from "../../app/api/approvalClientPort";
import { createMockApprovalClient } from "../../approvalClient.js";
import { ApprovalPage } from "./ApprovalPage";

afterEach(cleanup);

const NOW = () => new Date("2026-11-08T09:00:00Z");

describe("Approval Inbox React surface", () => {
  it("shows a bounded loading state", () => {
    const pending = new Promise<ApprovalInbox>(() => undefined);
    renderPage(clientWith({ listApprovalGates: () => pending }));

    expect(screen.getByRole("status")).toHaveTextContent("승인 요청을 불러오는 중입니다.");
    expect(screen.getByRole("heading", { name: "승인함" })).toBeInTheDocument();
  });

  it("shows an honest empty state and unsupported history tabs", async () => {
    renderPage(clientWith({ listApprovalGates: async () => emptyInbox() }));

    expect(await screen.findByText("대기 중인 승인 요청이 없습니다")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "완료" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "반려" })).toBeDisabled();
    expect(screen.getByText("완료·반려 이력은 현재 조회 계약에서 제공되지 않습니다.")).toBeInTheDocument();
  });

  it("renders an error and retries the inbox request", async () => {
    const user = userEvent.setup();
    const listApprovalGates = vi
      .fn<ApprovalClientPort["listApprovalGates"]>()
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce(emptyInbox());
    renderPage(clientWith({ listApprovalGates }));

    expect(await screen.findByRole("alert")).toHaveTextContent("승인 요청을 불러오지 못했습니다.");
    await user.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText("대기 중인 승인 요청이 없습니다")).toBeInTheDocument();
    expect(listApprovalGates).toHaveBeenCalledTimes(2);
  });

  it("selects a request and renders source-backed detail without inferred values", async () => {
    const user = userEvent.setup();
    renderPage(mockClient());

    expect(await screen.findByRole("heading", { name: "보호된 WRITE 승인" })).toBeInTheDocument();
    expect(screen.getAllByText("정보 미제공", { selector: "dd" }).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /업무 결재 검토/ }));
    expect(await screen.findByRole("heading", { name: "업무 결재 검토" })).toBeInTheDocument();
    expect(screen.getByText("project-p8-s42")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "업무 결재 진행 단계" })).toBeInTheDocument();
    expect(screen.getByText("요청 역할: TEAM_LEAD")).toBeInTheDocument();
  });

  it("shows attachment evidence counts and keeps technical details collapsed", async () => {
    renderPage(mockClient());

    expect(await screen.findByRole("heading", { name: "보호된 WRITE 승인" })).toBeInTheDocument();
    expect(screen.getByText("2개 · 520 KB")).toBeInTheDocument();
    expect(screen.getByText("교통비-영수증.png")).toBeInTheDocument();
    const technicalDetails = screen.getByText("기술 상세").closest("details");
    expect(technicalDetails).not.toBeNull();
    expect(technicalDetails).not.toHaveAttribute("open");
    expect(technicalDetails).toHaveTextContent("NSL");
  });

  it("marks expired approvals and excludes protected context from the surface", async () => {
    const user = userEvent.setup();
    const view = renderPage(mockClient());

    await screen.findByRole("heading", { name: "보호된 WRITE 승인" });
    await user.click(screen.getByRole("button", { name: /만료된 WRITE 승인/ }));
    expect(await screen.findByRole("heading", { name: "만료된 WRITE 승인" })).toBeInTheDocument();
    expect(screen.getAllByText("만료됨").length).toBeGreaterThan(0);
    expect(view.container.textContent).not.toContain("tenant-local");
    expect(view.container.textContent).not.toContain("owner-local");
    expect(view.container.textContent).not.toContain("source_contract");
    expect(view.container.innerHTML).not.toContain("service_token");
  });
});

function renderPage(client: ApprovalClientPort) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ApprovalPage client={client} now={NOW} />
    </QueryClientProvider>,
  );
}

function mockClient() {
  return createMockApprovalClient({ now: NOW }) as unknown as ApprovalClientPort;
}

function clientWith(
  overrides: Partial<ApprovalClientPort>,
): ApprovalClientPort {
  return {
    ...mockClient(),
    ...overrides,
  };
}

function emptyInbox(): ApprovalInbox {
  return {
    gates: [],
    returned_count: 0,
    scan_truncated: false,
  };
}
