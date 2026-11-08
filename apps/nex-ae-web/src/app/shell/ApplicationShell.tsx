import {
  Archive,
  BriefcaseBusiness,
  FileText,
  Gauge,
  Inbox,
  LogOut,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { Button } from "../../design-system/components";
import { projectApplicationShell } from "../legacyAdapters/applicationShellAdapter";
import { projectSessionIdentity } from "../legacyAdapters/sessionAdapter";
import { useSession } from "../providers/SessionProvider";
import styles from "./ApplicationShell.module.css";

const primaryItems = [
  { path: "/workspace", label: "워크스페이스", icon: BriefcaseBusiness },
  { path: "/approvals", label: "승인함", icon: Inbox },
  { path: "/documents", label: "문서", icon: FileText },
  { path: "/artifacts", label: "아티팩트", icon: Archive },
] as const;

export function ApplicationShell() {
  const { sessionState, employeeId, logout } = useSession();
  const shell = projectApplicationShell({ sessionState });
  const identity = projectSessionIdentity({ sessionState, employeeId });
  const items = shell.operationsVisible
    ? [...primaryItems, { path: "/operations", label: "운영/진단", icon: Gauge }]
    : primaryItems;

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main-content">본문으로 건너뛰기</a>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>NeX AE</div>
        <nav className={styles.navigation} aria-label="주요 탐색">
          {items.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ""}`}
            >
              <Icon aria-hidden="true" size={18} strokeWidth={1.8} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className={styles.workspace}>
        <header className={styles.header}>
          <strong>NeX-Platform</strong>
          {identity.visible ? (
            <div className={styles.sessionActions}>
              <span>{identity.account}</span>
              <Button
                variant="ghost"
                size="sm"
                leadingIcon={<LogOut aria-hidden="true" size={16} />}
                onClick={() => void logout()}
              >
                로그아웃
              </Button>
            </div>
          ) : null}
        </header>
        <main id="main-content" className={styles.main} tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
