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
    const progress = screen.getByRole("list", { name: "업무 결재 진행 단계" });
    expect(progress).toBeInTheDocument();
    expect(screen.getByText("1단계 현재 결재").closest("li")).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByText("2단계 대기").closest("li")).not.toHaveAttribute(
      "aria-current",
    );
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
    expect(screen.queryByRole("button", { name: /^승인$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^반려$/ })).toBeNull();
  });

  it("confirms approval, shows the result, and advances to the next request", async () => {
    const user = userEvent.setup();
    const base = mockClient();
    const submitApprovalDecision = vi.fn(base.submitApprovalDecision);
    renderPage({ ...base, submitApprovalDecision });

    await screen.findByRole("heading", { name: "보호된 WRITE 승인" });
    await user.click(screen.getByRole("button", { name: /^승인$/ }));
    expect(screen.getByRole("alertdialog")).toHaveAccessibleName("이 요청을 승인하시겠습니까?");
    await user.click(screen.getByRole("button", { name: "승인 확정" }));

    const resultHeading = await screen.findByRole("heading", { name: "결정이 기록되었습니다" });
    expect(resultHeading.closest('[role="status"]')).toHaveTextContent("승인됨");
    expect(resultHeading.closest('[role="status"]')).toHaveFocus();
    expect(screen.getByText("승인됨")).toBeInTheDocument();
    expect(submitApprovalDecision).toHaveBeenCalledWith(
      "42000000-0000-4000-8000-000000000001",
      expect.objectContaining({ decision: "APPROVE", decision_comment: null }),
    );
    await user.click(screen.getByRole("button", { name: "다음 요청 검토" }));
    expect(await screen.findByRole("heading", { name: "Agent 공식 작업 승인" })).toBeInTheDocument();
  });

  it("requires a rejection reason and confirms a rejection accessibly", async () => {
    const user = userEvent.setup();
    const base = mockClient();
    const submitApprovalDecision = vi.fn(base.submitApprovalDecision);
    renderPage({ ...base, submitApprovalDecision });

    await screen.findByRole("heading", { name: "보호된 WRITE 승인" });
    const reject = screen.getByRole("button", { name: /^반려$/ });
    expect(reject).toBeDisabled();
    const reason = screen.getByLabelText(/반려 사유/);
    await user.click(reason);
    await user.tab();
    expect(screen.getByText("반려 사유를 입력해 주세요.")).toBeInTheDocument();
    await user.type(reason, "증빙 금액을 다시 확인해 주세요.");
    expect(reject).toBeEnabled();
    await user.click(reject);
    expect(screen.getByRole("alertdialog")).toHaveAccessibleDescription(
      "입력한 사유가 요청자에게 결정 근거로 전달됩니다.",
    );
    await user.click(screen.getByRole("button", { name: "반려 확정" }));
    expect(await screen.findByText("반려됨")).toBeInTheDocument();
    expect(submitApprovalDecision).toHaveBeenCalledWith(
      "42000000-0000-4000-8000-000000000001",
      expect.objectContaining({
        decision: "REJECT",
        decision_comment: "증빙 금액을 다시 확인해 주세요.",
      }),
    );
  });

  it.each([
    ["APPROVAL_DECISION_CONFLICT", 409, false, "다른 결정이 이미 기록되었습니다."],
    ["APPROVAL_DECISION_UNAUTHORIZED", 403, false, "현재 계정에 승인 권한이 없습니다."],
    ["APPROVAL_SERVER_ERROR", 503, true, "일시적인 오류가 발생했습니다."],
  ])("maps %s decision failures to safe guidance", async (status, httpStatus, retryable, expected) => {
    const user = userEvent.setup();
    const error = Object.assign(new Error("protected backend detail"), {
      status,
      httpStatus,
      retryable,
    });
    const client = clientWith({
      submitApprovalDecision: vi.fn(async () => { throw error; }),
    });
    renderPage(client);

    await screen.findByRole("heading", { name: "보호된 WRITE 승인" });
    await user.click(screen.getByRole("button", { name: /^승인$/ }));
    await user.click(screen.getByRole("button", { name: "승인 확정" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(expected);
    expect(alert).not.toHaveTextContent("protected backend detail");
  });

  it("shows only authoritative risk and exposes safe attachment access routes", async () => {
    const base = mockClient();
    const getApprovalProjection = vi.fn(async (gateId: string) => ({
      ...(await base.getApprovalProjection(gateId)),
      risk: { status: "AVAILABLE" as const, level: "HIGH" as const, explanation: "고액 지출 검토" },
    }));
    renderPage({ ...base, getApprovalProjection });

    await screen.findByRole("heading", { name: "보호된 WRITE 승인" });
    expect(screen.getAllByText("높음")).toHaveLength(2);
    expect(screen.getByText("고액 지출 검토")).toBeInTheDocument();
    expect(screen.queryByText("HIGH")).toBeNull();
    const open = screen.getByRole("link", { name: "교통비-영수증.png 열기" });
    const download = screen.getByRole("link", { name: "교통비-영수증.png 다운로드" });
    expect(open).toHaveAttribute("href", expect.stringMatching(/^\/api\/v1\/approval-gates\//));
    expect(open).toHaveAttribute("target", "_blank");
    expect(download).toHaveAttribute("href", expect.stringContaining("download=true"));
    expect(download).toHaveAttribute("download");
  });

  it("renders an authoritative voucher-shaped accounting document", async () => {
    const base = mockClient();
    const getApprovalProjection = vi.fn(async (gateId: string) => ({
      ...(await base.getApprovalProjection(gateId)),
      accounting_document: {
        schema_version: "ae_accounting_document_projection.v1" as const,
        status: "AVAILABLE" as const,
        diagnostic_code: null,
        header: {
          project_code: "T001D260001",
          company_id: "company-1",
          approved_document_ref: "eos.approved-document-envelope:one",
          recognition_date: "2026-11-27",
          currency: "KRW",
          requester_subject_id: "employee-1001",
        },
        lines: [
          { line_no: 1, account_code: "520100", account_name: "외주인건비", description: "외주 인건비", debit: "125000.0000", credit: "0.0000", currency: "KRW" },
          { line_no: 2, account_code: "210200", account_name: "미지급금", description: null, debit: "0.0000", credit: "125000.0000", currency: "KRW" },
        ],
        totals: { debit: "125000.0000", credit: "125000.0000", difference: "0.0000", balanced: true },
        lineage: { candidate_id: "84000000-0000-4000-8000-000000000053", candidate_revision: 3, candidate_hash: `sha256:${"b".repeat(64)}`, approval_case_id: "case-1" },
      },
    }));
    renderPage({ ...base, getApprovalProjection });

    expect(await screen.findByRole("heading", { name: "전표 검토" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveTextContent("외주인건비");
    expect(screen.getByRole("table")).toHaveTextContent("미지급금");
    expect(screen.getByText(/Candidate rev\. 3/)).toHaveTextContent("차대변 일치");
    expect(screen.getByText("T001D260001")).toBeInTheDocument();
  });

  it("shows a bounded diagnostic when the accounting join is unavailable", async () => {
    const base = mockClient();
    const getApprovalProjection = vi.fn(async (gateId: string) => ({
      ...(await base.getApprovalProjection(gateId)),
      accounting_document: {
        schema_version: "ae_accounting_document_projection.v1" as const,
        status: "UNAVAILABLE" as const,
        diagnostic_code: "ae.eos_accounting_display_rejected",
        header: null,
        lines: [],
        totals: null,
        lineage: null,
      },
    }));
    renderPage({ ...base, getApprovalProjection });

    expect(await screen.findByText(/권위 있는 전표 원문/)).toHaveTextContent(
      "권위 있는 전표 원문을 확인할 수 없습니다.",
    );
    expect(screen.queryByText("ae.eos_accounting_display_rejected")).toBeNull();
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
