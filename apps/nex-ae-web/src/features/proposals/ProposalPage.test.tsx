import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  BusinessProposal,
  BusinessProposalApprovalPreview,
  BusinessProposalClientPort,
} from "../../app/api/businessProposalClientPort";
import { ProposalPage } from "./ProposalPage";

afterEach(cleanup);

describe("proposal review workspace", () => {
  it("shows only user-facing project codes and editable draft fields", async () => {
    const view = renderPage(client());
    expect(await screen.findByRole("heading", { name: "외부 용역비 사용 품의" })).toBeInTheDocument();
    expect(screen.getAllByText("VO00D260001")).toHaveLength(2);
    expect(screen.getByLabelText(/금액/)).toHaveValue("1000000.0000");
    expect(view.container.textContent).not.toContain(PROPOSAL.company_id);
    expect(view.container.textContent).not.toContain(PROPOSAL.current_revision.project_ids[0]);
  });

  it("previews a mandatory line and requires explicit submit confirmation", async () => {
    const user = userEvent.setup();
    const submit = vi.fn(async () => ({ ...PROPOSAL, state: "SUBMITTED" as const }));
    const source = client({ submit });
    renderPage(source);
    await screen.findByRole("heading", { name: "외부 용역비 사용 품의" });
    await user.click(screen.getByRole("button", { name: "결재선 미리보기" }));
    expect(await screen.findByLabelText("1단계 · TEAM_LEAD")).toHaveValue("lead-1");
    await user.click(screen.getByRole("button", { name: "상신" }));
    expect(screen.getByText("현재 revision과 결재선을 잠그고 상신합니다.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "상신 확인" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("품의서를 상신했습니다.")).toBeInTheDocument();
  });
});

function renderPage(source: BusinessProposalClientPort) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={queryClient}><ProposalPage client={source} /></QueryClientProvider>);
}

function client(overrides: Partial<BusinessProposalClientPort> = {}): BusinessProposalClientPort {
  return {
    clientMode: "fetch",
    list: async () => [PROPOSAL],
    get: async () => PROPOSAL,
    create: async () => PROPOSAL,
    revise: async () => PROPOSAL,
    previewApproval: async () => PREVIEW,
    selectApprovalLine: async () => ({}),
    submit: async () => PROPOSAL,
    ...overrides,
  };
}

const PROPOSAL: BusinessProposal = {
  proposal_id: "d1000000-0000-4000-8000-000000000031",
  company_id: "d2000000-0000-4000-8000-000000000031",
  requester_subject_id: "employee-8101",
  state: "DRAFT",
  version: 1,
  current_revision_no: 1,
  approved_envelope_id: null,
  current_revision: {
    revision_no: 1,
    revision_id: "d5000000-0000-4000-8000-000000000031",
    document_type: "EXPENSE_PROPOSAL",
    work_code: "FL0004001",
    title: "외부 용역비 사용 품의",
    purpose: "프로젝트 외부 용역비 집행",
    business_justification: "납기 준수를 위해 필요합니다.",
    transaction_type: "EXTERNAL_LABOR",
    requested_amount: "1000000.0000",
    original_currency: "KRW",
    valid_from: "2026-11-26T09:00:00+00:00",
    valid_until: "2026-12-26T09:00:00+00:00",
    scope_type: "PROJECT",
    project_ids: ["d3000000-0000-4000-8000-000000000031"],
    project_codes: ["VO00D260001"],
    attachment_manifest: [],
    content_hash: "sha256:" + "a".repeat(64),
  },
};

const PREVIEW: BusinessProposalApprovalPreview = {
  preview_hash: "sha256:" + "b".repeat(64),
  proposal_id: PROPOSAL.proposal_id,
  revision_no: 1,
  proposal_version: 1,
  effective_at: "2026-11-26T09:00:00+00:00",
  normalized_amount_evidence: { normalized_amount: "1000000.0000", functional_currency: "KRW" },
  required_stages: [{
    stage_order: 1,
    position_type: "TEAM_LEAD",
    candidates: [{
      subject_id: "lead-1",
      display_name: "김 팀장",
      authority_hash: "sha256:" + "c".repeat(64),
    }],
  }],
};
