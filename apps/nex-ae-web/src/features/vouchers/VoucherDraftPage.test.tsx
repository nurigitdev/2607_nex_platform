import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BusinessAccountCatalogClientPort } from "../../app/api/businessAccountCatalogClientPort";
import type { BusinessProposal, BusinessProposalClientPort } from "../../app/api/businessProposalClientPort";
import type { BusinessVoucherClientPort, BusinessVoucherDraft } from "../../app/api/businessVoucherClientPort";
import { VoucherDraftPage } from "./VoucherDraftPage";

afterEach(cleanup);

describe("voucher draft review workspace", () => {
  it("shows user-facing codes and requires explicit accounting confirmation", async () => {
    const user = userEvent.setup();
    const submit = vi.fn(async () => ({ state: "READY_FOR_REVIEW" }));
    renderPage(voucherClient({ submit }));
    expect(
      await screen.findByRole("heading", { name: "VO00D260001" }, { timeout: 5_000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /VO00D260001초안/ })).toHaveAttribute(
      "data-candidate-id",
      DRAFT.candidate_id,
    );
    expect(screen.getByLabelText("1번 계정과목")).toHaveValue("510100");
    expect(screen.getByRole("option", { name: "외주비 (510100)" })).toBeInTheDocument();
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
    await screen.findAllByRole("option", { name: "용역비 (510200)" });
    await user.selectOptions(account, "510200");
    await user.click(screen.getByRole("button", { name: "revision 저장" }));
    await waitFor(() => expect(revise).toHaveBeenCalledTimes(1));
    expect(revise.mock.calls[0][1].lines[0].account_code).toBe("510200");
  });

  it("visibly and automatically binds the only approved Project", async () => {
    const user = userEvent.setup();
    const create = vi.fn(async () => DRAFT);
    renderPage(voucherClient({ create }), proposalClient([PROPOSAL]));

    await user.click(screen.getByRole("button", { name: "전표 초안" }));
    expect(await screen.findByLabelText("Project Code")).toHaveValue("VO00D260001");
    expect(screen.getByText("승인된 품의서의 Project가 자동으로 연결됩니다.")).toBeInTheDocument();
    await completeCreationFields(user);
    await user.click(screen.getByRole("button", { name: "초안 생성" }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0].projectCode).toBe("VO00D260001");
  });

  it("requires an explicit approved Project selection for a multi-Project envelope", async () => {
    const user = userEvent.setup();
    const create = vi.fn(async () => DRAFT);
    const multiProject = {
      ...PROPOSAL,
      current_revision: {
        ...PROPOSAL.current_revision,
        scope_type: "PROJECT_SET" as const,
        project_ids: ["project-1", "project-2"],
        project_codes: ["VO00D260001", "VO00D260002"],
      },
    };
    renderPage(voucherClient({ create }), proposalClient([multiProject]));

    await user.click(screen.getByRole("button", { name: "전표 초안" }));
    const createButton = await screen.findByRole("button", { name: "초안 생성" });
    expect(createButton).toBeDisabled();
    await user.selectOptions(screen.getByLabelText(/Project Code/), "VO00D260002");
    await completeCreationFields(user);
    expect(createButton).toBeEnabled();
    await user.click(createButton);

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0].projectCode).toBe("VO00D260002");
  });

  it("blocks an approved proposal that has no Project attribution", async () => {
    const user = userEvent.setup();
    const missingProject = {
      ...PROPOSAL,
      current_revision: {
        ...PROPOSAL.current_revision,
        project_ids: [],
        project_codes: [],
      },
    };
    renderPage(voucherClient(), proposalClient([missingProject]));

    await user.click(screen.getByRole("button", { name: "전표 초안" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("승인된 Project Code가 없는 품의서");
    expect(screen.getByRole("button", { name: "초안 생성" })).toBeDisabled();
  });
});

async function completeCreationFields(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(await screen.findByLabelText("비용 계정과목"), "510100");
  await user.selectOptions(screen.getByLabelText("지급 계정과목"), "110100");
  await user.type(screen.getByLabelText("금액"), "1000");
  await user.type(screen.getByLabelText("증빙 참조"), "expense:51");
}

function renderPage(source: BusinessVoucherClientPort, proposals = proposalClient()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={queryClient}><VoucherDraftPage accountCatalogClient={accountCatalogClient()} client={source} proposalClient={proposals} /></QueryClientProvider>);
}

function accountCatalogClient(): BusinessAccountCatalogClientPort {
  return {
    clientMode: "fetch",
    get: async input => ({
      company_id: input.companyId,
      effective_on: input.effectiveOn,
      transaction_currency: input.transactionCurrency,
      accounts: [
        { account_code: "510100", account_name: "외주비", category: "EXPENSE", account_type: "EXPENSE" },
        { account_code: "510200", account_name: "용역비", category: "EXPENSE", account_type: "EXPENSE" },
        { account_code: "110100", account_name: "현금", category: "ASSET", account_type: "ASSET" },
      ],
    }),
  };
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

function proposalClient(items: readonly BusinessProposal[] = []): BusinessProposalClientPort {
  return {
    clientMode: "fetch",
    list: async () => items,
    get: async () => { throw new Error("unused"); },
    create: async () => { throw new Error("unused"); },
    revise: async () => { throw new Error("unused"); },
    previewApproval: async () => { throw new Error("unused"); },
    selectApprovalLine: async () => ({}),
    submit: async proposal => proposal,
  };
}

const PROPOSAL: BusinessProposal = {
  proposal_id: "c1000000-0000-4000-8000-000000000051",
  company_id: "company-1",
  requester_subject_id: "requester-1",
  state: "APPROVED",
  version: 3,
  current_revision_no: 1,
  approved_envelope_id: "d2000000-0000-4000-8000-000000000051",
  rejection_reason: null,
  journey: {
    schema_version: "eos_business_journey.v1",
    journey_kind: "BUSINESS_PROPOSAL",
    current_stage: "BUSINESS_APPROVED",
    terminal: true,
    approval_stage_count: 1,
    steps: [],
  },
  current_revision: {
    revision_no: 1,
    revision_id: "c2000000-0000-4000-8000-000000000051",
    document_type: "EXPENSE_PROPOSAL",
    work_code: "FL0004011",
    title: "외부 용역비 사용 품의",
    purpose: "외부 용역",
    business_justification: "납기 준수",
    transaction_type: "EXPENSE",
    requested_amount: "1000.0000",
    original_currency: "KRW",
    valid_from: "2026-11-26",
    valid_until: null,
    scope_type: "PROJECT",
    project_ids: ["project-1"],
    project_codes: ["VO00D260001"],
    attachment_manifest: [{ content_hash: "sha256:" + "c".repeat(64) }],
    content_hash: "sha256:" + "d".repeat(64),
  },
};

const DRAFT: BusinessVoucherDraft = {
  candidate_id: "d1000000-0000-4000-8000-000000000051",
  state: "DRAFT",
  version: 2,
  current_revision_no: 2,
  candidate_hash: "sha256:" + "a".repeat(64),
  company_id: "31000000-0000-4000-8000-000000000001",
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
