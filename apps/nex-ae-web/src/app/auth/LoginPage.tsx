import { Eye, EyeOff, LogIn } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Button, IconButton, Input } from "../../design-system/components";
import { useSession } from "../providers/SessionProvider";
import styles from "./LoginPage.module.css";

export function LoginPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { sessionState, phase, errorStatus, login } = useSession();
  const [employeeId, setEmployeeId] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const from = routeFromState(location.state);

  useEffect(() => {
    if (sessionState.status === "authenticated") navigate(from, { replace: true });
  }, [from, navigate, sessionState.status]);

  if (sessionState.status === "authenticated") return <Navigate to={from} replace />;

  const employeeError = submitted && !employeeId.trim() ? "사번을 입력해 주세요." : undefined;
  const passwordError = submitted && !password ? "비밀번호를 입력해 주세요." : undefined;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    if (!employeeId.trim() || !password) return;
    const secret = password;
    setPassword("");
    await login({ employeeId: employeeId.trim(), password: secret });
  }

  function handlePasswordKey(event: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(event.getModifierState("CapsLock"));
  }

  return (
    <main className={styles.page} data-ux-region="main">
      <section className={styles.panel} aria-labelledby="login-title">
        <header className={styles.brand}>
          <span aria-hidden="true">N</span>
          <div><strong>NeX AE</strong><p>NeX-Platform</p></div>
        </header>
        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <div className={styles.heading}>
            <h1 id="login-title">사번 로그인</h1>
          </div>
          {sessionState.status === "expired" ? (
            <p className={styles.notice} role="alert">세션이 만료되었습니다. 다시 로그인해 주세요.</p>
          ) : null}
          {errorStatus ? <p className={styles.error} role="alert">{loginErrorMessage(errorStatus)}</p> : null}
          <Input
            label="사번"
            name="employee_id"
            autoComplete="username"
            value={employeeId}
            onChange={event => setEmployeeId(event.target.value)}
            error={employeeError}
            required
            autoFocus
          />
          <div className={styles.passwordField}>
            <Input
              label="비밀번호"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={event => setPassword(event.target.value)}
              onKeyDown={handlePasswordKey}
              onKeyUp={handlePasswordKey}
              error={passwordError}
              required
            />
            <IconButton
              className={styles.passwordToggle}
              label={showPassword ? "비밀번호 숨기기" : "비밀번호 보기"}
              icon={showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              onClick={() => setShowPassword(value => !value)}
            />
          </div>
          {capsLock ? <p className={styles.caps} role="status">Caps Lock이 켜져 있습니다.</p> : null}
          <Button
            className={styles.submit}
            type="submit"
            size="lg"
            loading={phase === "submitting"}
            leadingIcon={<LogIn aria-hidden="true" size={18} />}
          >
            로그인
          </Button>
        </form>
      </section>
    </main>
  );
}

function routeFromState(state: unknown) {
  if (state && typeof state === "object" && "from" in state) {
    const from = state.from as { pathname?: unknown };
    if (typeof from?.pathname === "string" && from.pathname.startsWith("/")) return from.pathname;
  }
  return "/workspace";
}

function loginErrorMessage(status: string) {
  if (status === "HTTP_401") return "사번 또는 비밀번호를 확인해 주세요.";
  if (status === "HTTP_403") return "이 계정은 NeX AE를 사용할 수 없습니다.";
  if (status === "NETWORK_ERROR" || status === "FETCH_UNAVAILABLE" || status.startsWith("HTTP_5")) {
    return "로그인 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.";
  }
  return "로그인하지 못했습니다. 다시 시도해 주세요.";
}
