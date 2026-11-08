import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

import { classNames } from "./classNames";
import styles from "./components.module.css";

export interface TabItem {
  readonly id: string;
  readonly label: string;
  readonly count?: number;
  readonly disabled?: boolean;
  readonly content: ReactNode;
}

export function Tabs({
  items,
  defaultValue,
  label,
}: {
  readonly items: readonly TabItem[];
  readonly defaultValue: string;
  readonly label: string;
}) {
  return (
    <TabsPrimitive.Root defaultValue={defaultValue}>
      <TabsPrimitive.List className={styles.tabsList} aria-label={label}>
        {items.map(item => (
          <TabsPrimitive.Trigger
            key={item.id}
            value={item.id}
            disabled={item.disabled}
            className={styles.tabsTrigger}
            aria-label={
              typeof item.count === "number"
                ? `${item.label} ${item.count}건`
                : item.label
            }
          >
            {item.label}
            {typeof item.count === "number" ? <span>{item.count}</span> : null}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {items.map(item => (
        <TabsPrimitive.Content key={item.id} value={item.id} className={styles.tabsContent}>
          {item.content}
        </TabsPrimitive.Content>
      ))}
    </TabsPrimitive.Root>
  );
}

export function NavItem({
  href,
  label,
  icon,
  active = false,
  count,
}: {
  readonly href: string;
  readonly label: string;
  readonly icon: ReactNode;
  readonly active?: boolean;
  readonly count?: number;
}) {
  return (
    <a
      href={href}
      className={classNames(styles.navItem, active && styles.navItemActive)}
      aria-current={active ? "page" : undefined}
      aria-label={typeof count === "number" ? `${label} ${count}건` : label}
    >
      <span aria-hidden="true">{icon}</span>
      <span>{label}</span>
      {typeof count === "number" ? <span className={styles.navCount}>{count}</span> : null}
    </a>
  );
}
