import { useI18n } from '../../context/I18nContext';
import { Language, languageLabels } from '../../i18n/translations';

const LANGUAGES: Language[] = ['en', 'ru', 'uz'];

type LanguageSwitcherProps = {
  inline?: boolean;
};

export function LanguageSwitcher({ inline = false }: LanguageSwitcherProps) {
  const { language, setLanguage } = useI18n();

  if (inline) {
    return (
      <div className="inline-flex overflow-hidden rounded-xl border border-outline-variant/40 bg-white shadow-sm">
        {LANGUAGES.map((lang) => {
          const active = language === lang;
          return (
            <button
              key={lang}
              type="button"
              onClick={() => setLanguage(lang)}
              className={`px-3 py-1.5 text-xs font-semibold transition ${
                active
                  ? 'bg-primary-container text-white'
                  : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
              }`}
            >
              {languageLabels[lang]}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="fixed right-4 top-4 z-50">
      <div className="inline-flex overflow-hidden rounded-xl border border-outline-variant/40 bg-white shadow-sm">
        {LANGUAGES.map((lang) => {
          const active = language === lang;
          return (
            <button
              key={lang}
              type="button"
              onClick={() => setLanguage(lang)}
              className={`px-3 py-1.5 text-xs font-semibold transition ${
                active
                  ? 'bg-primary-container text-white'
                  : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
              }`}
            >
              {languageLabels[lang]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
