import type { HTMLAttributes, ReactNode } from "react";

import { classNames } from "./classNames";
import styles from "./components.module.css";

export function Card({ className, children, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section {...props} className={classNames(styles.card, className)}>
      {children}
    </section>
  );
}

export interface DataColumn<Row> {
  readonly key: string;
  readonly header: string;
  readonly cell: (row: Row) => ReactNode;
}

export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
}: {
  readonly caption: string;
  readonly columns: readonly DataColumn<Row>[];
  readonly rows: readonly Row[];
  readonly rowKey: (row: Row) => string;
}) {
  return (
    <div className={styles.tableScroll} tabIndex={0} role="region" aria-label={caption}>
      <table className={styles.table}>
        <caption className={styles.visuallyHidden}>{caption}</caption>
        <thead><tr>{columns.map(column => <th key={column.key} scope="col">{column.header}</th>)}</tr></thead>
        <tbody>
          {rows.map(row => (
            <tr key={rowKey(row)}>{columns.map(column => <td key={column.key}>{column.cell(row)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function List({ children, label }: { readonly children: ReactNode; readonly label: string }) {
  return <ul className={styles.list} aria-label={label}>{children}</ul>;
}
