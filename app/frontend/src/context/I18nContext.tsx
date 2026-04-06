import { createContext, ReactNode, useContext, useMemo, useState } from 'react';

import { Language, translations } from '../i18n/translations';

type TranslateParams = Record<string, string | number>;

type I18nContextValue = {
  language: Language;
  setLanguage: (next: Language) => void;
  t: (key: string, params?: TranslateParams) => string;
};

const STORAGE_KEY = 'pdads_lang';

const I18nContext = createContext<I18nContextValue | null>(null);

function getInitialLanguage(): Language {
  const fromStorage = localStorage.getItem(STORAGE_KEY);
  if (fromStorage === 'ru' || fromStorage === 'en' || fromStorage === 'uz') {
    return fromStorage;
  }

  const browserLang = (navigator.language || 'ru').toLowerCase();
  if (browserLang.startsWith('en')) {
    return 'en';
  }
  if (browserLang.startsWith('uz')) {
    return 'uz';
  }
  return 'ru';
}

function interpolate(template: string, params?: TranslateParams): string {
  if (!params) {
    return template;
  }
  return Object.entries(params).reduce((acc, [key, value]) => {
    return acc.replaceAll(`{${key}}`, String(value));
  }, template);
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(getInitialLanguage);

  const value = useMemo<I18nContextValue>(() => {
    const setLanguage = (next: Language) => {
      setLanguageState(next);
      localStorage.setItem(STORAGE_KEY, next);
    };

    const t = (key: string, params?: TranslateParams): string => {
      const langDict = translations[language] ?? {};
      const fallbackDict = translations.en;
      const template = langDict[key] ?? fallbackDict[key] ?? key;
      return interpolate(template, params);
    };

    return { language, setLanguage, t };
  }, [language]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error('useI18n must be used within I18nProvider');
  }
  return ctx;
}
