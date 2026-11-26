import type { BusinessJourney as Journey } from "../../app/api/businessJourney";
import styles from "./BusinessJourney.module.css";

export function BusinessJourney({ value }: { readonly value: Journey }) {
  return <nav className={styles.journey} aria-label="업무 진행 단계">
    <ol>{value.steps.map(step => <li key={step.code} data-status={step.status} aria-current={step.status === "CURRENT" ? "step" : undefined}>
      <strong>{step.label}</strong>
      <span>{statusLabel(step.status)}</span>
    </li>)}</ol>
  </nav>;
}

function statusLabel(status: Journey["steps"][number]["status"]): string {
  return ({
    COMPLETED: "완료",
    CURRENT: "진행 중",
    AVAILABLE: "진행 가능",
    UPCOMING: "대기",
    RETURNED: "수정 요청",
    REJECTED: "반려",
    CANCELLED: "회수",
    BLOCKED: "중단",
  } as const)[status];
}
