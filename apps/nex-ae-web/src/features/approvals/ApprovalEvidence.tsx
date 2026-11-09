import { Download, ExternalLink, Paperclip } from "lucide-react";

import type {
  ApprovalAttachmentManifest,
  UserApprovalProjection,
} from "../../app/api/approvalClientPort";
import { StatusPill } from "../../design-system/components";
import styles from "./ApprovalPage.module.css";

const RISK_PRESENTATION = Object.freeze({
  LOW: Object.freeze({ label: "낮음", tone: "success" }),
  MEDIUM: Object.freeze({ label: "중간", tone: "warning" }),
  HIGH: Object.freeze({ label: "높음", tone: "danger" }),
} as const);

export function approvalRiskLabel(risk: UserApprovalProjection["risk"]) {
  return risk.status === "AVAILABLE" && risk.level
    ? RISK_PRESENTATION[risk.level].label
    : "정보 미제공";
}

export function ApprovalEvidence({
  risk,
  manifest,
  resolveResourceRoute,
}: {
  readonly risk: UserApprovalProjection["risk"];
  readonly manifest?: ApprovalAttachmentManifest;
  readonly resolveResourceRoute: (route: string) => string;
}) {
  const riskPresentation =
    risk.status === "AVAILABLE" && risk.level ? RISK_PRESENTATION[risk.level] : null;
  return (
    <>
      {riskPresentation ? (
        <section className={styles.section} aria-labelledby="risk-summary-title">
          <div className={styles.sectionHeading}>
            <h3 id="risk-summary-title">위험도</h3>
            <StatusPill tone={riskPresentation.tone}>{riskPresentation.label}</StatusPill>
          </div>
          {risk.explanation ? <p className={styles.riskExplanation}>{risk.explanation}</p> : null}
        </section>
      ) : null}
      <section className={styles.section} aria-labelledby="attachment-summary-title">
        <div className={styles.sectionHeading}>
          <h3 id="attachment-summary-title">첨부 근거</h3>
          <span>
            {manifest
              ? `${manifest.attachment_count}개 · ${formatBytes(manifest.total_size_bytes)}`
              : "없음"}
          </span>
        </div>
        {manifest ? (
          <ul className={styles.evidenceList}>
            {manifest.items.map(item => (
              <li key={item.attachment_id}>
                <span className={styles.evidenceIdentity}>
                  <Paperclip aria-hidden="true" size={16} />
                  <span>
                    <strong>{item.display_name}</strong>
                    <small>{formatBytes(item.size_bytes)}</small>
                  </span>
                </span>
                <span className={styles.evidenceActions}>
                  <a
                    href={resolveResourceRoute(item.content_route)}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`${item.display_name} 열기`}
                  >
                    <ExternalLink aria-hidden="true" size={15} /> 열기
                  </a>
                  <a
                    href={resolveResourceRoute(item.download_route)}
                    download
                    aria-label={`${item.display_name} 다운로드`}
                  >
                    <Download aria-hidden="true" size={15} /> 다운로드
                  </a>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(value < 10240 ? 1 : 0)} KB`;
}
