import { ChartNoAxesCombined, CheckCircle2, ReceiptText, TriangleAlert } from "lucide-react";

import { Card, StatusPill } from "../../design-system/components";
import styles from "./BusinessResultCard.module.css";

export interface VoucherBusinessSummary {
  readonly resultType: "FINANCE.VOUCHER_DRAFT";
  readonly schemaVersion: "ae_business_result_summary.v1";
  readonly outcome: "COMMITTED" | "NOT_COMMITTED" | "UNKNOWN_COMMIT_STATE";
  readonly verificationStatus: string | null;
  readonly approvalState: "APPROVED" | "DENIED" | "NOT_REQUIRED" | "UNKNOWN";
  readonly businessOperationId: string;
  readonly voucherNumber: string | null;
  readonly amount: string;
  readonly currency: string;
  readonly accountCodes: readonly string[];
  readonly projectCode: string;
  readonly businessObjectLink: null;
}

export interface ProjectAllocationProjection {
  readonly projectCode: string;
  readonly projectionId: string;
  readonly projectionVersion: number;
  readonly projectionHash: string;
  readonly reconciliationStatus: string;
  readonly freshnessStatus: string;
  readonly dataClassification: string;
}

export interface ProjectAllocationBusinessSummary {
  readonly resultType: "FINANCE.PROJECT_ALLOCATION";
  readonly schemaVersion: "ae_business_result_summary.v1";
  readonly outcome: "ALLOCATED_AND_VERIFIED";
  readonly journalRef: string;
  readonly sourcePoolRef: string;
  readonly sourcePoolHash: string;
  readonly allocationBatchRef: string;
  readonly allocationReconciliationHash: string;
  readonly pnlRefreshHash: string;
  readonly projectProjections: readonly ProjectAllocationProjection[];
}

export type BusinessSummary =
  | VoucherBusinessSummary
  | ProjectAllocationBusinessSummary;

export interface WorkspaceResultProjection {
  readonly status: string;
  readonly businessSummary?: BusinessSummary | null;
  readonly artifactCount?: number;
  readonly warnings?: readonly string[];
}

export function BusinessResultCard({ result }: { readonly result: WorkspaceResultProjection }) {
  const summary = result.businessSummary ?? null;
  const successful = ["SUCCEEDED", "PARTIAL"].includes(result.status);
  const warnings = result.warnings ?? [];
  return (
    <Card className={styles.card} aria-labelledby="business-result-title" data-ux-region="primary-result">
      <header className={styles.header}>
        <div className={styles.titleGroup}>
          {successful ? <CheckCircle2 aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
          <div>
            <p className={styles.eyebrow}>업무 처리 결과</p>
            <h2 id="business-result-title">
              {businessResultTitle(summary)}
            </h2>
          </div>
        </div>
        <StatusPill tone={successful ? "success" : "warning"}>
          {resultStatusLabel(result.status)}
        </StatusPill>
      </header>

      {summary?.resultType === "FINANCE.VOUCHER_DRAFT" ? (
        <VoucherSummary summary={summary} />
      ) : summary?.resultType === "FINANCE.PROJECT_ALLOCATION" ? (
        <ProjectAllocationSummary summary={summary} />
      ) : (
        <p className={styles.genericMessage}>
          안전하게 공개할 수 있는 결과 요약만 표시합니다.
        </p>
      )}

      {typeof result.artifactCount === "number" && result.artifactCount > 0 ? (
        <p className={styles.supporting}>생성된 결과물 {result.artifactCount}건</p>
      ) : null}
      {warnings.length > 0 ? (
        <ul className={styles.warnings} aria-label="결과 주의사항">
          {warnings.map(warning => <li key={warning}>{warning}</li>)}
        </ul>
      ) : null}
    </Card>
  );
}

function ProjectAllocationSummary({
  summary,
}: {
  readonly summary: ProjectAllocationBusinessSummary;
}) {
  return (
    <div className={styles.summary}>
      <div className={styles.allocationIdentity}>
        <ChartNoAxesCombined aria-hidden="true" size={20} />
        <span>배부 결과</span>
        <strong>{summary.projectProjections.length}개 프로젝트 반영 완료</strong>
      </div>
      <ul className={styles.projectList} aria-label="프로젝트 배부 반영 상태">
        {summary.projectProjections.map(project => (
          <li className={styles.projectItem} key={project.projectCode}>
            <strong>{project.projectCode}</strong>
            <span>{projectionStateLabel(project)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function VoucherSummary({ summary }: { readonly summary: VoucherBusinessSummary }) {
  return (
    <div className={styles.summary}>
      <div className={styles.voucherIdentity}>
        <ReceiptText aria-hidden="true" size={20} />
        <span>전표번호</span>
        <strong>{summary.voucherNumber ?? "발급되지 않음"}</strong>
      </div>
      <dl className={styles.fields}>
        <div><dt>금액</dt><dd>{formatAmount(summary.amount, summary.currency)}</dd></div>
        <div><dt>프로젝트</dt><dd>{summary.projectCode}</dd></div>
        <div><dt>계정</dt><dd>{summary.accountCodes.join(" / ")}</dd></div>
        <div><dt>승인</dt><dd>{approvalLabel(summary.approvalState)}</dd></div>
      </dl>
    </div>
  );
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
    FAILED: "실패",
    BLOCKED: "확인 필요",
    CANCELLED: "취소됨",
  }[status] ?? "처리 결과";
}

function businessResultTitle(summary: BusinessSummary | null): string {
  if (summary?.resultType === "FINANCE.VOUCHER_DRAFT") return "전표 등록 결과";
  if (summary?.resultType === "FINANCE.PROJECT_ALLOCATION") return "프로젝트 배부 결과";
  return "요청 처리 결과";
}

function projectionStateLabel(project: ProjectAllocationProjection): string {
  const reconciliation = project.reconciliationStatus === "VERIFIED"
    ? "검증 완료"
    : "검증 확인 필요";
  const freshness = project.freshnessStatus === "CURRENT"
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
