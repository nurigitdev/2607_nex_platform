import type {
  BusinessSummary,
  ProjectAllocationBusinessSummary,
  VoucherBusinessSummary,
  WorkspaceResultProjection,
} from "./BusinessResultCard";

interface CommonBusinessResultPresentation {
  readonly successful: boolean;
  readonly statusLabel: string;
  readonly title: string;
  readonly description: string;
  readonly artifactLabel: string | null;
  readonly warnings: readonly string[];
}

export interface VoucherResultPresentation extends CommonBusinessResultPresentation {
  readonly kind: "voucher";
  readonly voucherNumber: string;
  readonly fields: readonly {
    readonly label: string;
    readonly value: string;
  }[];
}

export interface ProjectAllocationResultPresentation extends CommonBusinessResultPresentation {
  readonly kind: "project-allocation";
  readonly headline: string;
  readonly projects: readonly {
    readonly projectCode: string;
    readonly stateLabel: string;
  }[];
}

export interface GenericResultPresentation extends CommonBusinessResultPresentation {
  readonly kind: "generic";
}

export type BusinessResultPresentation =
  | VoucherResultPresentation
  | ProjectAllocationResultPresentation
  | GenericResultPresentation;

export function presentBusinessResult(
  result: WorkspaceResultProjection,
): BusinessResultPresentation {
  const common = commonPresentation(result);
  const summary = result.businessSummary ?? null;
  if (summary?.resultType === "FINANCE.VOUCHER_DRAFT") {
    return presentVoucher(summary, common);
  }
  if (summary?.resultType === "FINANCE.PROJECT_ALLOCATION") {
    return presentProjectAllocation(summary, common);
  }
  return {
    ...common,
    kind: "generic",
    title: "요청 처리 결과",
    description: common.successful
      ? "요청 처리가 끝났습니다. 표시 가능한 업무 요약을 확인해 주세요."
      : "요청을 완료하지 못했습니다. 아래 안내를 확인해 주세요.",
  };
}

function commonPresentation(
  result: WorkspaceResultProjection,
): CommonBusinessResultPresentation {
  const successful = ["SUCCEEDED", "PARTIAL"].includes(result.status);
  return {
    successful,
    statusLabel: resultStatusLabel(result.status),
    title: businessResultTitle(result.businessSummary ?? null),
    description: "",
    artifactLabel:
      typeof result.artifactCount === "number" && result.artifactCount > 0
        ? `생성된 결과물 ${result.artifactCount}건`
        : null,
    warnings: userFacingWarnings(result.warnings ?? []),
  };
}

function presentVoucher(
  summary: VoucherBusinessSummary,
  common: CommonBusinessResultPresentation,
): VoucherResultPresentation {
  return {
    ...common,
    kind: "voucher",
    title: "전표 등록 결과",
    description: voucherDescription(summary),
    voucherNumber: summary.voucherNumber ?? "발급되지 않음",
    fields: [
      { label: "금액", value: formatAmount(summary.amount, summary.currency) },
      { label: "프로젝트", value: summary.projectCode },
      {
        label: "계정",
        value: summary.accountCodes.length > 0
          ? summary.accountCodes.join(" / ")
          : "확인 필요",
      },
      { label: "승인", value: approvalLabel(summary.approvalState) },
    ],
  };
}

function presentProjectAllocation(
  summary: ProjectAllocationBusinessSummary,
  common: CommonBusinessResultPresentation,
): ProjectAllocationResultPresentation {
  return {
    ...common,
    kind: "project-allocation",
    title: "프로젝트 배부 결과",
    description: "배부 결과가 프로젝트 손익에 반영되었습니다.",
    headline: `${summary.projectProjections.length}개 프로젝트 반영 완료`,
    projects: summary.projectProjections.map(project => ({
      projectCode: project.projectCode,
      stateLabel: projectionStateLabel(
        project.reconciliationStatus,
        project.freshnessStatus,
      ),
    })),
  };
}

function voucherDescription(summary: VoucherBusinessSummary): string {
  if (summary.outcome === "NOT_COMMITTED") {
    return "전표가 등록되지 않았습니다. 처리 안내를 확인해 주세요.";
  }
  if (summary.outcome === "UNKNOWN_COMMIT_STATE") {
    return "전표 등록 결과를 확인하고 있습니다.";
  }
  return summary.verificationStatus === "VERIFIED"
    ? "전표 등록과 검증이 완료되었습니다."
    : "전표가 등록되었습니다. 검증 상태를 확인해 주세요.";
}

function formatAmount(amount: string, currency: string): string {
  const numeric = Number(amount);
  return Number.isFinite(numeric)
    ? `${numeric.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} ${currency}`
    : `${amount} ${currency}`;
}

function resultStatusLabel(status: string): string {
  return {
    SUCCEEDED: "완료",
    PARTIAL: "일부 완료",
    FAILED: "처리 실패",
    BLOCKED: "확인 필요",
    CANCELLED: "취소됨",
  }[status] ?? "처리 결과";
}

function businessResultTitle(summary: BusinessSummary | null): string {
  if (summary?.resultType === "FINANCE.VOUCHER_DRAFT") return "전표 등록 결과";
  if (summary?.resultType === "FINANCE.PROJECT_ALLOCATION") return "프로젝트 배부 결과";
  return "요청 처리 결과";
}

function projectionStateLabel(
  reconciliationStatus: string,
  freshnessStatus: string,
): string {
  const reconciliation = reconciliationStatus === "VERIFIED"
    ? "검증 완료"
    : "검증 확인 필요";
  const freshness = freshnessStatus === "CURRENT"
    ? "최신"
    : "갱신 확인 필요";
  return `${reconciliation} · ${freshness}`;
}

function approvalLabel(state: VoucherBusinessSummary["approvalState"]): string {
  return {
    APPROVED: "승인 완료",
    DENIED: "승인 거절",
    NOT_REQUIRED: "승인 불필요",
    UNKNOWN: "확인 중",
  }[state];
}

function userFacingWarnings(warnings: readonly string[]): readonly string[] {
  if (warnings.length === 0) return [];
  const labels = warnings.map(warning => {
    const normalized = warning.toUpperCase();
    if (normalized.includes("APPROVAL")) return "승인 상태를 추가로 확인해 주세요.";
    if (normalized.includes("VERIFY")) return "검증 상태를 추가로 확인해 주세요.";
    if (normalized.includes("PARTIAL")) return "일부 처리 결과를 추가로 확인해 주세요.";
    return "처리 결과에 확인이 필요한 항목이 있습니다.";
  });
  return [...new Set(labels)];
}
