import {
  CircleCheck,
  CircleX,
  Clock3,
  Info,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { IconButton } from "./controls";
import { classNames } from "./classNames";
import styles from "./components.module.css";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

export function Badge({
  children,
  tone = "neutral",
}: {
  readonly children: ReactNode;
  readonly tone?: StatusTone;
}) {
  return <span className={classNames(styles.badge, styles[`tone_${tone}`])}>{children}</span>;
}

const STATUS_ICONS: Record<StatusTone, LucideIcon> = {
  neutral: Clock3,
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  danger: CircleX,
};

export function StatusPill({
  children,
  tone = "neutral",
}: {
  readonly children: ReactNode;
  readonly tone?: StatusTone;
}) {
  const Icon = STATUS_ICONS[tone];
  return (
    <span className={classNames(styles.badge, styles.statusPill, styles[`tone_${tone}`])}>
      <Icon aria-hidden="true" size={14} />
      <span>{children}</span>
    </span>
  );
}

export function Toast({
  title,
  description,
  tone = "info",
  onDismiss,
}: {
  readonly title: string;
  readonly description?: string;
  readonly tone?: StatusTone;
  readonly onDismiss?: () => void;
}) {
  return (
    <div
      className={classNames(styles.toast, styles[`tone_${tone}`])}
      role={tone === "danger" ? "alert" : "status"}
    >
      <div>
        <strong>{title}</strong>
        {description ? <p>{description}</p> : null}
      </div>
      {onDismiss ? (
        <IconButton label="알림 닫기" icon={<X aria-hidden="true" size={18} />} onClick={onDismiss} />
      ) : null}
    </div>
  );
}

export interface StepperItem {
  readonly id: string;
  readonly label: string;
  readonly state: "complete" | "current" | "pending" | "error";
}

export function Stepper({ items, label = "진행 상태" }: { readonly items: readonly StepperItem[]; readonly label?: string }) {
  return (
    <ol className={styles.stepper} aria-label={label}>
      {items.map(item => {
        const Icon = item.state === "complete" ? CircleCheck : item.state === "error" ? CircleX : Clock3;
        return (
          <li
            key={item.id}
            className={styles.stepperItem}
            aria-current={item.state === "current" ? "step" : undefined}
          >
            <Icon aria-hidden="true" size={18} />
            <span>{item.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function EmptyState({
  icon: Icon = Info,
  title,
  description,
  action,
}: {
  readonly icon?: LucideIcon;
  readonly title: string;
  readonly description: string;
  readonly action?: ReactNode;
}) {
  return (
    <div className={styles.emptyState}>
      <span className={styles.emptyStateIcon} aria-hidden="true"><Icon size={32} /></span>
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function Avatar({ name, size = "md" }: { readonly name: string; readonly size?: "sm" | "md" }) {
  const initials = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map(part => part[0])
    .join("")
    .toUpperCase();
  return (
    <span className={classNames(styles.avatar, styles[`avatar_${size}`])} aria-label={name}>
      {initials || "?"}
    </span>
  );
}
