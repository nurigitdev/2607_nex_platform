import { projectBusinessJourney, type BusinessJourney } from "./businessJourney";

export type BusinessVoucherState =
  | "DRAFT"
  | "READY_FOR_REVIEW"
  | "RETURNED_FOR_CORRECTION"
  | "APPROVED"
  | "POSTED"
  | "INVALIDATED";

export interface BusinessVoucherLine {
  readonly line_no: number;
  readonly account_code: string;
  readonly account_name: string;
  readonly debit_original: string;
  readonly credit_original: string;
  readonly source_record_line_ref: string;
  readonly description: string | null;
  readonly evidence_hash: string;
}

export interface BusinessVoucherDraft {
  readonly candidate_id: string;
  readonly state: BusinessVoucherState;
  readonly version: number;
  readonly current_revision_no: number;
  readonly candidate_hash: string;
  readonly project_code: string;
  readonly recognition_date: string;
  readonly transaction_currency: string;
  readonly source_kind: string;
  readonly source_record_ref: string;
  readonly business_work_code: string;
  readonly document_envelope_id: string;
  readonly journey: BusinessJourney;
  readonly approved_document: {
    readonly approved_document_id: string;
    readonly approved_amount: string;
    readonly remaining_amount: string;
    readonly attachment_manifest_hash: string;
  } | null;
  readonly lines: readonly BusinessVoucherLine[];
  readonly balance: {
    readonly debit: string;
    readonly credit: string;
    readonly balanced: boolean;
  };
}

export interface BusinessVoucherClientPort {
  readonly clientMode: "mock" | "fetch";
  readonly list: (states?: readonly BusinessVoucherState[]) => Promise<readonly BusinessVoucherDraft[]>;
  readonly get: (candidateId: string) => Promise<BusinessVoucherDraft>;
  readonly create: (input: {
    readonly envelopeId: string;
    readonly projectCode: string;
    readonly recognitionDate: string;
    readonly sourceKind: string;
    readonly sourceRecordRef: string;
    readonly lines: readonly Omit<BusinessVoucherLine, "line_no" | "account_name">[];
  }) => Promise<BusinessVoucherDraft>;
  readonly revise: (
    draft: BusinessVoucherDraft,
    input: { readonly recognitionDate: string; readonly lines: readonly BusinessVoucherLine[] },
  ) => Promise<BusinessVoucherDraft>;
  readonly validate: (draft: BusinessVoucherDraft) => Promise<Record<string, unknown>>;
  readonly submit: (draft: BusinessVoucherDraft) => Promise<Record<string, unknown>>;
}

export class BusinessVoucherClientError extends Error {
  readonly status: string;
  readonly statusCode: number | null;

  constructor(message: string, status = "BUSINESS_VOUCHER_REQUEST_FAILED", statusCode: number | null = null) {
    super(message);
    this.name = "BusinessVoucherClientError";
    this.status = status;
    this.statusCode = statusCode;
  }
}

export function createBusinessVoucherClient({
  mode,
  baseUrl = "",
  fetchImpl,
}: {
  readonly mode: "mock" | "fetch";
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof globalThis.fetch;
}): BusinessVoucherClientPort {
  if (mode === "mock") return createMockClient();
  if (typeof fetchImpl !== "function") {
    throw new BusinessVoucherClientError("Fetch is unavailable.", "FETCH_UNAVAILABLE");
  }
  const request = async (path: string, init?: RequestInit) => {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      credentials: "include",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      ...init,
    });
    const payload = await readJson(response);
    if (!response.ok) {
      throw new BusinessVoucherClientError(
        text(payload.detail, "전표 요청을 처리하지 못했습니다."),
        text(payload.error_code, "BUSINESS_VOUCHER_REQUEST_FAILED"),
        response.status,
      );
    }
    return payload;
  };
  const client: BusinessVoucherClientPort = {
    clientMode: "fetch" as const,
    async list(states: readonly BusinessVoucherState[] = []) {
      const query = new URLSearchParams();
      states.forEach(state => query.append("state", state));
      const payload = await request(`/api/v1/business-voucher-drafts${query.size ? `?${query}` : ""}`);
      if (!Array.isArray(payload.items)) throw invalidResponse();
      return payload.items.map(projectDraft);
    },
    async get(candidateId: string) {
      return projectDraft(await request(`/api/v1/business-voucher-drafts/${encodeURIComponent(candidateId)}`));
    },
    async create(input) {
      return projectDraft(await request("/api/v1/business-voucher-drafts", {
        method: "POST",
        body: JSON.stringify({
          client_command_id: crypto.randomUUID(),
          envelope_id: input.envelopeId,
          project_code: input.projectCode,
          recognition_date: input.recognitionDate,
          source_kind: input.sourceKind,
          source_record_ref: input.sourceRecordRef,
          lines: input.lines,
        }),
      }));
    },
    async revise(draft, input) {
      return projectDraft(await request(`/api/v1/business-voucher-drafts/${encodeURIComponent(draft.candidate_id)}`, {
        method: "PATCH",
        body: JSON.stringify({
          client_command_id: crypto.randomUUID(),
          expected_version: draft.version,
          expected_revision: draft.current_revision_no,
          expected_candidate_hash: draft.candidate_hash,
          recognition_date: input.recognitionDate,
          lines: input.lines.map(line => ({
            account_code: line.account_code,
            debit_original: line.debit_original,
            credit_original: line.credit_original,
            source_record_line_ref: line.source_record_line_ref,
            description: line.description,
            evidence_hash: line.evidence_hash,
          })),
        }),
      }));
    },
    async validate(draft) {
      return request(`/api/v1/business-voucher-drafts/${encodeURIComponent(draft.candidate_id)}:validate`, {
        method: "POST",
        body: JSON.stringify({ as_of: new Date().toISOString() }),
      });
    },
    async submit(draft) {
      return request(`/api/v1/business-voucher-drafts/${encodeURIComponent(draft.candidate_id)}:submit-for-accounting`, {
        method: "POST",
        body: JSON.stringify({
          client_command_id: crypto.randomUUID(),
          expected_version: draft.version,
          expected_revision: draft.current_revision_no,
          expected_candidate_hash: draft.candidate_hash,
          confirmed: true,
        }),
      });
    },
  };
  return Object.freeze(client);
}

function createMockClient(): BusinessVoucherClientPort {
  const items: BusinessVoucherDraft[] = [];
  const client: BusinessVoucherClientPort = {
    clientMode: "mock" as const,
    async list(states: readonly BusinessVoucherState[] = []) {
      return items.filter(item => states.length === 0 || states.includes(item.state));
    },
    async get(candidateId: string) {
      const found = items.find(item => item.candidate_id === candidateId);
      if (!found) throw new BusinessVoucherClientError("전표 초안을 찾을 수 없습니다.", "NOT_FOUND", 404);
      return found;
    },
    async create() { throw new BusinessVoucherClientError("Mock draft creation requires a seeded approval."); },
    async revise(draft, input) {
      const next = { ...draft, recognition_date: input.recognitionDate, lines: input.lines };
      items.splice(items.indexOf(draft), 1, next);
      return next;
    },
    async validate() { return { status: "PASS" }; },
    async submit() { return { state: "READY_FOR_REVIEW" }; },
  };
  return Object.freeze(client);
}

function projectDraft(value: unknown): BusinessVoucherDraft {
  if (!isObject(value) || !Array.isArray(value.lines) || !isObject(value.balance)) throw invalidResponse();
  return Object.freeze({
    candidate_id: text(value.candidate_id),
    state: text(value.state) as BusinessVoucherState,
    version: integer(value.version),
    current_revision_no: integer(value.current_revision_no),
    candidate_hash: text(value.candidate_hash),
    project_code: text(value.project_code),
    recognition_date: text(value.recognition_date),
    transaction_currency: text(value.transaction_currency),
    source_kind: text(value.source_kind),
    source_record_ref: text(value.source_record_ref),
    business_work_code: text(value.business_work_code),
    document_envelope_id: text(value.document_envelope_id),
    journey: projectBusinessJourney(value.journey),
    approved_document: isObject(value.approved_document) ? {
      approved_document_id: text(value.approved_document.approved_document_id),
      approved_amount: text(value.approved_document.approved_amount),
      remaining_amount: text(value.approved_document.remaining_amount),
      attachment_manifest_hash: text(value.approved_document.attachment_manifest_hash),
    } : null,
    lines: value.lines.map(projectLine),
    balance: {
      debit: text(value.balance.debit),
      credit: text(value.balance.credit),
      balanced: value.balance.balanced === true,
    },
  });
}

function projectLine(value: unknown): BusinessVoucherLine {
  if (!isObject(value)) throw invalidResponse();
  return {
    line_no: integer(value.line_no),
    account_code: text(value.account_code),
    account_name: text(value.account_name),
    debit_original: text(value.debit_original),
    credit_original: text(value.credit_original),
    source_record_line_ref: text(value.source_record_line_ref),
    description: typeof value.description === "string" ? value.description : null,
    evidence_hash: text(value.evidence_hash),
  };
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const value: unknown = await response.json();
    if (!isObject(value)) throw invalidResponse();
    return value;
  } catch (error) {
    if (error instanceof BusinessVoucherClientError) throw error;
    throw invalidResponse();
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function text(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }
function integer(value: unknown): number { if (typeof value !== "number" || !Number.isInteger(value)) throw invalidResponse(); return value; }
function invalidResponse() { return new BusinessVoucherClientError("전표 응답 형식이 올바르지 않습니다.", "INVALID_RESPONSE", 502); }
