import { ShieldAlert } from "lucide-react";

import styles from "./StartupFailure.module.css";

export function StartupFailure() {
  return (
    <main className={styles.page}>
      <section className={styles.message} role="alert" aria-labelledby="startup-failure-title">
        <ShieldAlert aria-hidden="true" size={28} />
        <div>
          <h1 id="startup-failure-title">서비스를 시작할 수 없습니다</h1>
          <p>잠시 후 다시 접속해 주세요.</p>
        </div>
      </section>
    </main>
  );
}
