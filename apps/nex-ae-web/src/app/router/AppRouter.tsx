import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { EmptyState } from "../../design-system/components";
import { projectApplicationShell } from "../legacyAdapters/applicationShellAdapter";
import { useSession } from "../providers/SessionProvider";
import { ApplicationShell } from "../shell/ApplicationShell";
import styles from "./AppRouter.module.css";

const pageLabels: Readonly<Record<string, string>> = Object.freeze({
  workspace: "워크스페이스",
  approvals: "승인함",
  upload: "업로드",
  documents: "문서",
  retrieval: "검색",
  artifacts: "아티팩트",
  operations: "운영/진단",
});

function LoginPlaceholder() {
  const { sessionState } = useSession();
  if (sessionState.status === "authenticated") return <Navigate to="/workspace" replace />;
  return <main className={styles.login}><h1>NeX AE</h1></main>;
}

function ProtectedShell() {
  const location = useLocation();
  const { sessionState } = useSession();
  const requestedView = location.pathname.slice(1).split("/")[0];
  const shell = projectApplicationShell({ sessionState, requestedView });
  if (!shell.authenticated) return <Navigate to="/login" replace state={{ from: location }} />;
  if (!shell.allowedViews.includes(requestedView)) return <Navigate to="/workspace" replace />;
  return <ApplicationShell />;
}

function RoutePage({ routeId }: { readonly routeId: string }) {
  return (
    <section className={styles.page} aria-labelledby={`${routeId}-title`}>
      <h1 id={`${routeId}-title`}>{pageLabels[routeId]}</h1>
      <EmptyState title="표시할 항목이 없습니다" description="새 항목이 여기에 표시됩니다." />
    </section>
  );
}

function UnknownRoute() {
  const { sessionState } = useSession();
  return <Navigate to={sessionState.status === "authenticated" ? "/workspace" : "/login"} replace />;
}

export function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPlaceholder />} />
      <Route element={<ProtectedShell />}>
        {Object.keys(pageLabels).map(routeId => (
          <Route key={routeId} path={`/${routeId}`} element={<RoutePage routeId={routeId} />} />
        ))}
      </Route>
      <Route path="*" element={<UnknownRoute />} />
    </Routes>
  );
}
