import { projectBusinessJourney, type BusinessJourney } from "./businessJourney";

export type BusinessProposalState =
  | "DRAFT"
  | "SUBMITTED"
  | "APPROVED"
  | "REJECTED"
  | "WITHDRAWN";

export interface BusinessProposalRevision {
  readonly revision_no: number;
  readonly revision_id: string;
  readonly document_type: string;
  readonly work_code: string;
  readonly title: string;
  readonly purpose: string;
  readonly business_justification: string;
  readonly transaction_type: string;
  readonly requested_amount: string;
  readonly original_currency: string;
  readonly valid_from: string;
  readonly valid_until: string | null;
  readonly scope_type: "COMPANY" | "PROJECT" | "PROJECT_SET";
  readonly project_ids: readonly string[];
  readonly project_codes: readonly string[];
  readonly attachment_manifest: readonly Record<string, unknown>[];
  readonly content_hash: string;
}

export interface BusinessProposal {
  readonly proposal_id: string;
  readonly company_id: string;
  readonly requester_subject_id: string;
  readonly state: BusinessProposalState;
  readonly version: number;
  readonly current_revision_no: number;
  readonly approved_envelope_id: string | null;
  readonly journey: BusinessJourney;
  readonly current_revision: BusinessProposalRevision;
}

export interface ApprovalCandidate {
  readonly subject_id: string;
  readonly display_name: string;
  readonly authority_hash: string;
}

export interface ApprovalStagePreview {
  readonly stage_order: number;
  readonly position_type: string;
  readonly candidates: readonly ApprovalCandidate[];
}

export interface BusinessProposalApprovalPreview {
  readonly preview_hash: string;
  readonly proposal_id: string;
  readonly revision_no: number;
  readonly proposal_version: number;
  readonly effective_at: string;
  readonly required_stages: readonly ApprovalStagePreview[];
  readonly normalized_amount_evidence: {
    readonly normalized_amount: string;
    readonly functional_currency: string;
  };
}

export interface ProposalRevisionCommand {
  readonly proposal_id: string;
  readonly revision_id: string;
  readonly company_id: string;
  readonly document_type: string;
  readonly work_code: string;
  readonly title: string;
  readonly purpose: string;
  readonly business_justification: string;
  readonly transaction_type: string;
  readonly requested_amount: string;
  readonly original_currency: string;
  readonly valid_from: string;
  readonly valid_until: string | null;
  readonly scope_type: "COMPANY" | "PROJECT" | "PROJECT_SET";
  readonly project_ids: readonly string[];
  readonly project_codes: readonly string[];
  readonly attachment_manifest: readonly Record<string, unknown>[];
  readonly expected_version?: number;
  readonly expected_revision?: number;
}

export interface BusinessProposalClientPort {
  readonly clientMode: "mock" | "fetch";
  readonly list: (states?: readonly BusinessProposalState[]) => Promise<readonly BusinessProposal[]>;
  readonly get: (proposalId: string) => Promise<BusinessProposal>;
  readonly create: (command: ProposalRevisionCommand) => Promise<BusinessProposal>;
  readonly revise: (proposalId: string, command: ProposalRevisionCommand) => Promise<BusinessProposal>;
  readonly previewApproval: (
    proposalId: string,
    effectiveAt: string,
  ) => Promise<BusinessProposalApprovalPreview>;
  readonly selectApprovalLine: (
    proposalId: string,
    input: {
      readonly preview: BusinessProposalApprovalPreview;
      readonly selectedApprovers: readonly { readonly stage_order: number; readonly subject_id: string }[];
    },
  ) => Promise<Record<string, unknown>>;
  readonly submit: (
    proposal: BusinessProposal,
    preview: BusinessProposalApprovalPreview,
    selectedApprovers: readonly { readonly stage_order: number; readonly subject_id: string }[],
  ) => Promise<BusinessProposal>;
}

export class BusinessProposalClientError extends Error {
  readonly status: string;
  readonly statusCode: number | null;

  constructor(message: string, status = "BUSINESS_PROPOSAL_REQUEST_FAILED", statusCode: number | null = null) {
    super(message);
    this.name = "BusinessProposalClientError";
    this.status = status;
    this.statusCode = statusCode;
  }
}

export function createBusinessProposalClient({
  mode,
  baseUrl = "",
  fetchImpl,
}: {
  readonly mode: "mock" | "fetch";
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof globalThis.fetch;
}): BusinessProposalClientPort {
  if (mode === "mock") return createMockClient();
  if (typeof fetchImpl !== "function") {
    throw new BusinessProposalClientError("Fetch is unavailable.", "FETCH_UNAVAILABLE");
  }
  const request = async (path: string, init?: RequestInit) => {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      credentials: "include",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      ...init,
    });
    const payload = await readJson(response);
    if (!response.ok) {
      throw new BusinessProposalClientError(
        text(payload.detail, "품의서 요청을 처리하지 못했습니다."),
        text(payload.error_code, "BUSINESS_PROPOSAL_REQUEST_FAILED"),
        response.status,
      );
    }
    return payload;
  };
  const client: BusinessProposalClientPort = {
    clientMode: "fetch" as const,
    async list(states: readonly BusinessProposalState[] = []) {
      const query = new URLSearchParams();
      states.forEach(state => query.append("state", state));
      const payload = await request(`/api/v1/business-proposals${query.size ? `?${query}` : ""}`);
      if (!Array.isArray(payload.items)) throw invalidResponse();
      return payload.items.map(projectProposal);
    },
    async get(proposalId: string) {
      return projectProposal(await request(`/api/v1/business-proposals/${encodeURIComponent(proposalId)}`));
    },
    async create(command: ProposalRevisionCommand) {
      return projectProposal(await request("/api/v1/business-proposals", {
        method: "POST",
        body: JSON.stringify(command),
      }));
    },
    async revise(proposalId: string, command: ProposalRevisionCommand) {
      return projectProposal(await request(`/api/v1/business-proposals/${encodeURIComponent(proposalId)}`, {
        method: "PATCH",
        body: JSON.stringify(command),
      }));
    },
    async previewApproval(proposalId: string, effectiveAt: string) {
      return projectPreview(await request(
        `/api/v1/business-proposals/${encodeURIComponent(proposalId)}:preview-approval`,
        { method: "POST", body: JSON.stringify({ effective_at: effectiveAt }) },
      ));
    },
    async selectApprovalLine(proposalId: string, input: {
      readonly preview: BusinessProposalApprovalPreview;
      readonly selectedApprovers: readonly { readonly stage_order: number; readonly subject_id: string }[];
    }) {
      return request(`/api/v1/business-proposals/${encodeURIComponent(proposalId)}:select-approval-line`, {
        method: "POST",
        body: JSON.stringify({
          effective_at: input.preview.effective_at,
          preview_hash: input.preview.preview_hash,
          revision_no: input.preview.revision_no,
          selected_approvers: input.selectedApprovers,
        }),
      });
    },
    async submit(
      proposal: BusinessProposal,
      preview: BusinessProposalApprovalPreview,
      selectedApprovers: readonly { readonly stage_order: number; readonly subject_id: string }[],
    ) {
      const payload = await request(`/api/v1/business-proposals/${encodeURIComponent(proposal.proposal_id)}:submit`, {
        method: "POST",
        body: JSON.stringify({
          effective_at: preview.effective_at,
          expected_version: proposal.version,
          expected_revision: proposal.current_revision_no,
          preview_hash: preview.preview_hash,
          selected_approvers: selectedApprovers,
        }),
      });
      return projectProposal(payload);
    },
  };
  return Object.freeze(client);
}

function createMockClient(): BusinessProposalClientPort {
  const items: BusinessProposal[] = [];
  const client: BusinessProposalClientPort = {
    clientMode: "mock" as const,
    async list(states: readonly BusinessProposalState[] = []) { return items.filter(item => states.length === 0 || states.includes(item.state)); },
    async get(proposalId: string) { return requiredProposal(items.find(item => item.proposal_id === proposalId)); },
    async create(command: ProposalRevisionCommand) {
      const proposal = proposalFromCommand(command, 1, 1);
      items.push(proposal);
      return proposal;
    },
    async revise(proposalId: string, command: ProposalRevisionCommand) {
      const current = requiredProposal(items.find(item => item.proposal_id === proposalId));
      const revised = proposalFromCommand(command, current.version + 1, current.current_revision_no + 1);
      items.splice(items.indexOf(current), 1, revised);
      return revised;
    },
    async previewApproval(proposalId: string, effectiveAt: string) {
      const proposal = requiredProposal(items.find(item => item.proposal_id === proposalId));
      return {
        preview_hash: "sha256:" + "a".repeat(64),
        proposal_id: proposalId,
        revision_no: proposal.current_revision_no,
        proposal_version: proposal.version,
        effective_at: effectiveAt,
        required_stages: [],
        normalized_amount_evidence: {
          normalized_amount: proposal.current_revision.requested_amount,
          functional_currency: proposal.current_revision.original_currency,
        },
      };
    },
    async selectApprovalLine() { return {}; },
    async submit(proposal: BusinessProposal) { return proposal; },
  };
  return Object.freeze(client);
}

function projectProposal(value: unknown): BusinessProposal {
  if (!isObject(value) || !isObject(value.current_revision)) throw invalidResponse();
  const revision = value.current_revision;
  return Object.freeze({
    proposal_id: text(value.proposal_id),
    company_id: text(value.company_id),
    requester_subject_id: text(value.requester_subject_id),
    state: text(value.state) as BusinessProposalState,
    version: integer(value.version),
    current_revision_no: integer(value.current_revision_no),
    approved_envelope_id: typeof value.approved_envelope_id === "string" ? value.approved_envelope_id : null,
    journey: projectBusinessJourney(value.journey),
    current_revision: Object.freeze({
      revision_no: integer(revision.revision_no),
      revision_id: text(revision.revision_id),
      document_type: text(revision.document_type),
      work_code: text(revision.work_code),
      title: text(revision.title),
      purpose: text(revision.purpose),
      business_justification: text(revision.business_justification),
      transaction_type: text(revision.transaction_type),
      requested_amount: text(revision.requested_amount),
      original_currency: text(revision.original_currency),
      valid_from: text(revision.valid_from),
      valid_until: typeof revision.valid_until === "string" ? revision.valid_until : null,
      scope_type: text(revision.scope_type) as BusinessProposalRevision["scope_type"],
      project_ids: strings(revision.project_ids),
      project_codes: strings(revision.project_codes),
      attachment_manifest: objects(revision.attachment_manifest),
      content_hash: text(revision.content_hash),
    }),
  });
}

function projectPreview(value: unknown): BusinessProposalApprovalPreview {
  if (!isObject(value) || !Array.isArray(value.required_stages) || !isObject(value.normalized_amount_evidence)) {
    throw invalidResponse();
  }
  return {
    preview_hash: text(value.preview_hash),
    proposal_id: text(value.proposal_id),
    revision_no: integer(value.revision_no),
    proposal_version: integer(value.proposal_version),
    effective_at: text(value.effective_at),
    required_stages: value.required_stages.map(stage => {
      if (!isObject(stage) || !Array.isArray(stage.candidates)) throw invalidResponse();
      return {
        stage_order: integer(stage.stage_order),
        position_type: text(stage.position_type),
        candidates: stage.candidates.map(candidate => {
          if (!isObject(candidate)) throw invalidResponse();
          return {
            subject_id: text(candidate.subject_id),
            display_name: text(candidate.display_name),
            authority_hash: text(candidate.authority_hash),
          };
        }),
      };
    }),
    normalized_amount_evidence: {
      normalized_amount: text(value.normalized_amount_evidence.normalized_amount),
      functional_currency: text(value.normalized_amount_evidence.functional_currency),
    },
  };
}

function proposalFromCommand(command: ProposalRevisionCommand, version: number, revisionNo: number): BusinessProposal {
  return {
    proposal_id: command.proposal_id,
    company_id: command.company_id,
    requester_subject_id: "local-user",
    state: "DRAFT",
    version,
    current_revision_no: revisionNo,
    approved_envelope_id: null,
    journey: projectBusinessJourney({
      schema_version: "eos_business_journey.v1",
      journey_kind: "BUSINESS_PROPOSAL",
      current_stage: "PROPOSAL_DRAFT",
      terminal: false,
      approval_stage_count: 0,
      steps: [
        { order: 1, code: "PROPOSAL_DRAFT", label: "품의서 작성", status: "CURRENT" },
        { order: 2, code: "BUSINESS_APPROVAL", label: "품의 결재", status: "UPCOMING" },
        { order: 3, code: "VOUCHER_PREPARATION", label: "전표 작성", status: "UPCOMING" },
      ],
    }),
    current_revision: {
      ...command,
      revision_no: revisionNo,
      content_hash: "sha256:" + "b".repeat(64),
    },
  };
}

function requiredProposal(value: BusinessProposal | undefined) {
  if (!value) throw new BusinessProposalClientError("품의서를 찾을 수 없습니다.", "BUSINESS_PROPOSAL_NOT_FOUND", 404);
  return value;
}
function invalidResponse() { return new BusinessProposalClientError("품의서 응답이 올바르지 않습니다.", "BUSINESS_PROPOSAL_RESPONSE_INVALID"); }
function text(value: unknown, fallback = "") { return typeof value === "string" && value.trim() ? value.trim() : fallback; }
function integer(value: unknown) { if (!Number.isInteger(value)) throw invalidResponse(); return Number(value); }
function strings(value: unknown) { if (!Array.isArray(value) || !value.every(item => typeof item === "string")) throw invalidResponse(); return value; }
function objects(value: unknown) { if (!Array.isArray(value) || !value.every(isObject)) throw invalidResponse(); return value; }
function isObject(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
async function readJson(response: Response): Promise<Record<string, unknown>> { try { const value: unknown = await response.json(); return isObject(value) ? value : {}; } catch { return {}; } }
