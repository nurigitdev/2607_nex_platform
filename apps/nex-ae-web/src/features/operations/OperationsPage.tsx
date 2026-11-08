import { RefreshCw } from "lucide-react";

import type { OperationsSummaryProjection } from "../../app/api/operationsClientPort";
import { Button, EmptyState, StatusPill } from "../../design-system/components";
import styles from "./OperationsPage.module.css";

export function OperationsPage({
  summary = null,
  loading = false,
  error = null,
  onRefresh,
}: {
  readonly summary?: OperationsSummaryProjection | null;
  readonly loading?: boolean;
  readonly error?: string | null;
  readonly onRefresh?: () => Promise<void> | void;
}) {
  return (
    <section className={styles.page} aria-labelledby="operations-title">
      <header>
        <div><span>Operations</span><h1 id="operations-title">운영/진단</h1></div>
        <Button variant="ghost" size="sm" leadingIcon={<RefreshCw aria-hidden="true" size={16} />} disabled={loading} onClick={() => void onRefresh?.()}>새로고침</Button>
      </header>
      {error ? <div className={styles.error} role="alert">{error}</div> : null}
      {!summary ? (
        <EmptyState title={loading ? "운영 정보를 확인하고 있습니다" : "운영 정보를 표시할 수 없습니다"} description="잠시 후 새로고침해 주세요." />
      ) : (
        <>
          <div className={styles.summary}><strong>플랫폼 상태</strong><StatusPill tone={statusTone(summary.overallStatus)}>{statusLabel(summary.overallStatus)}</StatusPill></div>
          <section className={styles.section} aria-labelledby="service-status-title">
            <h2 id="service-status-title">서비스 상태</h2>
            <table className={styles.table}>
              <thead><tr><th>서비스</th><th>상태</th><th>준비 상태</th><th>버전</th></tr></thead>
              <tbody>{summary.services.map(service => (
                <tr key={service.serviceId}><td>{service.serviceId}</td><td>{statusLabel(service.healthStatus)}</td><td>{statusLabel(service.readinessStatus)}</td><td>{service.version ?? "-"}</td></tr>
              ))}</tbody>
            </table>
          </section>
          <section className={styles.section} aria-labelledby="runtime-status-title">
            <h2 id="runtime-status-title">런타임 진단</h2>
            <dl className={styles.runtime}>
              <div><dt>데이터베이스</dt><dd>{statusLabel(summary.runtime.databaseStatus)}</dd></div>
              <div><dt>Agent Runtime</dt><dd>{statusLabel(summary.runtime.agentRuntimeStatus)}</dd></div>
              <div><dt>모델 경로</dt><dd>{statusLabel(summary.runtime.providerRouteStatus)}</dd></div>
            </dl>
          </section>
          <section className={styles.section} aria-labelledby="safe-routes-title">
            <h2 id="safe-routes-title">안전한 운영 경로</h2>
            <ul className={styles.routes}>{summary.routes.map(route => <li key={route.routeId}><strong>{route.routeId}</strong><span>{route.method}</span><code>{route.path}</code></li>)}</ul>
          </section>
        </>
      )}
    </section>
  );
}

function statusLabel(status: string) {
  return ({ READY: "정상", HEALTHY: "정상", AVAILABLE: "사용 가능", CONFIGURED: "설정됨", DEGRADED: "주의", ATTENTION: "확인 필요", NOT_READY: "준비 안 됨", UNAVAILABLE: "사용 불가", NOT_OBSERVED: "미확인", UNKNOWN: "알 수 없음" } as Record<string, string>)[status] ?? "확인 필요";
}

function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (["READY", "HEALTHY", "AVAILABLE", "CONFIGURED"].includes(status)) return "success";
  if (["DEGRADED", "ATTENTION"].includes(status)) return "warning";
  if (["NOT_READY", "UNAVAILABLE"].includes(status)) return "danger";
  return "neutral";
}
