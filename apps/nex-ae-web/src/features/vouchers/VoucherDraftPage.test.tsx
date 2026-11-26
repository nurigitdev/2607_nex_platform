import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BusinessProposalClientPort } from "../../app/api/businessProposalClientPort";
import type { BusinessVoucherClientPort, BusinessVoucherDraft } from "../../app/api/businessVoucherClientPort";
import { VoucherDraftPage } from "./VoucherDraftPage";

afterEach(cleanup);

describe("voucher draft review workspace", () => {
  it("shows user-facing codes and requires explicit accounting confirmation", async () => {
    const user = userEvent.setup();
    const submit = vi.fn(async () => ({ state: "READY_FOR_REVIEW" }));
    renderPage(voucherClient({ submit }));
    expect(await screen.findByRole("heading", { name: "VO00D260001" })).toBeInTheDocument();
    expect(screen.getByLabelText("1번 계정과목")).toHaveValue("510100");
    expect(screen.getByRole("navigation", { name: "업무 진행 단계" })).toHaveTextContent("전표 검토진행 중");
    await user.click(screen.getByRole("button", { name: "회계 상신" }));
    expect(screen.getByText("현재 revision을 잠그고 회계 결재를 요청합니다.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "상신 확인" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  });

  it("saves account and amount edits as an immutable revision", async () => {
    const user = userEvent.setup();
    const revise = vi.fn(async () => DRAFT);
    renderPage(voucherClient({ revise }));
    const account = await screen.findByLabelText("1번 계정과목");
    await user.clear(account);
    await user.type(account, "510200");
    await user.click(screen.getByRole("button", { name: "revision 저장" }));
    await waitFor(() => expect(revise).toHaveBeenCalledTimes(1));
    expect(revise.mock.calls[0][1].lines[0].account_code).toBe("510200");
  });
});

function renderPage(source: BusinessVoucherClientPort) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={queryClient}><VoucherDraftPage client={source} proposalClient={proposalClient()} /></QueryClientProvider>);
}

function voucherClient(overrides: Partial<BusinessVoucherClientPort> = {}): BusinessVoucherClientPort {
  return {
    clientMode: "fetch",
    list: async () => [DRAFT],
    get: async () => DRAFT,
    create: async () => DRAFT,
    revise: async () => DRAFT,
    validate: async () => ({ status: "PASS" }),
    submit: async () => ({ state: "READY_FOR_REVIEW" }),
    ...overrides,
  };
}

function proposalClient(): BusinessProposalClientPort {
  return {
    clientMode: "fetch",
    list: async () => [],
    get: async () => { throw new Error("unused"); },
    create: async () => { throw new Error("unused"); },
    revise: async () => { throw new Error("unused"); },
    previewApproval: async () => { throw new Error("unused"); },
    selectApprovalLine: async () => ({}),
    submit: async proposal => proposal,
  };
}

const DRAFT: BusinessVoucherDraft = {
  candidate_id: "d1000000-0000-4000-8000-000000000051",
  state: "DRAFT",
  version: 2,
  current_revision_no: 2,
  candidate_hash: "sha256:" + "a".repeat(64),
  project_code: "VO00D260001",
  recognition_date: "2026-11-26",
  transaction_currency: "KRW",
  source_kind: "EXPENSE_CLAIM",
  source_record_ref: "expense:51",
  business_work_code: "FL0004011",
  document_envelope_id: "d2000000-0000-4000-8000-000000000051",
  journey: {
    schema_version: "eos_business_journey.v1",
    journey_kind: "ACCOUNTING_VOUCHER",
    current_stage: "VOUCHER_REVIEW",
    terminal: false,
    approval_stage_count: null,
    steps: [
      { order: 1, code: "VOUCHER_REVIEW", label: "전표 검토", status: "CURRENT" },
      { order: 2, code: "ACCOUNTING_APPROVAL", label: "회계 결재", status: "UPCOMING" },
      { order: 3, code: "JOURNAL_POSTING", label: "총계정원장 반영", status: "UPCOMING" },
    ],
  },
  approved_document: { approved_document_id: "proposal-51", approved_amount: "1000.0000", remaining_amount: "1000.0000", attachment_manifest_hash: "sha256:" + "b".repeat(64) },
  lines: [
    { line_no: 1, account_code: "510100", account_name: "외주비", debit_original: "1000.0000", credit_original: "0.0000", source_record_line_ref: "expense:51:1", description: "외주비", evidence_hash: "sha256:" + "c".repeat(64) },
    { line_no: 2, account_code: "110100", account_name: "현금", debit_original: "0.0000", credit_original: "1000.0000", source_record_line_ref: "expense:51:2", description: "지급", evidence_hash: "sha256:" + "c".repeat(64) },
  ],
  balance: { debit: "1000.0000", credit: "1000.0000", balanced: true },
};
