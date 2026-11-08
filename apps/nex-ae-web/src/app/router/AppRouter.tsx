import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { EmptyState } from "../../design-system/components";
import { ApprovalPage } from "../../features/approvals/ApprovalPage";
import { ArtifactRuntimeRoute } from "../../features/artifacts/ArtifactRuntimeRoute";
import { DocumentRuntimeRoute } from "../../features/documents/DocumentRuntimeRoute";
import { WorkspaceRuntimeRoute } from "../../features/workspace/WorkspaceRuntimeRoute";
import { LoginPage } from "../auth/LoginPage";
import { projectApplicationShell } from "../legacyAdapters/applicationShellAdapter";
import { useOptionalInstalledRuntime } from "../providers/RuntimeProvider";
import { useSession } from "../providers/SessionProvider";
import { ApplicationShell } from "../shell/ApplicationShell";
import styles from "./AppRouter.module.css";

const pageLabels: Readonly<Record<string, string>> = Object.freeze({
  workspace: "워크스페이스",
  approvals: "승인함",
  upload: "업로드",
  documents: "문서",
  retrieval: "검색",
  artifacts: "결과물",
  operations: "운영/진단",
});

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

function ApprovalRoute() {
  const runtime = useOptionalInstalledRuntime();
  return <ApprovalPage client={runtime?.clients.approval ?? null} />;
}

export function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedShell />}>
        <Route path="/workspace" element={<WorkspaceRuntimeRoute />} />
        <Route path="/approvals" element={<ApprovalRoute />} />
        <Route path="/documents" element={<DocumentRuntimeRoute />} />
        <Route path="/upload" element={<DocumentRuntimeRoute initialTab="upload" />} />
        <Route path="/retrieval" element={<DocumentRuntimeRoute initialTab="retrieval" />} />
        <Route path="/artifacts" element={<ArtifactRuntimeRoute />} />
        {Object.keys(pageLabels).filter(routeId => !["workspace", "approvals", "documents", "upload", "retrieval", "artifacts"].includes(routeId)).map(routeId => (
          <Route key={routeId} path={`/${routeId}`} element={<RoutePage routeId={routeId} />} />
        ))}
      </Route>
      <Route path="*" element={<UnknownRoute />} />
    </Routes>
  );
}
