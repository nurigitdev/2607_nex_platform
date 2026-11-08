export type ApprovalDomain = "NSL_WRITE" | "AGENT_FORMAL" | "BUSINESS_FORMAL";
export type ApprovalSourceState =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "EXPIRED"
  | "CANCELLED";
export type ProjectionSourceStatus = "AVAILABLE" | "OPEN";

export interface ApprovalAttachmentItem {
  readonly attachment_id: string;
  readonly display_name: string;
  readonly media_type: string;
  readonly size_bytes: number;
  readonly content_route: string;
  readonly download_route: string;
}

export interface ApprovalAttachmentManifest {
  readonly state: "LOCKED";
  readonly attachment_count: number;
  readonly total_size_bytes: number;
  readonly items: readonly ApprovalAttachmentItem[];
}

export interface FormalApprovalProgress {
  readonly current_stage: number;
  readonly stage_count: number;
  readonly requested_role: string;
  readonly org_unit_id: string;
  readonly project_id: string;
  readonly terminal_state: ApprovalSourceState | null;
}

export interface ApprovalGate {
  readonly gate_id: string;
  readonly approval_domain: ApprovalDomain;
  readonly state: ApprovalSourceState;
  readonly title: string;
  readonly summary: string;
  readonly expires_at: string | null;
  readonly approval_provider_type: string | null;
  readonly approval_target_ref: string | null;
  readonly business_operation_id: string | null;
  readonly attachment_manifest?: ApprovalAttachmentManifest;
  readonly formal_approval?: FormalApprovalProgress;
}

export interface ApprovalInbox {
  readonly gates: readonly ApprovalGate[];
  readonly returned_count: number;
  readonly scan_truncated: boolean;
}

export interface ApprovalGateDetail {
  readonly gate: ApprovalGate;
  readonly created_at: string;
  readonly version: number;
  readonly decision_options: readonly ["APPROVE", "REJECT"];
}

interface TextProjection {
  readonly status: ProjectionSourceStatus;
  readonly value?: string | null;
  readonly display_name?: string | null;
}

export interface UserApprovalProjection {
  readonly gate_id: string;
  readonly approval_domain: ApprovalDomain;
  readonly state: ApprovalSourceState;
  readonly title: string;
  readonly summary: string;
  readonly expires_at: string | null;
  readonly approval_provider_type: string | null;
  readonly approval_target_ref: string | null;
  readonly business_operation_id: string | null;
  readonly requester: TextProjection;
  readonly requested_at: TextProjection & { readonly value: string };
  readonly project: {
    readonly id_status: ProjectionSourceStatus;
    readonly project_id: string | null;
    readonly display_status: ProjectionSourceStatus;
    readonly display_name: string | null;
  };
  readonly amount: {
    readonly status: ProjectionSourceStatus;
    readonly value: string | null;
    readonly currency: string | null;
  };
  readonly business_date: TextProjection;
  readonly accounts: {
    readonly status: ProjectionSourceStatus;
    readonly items: readonly { readonly code: string; readonly display_name: string | null }[];
  };
  readonly risk: {
    readonly status: ProjectionSourceStatus;
    readonly level: "LOW" | "MEDIUM" | "HIGH" | null;
    readonly explanation: string | null;
  };
  readonly line_items: {
    readonly status: ProjectionSourceStatus;
    readonly items: readonly {
      readonly line_no: number;
      readonly description: string | null;
      readonly account_code: string | null;
      readonly amount: string;
      readonly currency: string;
    }[];
  };
}

export interface ApprovalDecisionRequest {
  readonly schema_version: "wc_approval_decision_request.v1";
  readonly decision: "APPROVE" | "REJECT";
  readonly decision_comment: string | null;
  readonly correlation_id: string | null;
  readonly causation_id: string | null;
}

export interface ApprovalDecisionResult {
  readonly approval_work_item_id: string;
  readonly decision: "APPROVE" | "REJECT";
  readonly decision_comment: string | null;
  readonly decided_at: string;
}

export interface ApprovalClientPort {
  readonly clientMode: "mock" | "fetch";
  readonly resolveResourceRoute: (route: string) => string;
  readonly listApprovalGates: (input?: { readonly limit?: number }) => Promise<ApprovalInbox>;
  readonly getApprovalGate: (gateId: string) => Promise<ApprovalGateDetail>;
  readonly getApprovalProjection: (gateId: string) => Promise<UserApprovalProjection>;
  readonly submitApprovalDecision: (
    gateId: string,
    request: ApprovalDecisionRequest,
  ) => Promise<ApprovalDecisionResult>;
}
