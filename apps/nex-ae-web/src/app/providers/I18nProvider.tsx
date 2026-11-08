import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  DEFAULT_LOCALE,
  message,
  normalizeLocale,
} from "../../locales/messages.js";

interface I18nContextValue {
  readonly locale: string;
  readonly setLocale: (locale: string) => void;
  readonly t: (key: string, values?: Readonly<Record<string, unknown>>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({
  children,
  initialLocale = DEFAULT_LOCALE,
}: {
  readonly children: ReactNode;
  readonly initialLocale?: string;
}) {
  const [locale, setLocaleState] = useState(() => normalizeLocale(initialLocale));
  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      setLocale: nextLocale => setLocaleState(normalizeLocale(nextLocale)),
      t: (key, values = {}) => message(key, { locale, values }),
    }),
    [locale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used within I18nProvider");
  return value;
}
