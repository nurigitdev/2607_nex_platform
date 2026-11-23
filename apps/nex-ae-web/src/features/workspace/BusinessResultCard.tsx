import { ChartNoAxesCombined, CheckCircle2, ReceiptText, TriangleAlert } from "lucide-react";

import { Card, StatusPill } from "../../design-system/components";
import {
  presentBusinessResult,
  type ProjectAllocationResultPresentation,
  type VoucherResultPresentation,
} from "./businessResultPresentation";
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
  const presentation = presentBusinessResult(result);
  return (
    <Card className={styles.card} aria-labelledby="business-result-title" data-ux-region="primary-result">
      <header className={styles.header}>
        <div className={styles.titleGroup}>
          {presentation.successful ? <CheckCircle2 aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
          <div>
            <p className={styles.eyebrow}>업무 처리 결과</p>
            <h2 id="business-result-title">
              {presentation.title}
            </h2>
          </div>
        </div>
        <StatusPill tone={presentation.successful ? "success" : "warning"}>
          {presentation.statusLabel}
        </StatusPill>
      </header>

      <p className={styles.description}>{presentation.description}</p>

      {presentation.kind === "voucher" ? (
        <VoucherSummary presentation={presentation} />
      ) : presentation.kind === "project-allocation" ? (
        <ProjectAllocationSummary presentation={presentation} />
      ) : (
        <p className={styles.genericMessage}>업무 결과 요약이 준비되지 않았습니다.</p>
      )}

      {presentation.artifactLabel ? (
        <p className={styles.supporting}>{presentation.artifactLabel}</p>
      ) : null}
      {presentation.warnings.length > 0 ? (
        <ul className={styles.warnings} aria-label="결과 주의사항">
          {presentation.warnings.map(warning => <li key={warning}>{warning}</li>)}
        </ul>
      ) : null}
    </Card>
  );
}

function ProjectAllocationSummary({
  presentation,
}: {
  readonly presentation: ProjectAllocationResultPresentation;
}) {
  return (
    <div className={styles.summary}>
      <div className={styles.allocationIdentity}>
        <ChartNoAxesCombined aria-hidden="true" size={20} />
        <span>배부 결과</span>
        <strong>{presentation.headline}</strong>
      </div>
      <ul className={styles.projectList} aria-label="프로젝트 배부 반영 상태">
        {presentation.projects.map(project => (
          <li className={styles.projectItem} key={project.projectCode}>
            <strong>{project.projectCode}</strong>
            <span>{project.stateLabel}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function VoucherSummary({
  presentation,
}: {
  readonly presentation: VoucherResultPresentation;
}) {
  return (
    <div className={styles.summary}>
      <div className={styles.voucherIdentity}>
        <ReceiptText aria-hidden="true" size={20} />
        <span>전표번호</span>
        <strong>{presentation.voucherNumber}</strong>
      </div>
      <dl className={styles.fields}>
        {presentation.fields.map(field => (
          <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>
        ))}
      </dl>
    </div>
  );
}
