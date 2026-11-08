import { CheckCircle2, ReceiptText, TriangleAlert } from "lucide-react";

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

export interface WorkspaceResultProjection {
  readonly status: string;
  readonly businessSummary?: VoucherBusinessSummary | null;
  readonly artifactCount?: number;
  readonly warnings?: readonly string[];
}

export function BusinessResultCard({ result }: { readonly result: WorkspaceResultProjection }) {
  const summary = result.businessSummary ?? null;
  const successful = ["SUCCEEDED", "PARTIAL"].includes(result.status);
  const warnings = result.warnings ?? [];
  return (
    <Card className={styles.card} aria-labelledby="business-result-title">
      <header className={styles.header}>
        <div className={styles.titleGroup}>
          {successful ? <CheckCircle2 aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
          <div>
            <p className={styles.eyebrow}>업무 처리 결과</p>
            <h2 id="business-result-title">
              {summary ? "전표 등록 결과" : "요청 처리 결과"}
            </h2>
          </div>
        </div>
        <StatusPill tone={successful ? "success" : "warning"}>
          {resultStatusLabel(result.status)}
        </StatusPill>
      </header>

      {summary ? <VoucherSummary summary={summary} /> : (
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

function approvalLabel(state: VoucherBusinessSummary["approvalState"]): string {
  return {
    APPROVED: "승인 완료",
    DENIED: "승인 거절",
    NOT_REQUIRED: "승인 불필요",
    UNKNOWN: "확인 중",
  }[state];
}
