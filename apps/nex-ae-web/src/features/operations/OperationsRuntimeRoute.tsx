import { useEffect, useState } from "react";

import type { OperationsSummaryProjection } from "../../app/api/operationsClientPort";
import { useOptionalInstalledRuntime } from "../../app/providers/RuntimeProvider";
import { OperationsPage } from "./OperationsPage";

export function OperationsRuntimeRoute() {
  const runtime = useOptionalInstalledRuntime();
  const [summary, setSummary] = useState<OperationsSummaryProjection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (!runtime) return;
    setLoading(true);
    setError(null);
    try {
      setSummary(await runtime.clients.operations.getSummary());
    } catch (cause) {
      setSummary(null);
      setError(messageFor(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, [runtime]);
  return <OperationsPage summary={summary} loading={loading} error={error} onRefresh={refresh} />;
}

function messageFor(error: unknown) {
  const statusCode = error && typeof error === "object" && "statusCode" in error ? Number(error.statusCode) : null;
  if (statusCode === 403) return "운영 화면에 접근할 권한이 없습니다.";
  return "운영 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
}
