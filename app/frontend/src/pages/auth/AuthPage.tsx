import { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from 'react';
import { City, Country } from 'country-state-city';
import { useNavigate } from 'react-router-dom';

import { authService } from '../../api/services';
import { useAuth } from '../../context/AuthContext';
import { useI18n } from '../../context/I18nContext';
import { Language } from '../../i18n/translations';

const TOPIC_OPTIONS = [
  'technology',
  'business',
  'education',
  'health',
  'sports',
  'politics',
  'science',
  'culture',
  'ai',
  'finance',
  'marketing',
  'travel',
];

const TOPIC_LABELS: Record<string, Record<Language, string>> = {
  technology: { ru: 'Технологии', en: 'Technology', uz: 'Texnologiya' },
  business: { ru: 'Бизнес', en: 'Business', uz: 'Biznes' },
  education: { ru: 'Образование', en: 'Education', uz: "Ta'lim" },
  health: { ru: 'Здоровье', en: 'Health', uz: "Sog'liq" },
  sports: { ru: 'Спорт', en: 'Sports', uz: 'Sport' },
  politics: { ru: 'Политика', en: 'Politics', uz: 'Siyosat' },
  science: { ru: 'Наука', en: 'Science', uz: 'Fan' },
  culture: { ru: 'Культура', en: 'Culture', uz: 'Madaniyat' },
  ai: { ru: 'ИИ', en: 'AI', uz: "Sun'iy intellekt" },
  finance: { ru: 'Финансы', en: 'Finance', uz: 'Moliya' },
  marketing: { ru: 'Маркетинг', en: 'Marketing', uz: 'Marketing' },
  travel: { ru: 'Путешествия', en: 'Travel', uz: 'Sayohat' },
};

type Mode = 'login' | 'register';
type RegisterStep = 'account' | 'verify' | 'interests';
type CountryOption = { isoCode: string; label: string; englishName: string };
type CityOption = { name: string; stateCode: string };

function normalizeLanguage(language: Language): string {
  if (language === 'ru') {
    return 'ru-RU';
  }
  if (language === 'uz') {
    return 'uz-UZ';
  }
  return 'en-US';
}

function toErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object') {
    return fallback;
  }

  const maybeAny = error as {
    response?: { data?: { detail?: string | Array<{ msg?: string }> } };
    message?: string;
  };

  const detail = maybeAny.response?.data?.detail;
  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first.msg === 'string') {
      return first.msg;
    }
  }

  if (typeof maybeAny.message === 'string' && maybeAny.message.trim()) {
    return maybeAny.message;
  }

  return fallback;
}

function getTopicLabel(topic: string, language: Language): string {
  return TOPIC_LABELS[topic]?.[language] ?? topic;
}

function dedupeItems(items: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  for (const item of items) {
    const value = item.trim();
    if (!value) {
      continue;
    }
    const normalized = value.toLowerCase();
    if (seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(value);
  }

  return result;
}

export function AuthPage() {
  const navigate = useNavigate();
  const { user, login, isLoading } = useAuth();
  const { t, language } = useI18n();

  const [mode, setMode] = useState<Mode>('login');
  const [registerStep, setRegisterStep] = useState<RegisterStep>('account');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [registerPassword, setRegisterPassword] = useState('');

  const [verificationId, setVerificationId] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [debugCode, setDebugCode] = useState('');

  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [customTopics, setCustomTopics] = useState<string[]>([]);
  const [topicSearch, setTopicSearch] = useState('');
  const [customTopicInput, setCustomTopicInput] = useState('');

  const [profession, setProfession] = useState('');

  const [countryCode, setCountryCode] = useState('');
  const [countryName, setCountryName] = useState('');
  const [countryInput, setCountryInput] = useState('');
  const [isCountryOpen, setIsCountryOpen] = useState(false);

  const [cityInput, setCityInput] = useState('');
  const [regionCode, setRegionCode] = useState('');
  const [isCityOpen, setIsCityOpen] = useState(false);

  useEffect(() => {
    if (!isLoading && user) {
      navigate('/app/home', { replace: true });
    }
  }, [isLoading, navigate, user]);

  const locale = useMemo(() => normalizeLanguage(language), [language]);

  const countries = useMemo<CountryOption[]>(() => {
    let formatter: Intl.DisplayNames | null = null;
    try {
      formatter = new Intl.DisplayNames([locale], { type: 'region' });
    } catch {
      formatter = null;
    }

    const allCountries = Country.getAllCountries() as Array<{ isoCode: string; name: string }>;
    return allCountries
      .map((item) => {
        const localized = formatter?.of(item.isoCode) ?? item.name;
        return {
          isoCode: item.isoCode,
          label: localized,
          englishName: item.name,
        };
      })
      .sort((a, b) => a.label.localeCompare(b.label, locale));
  }, [locale]);

  const selectedCountry = useMemo(
    () => countries.find((item) => item.isoCode === countryCode) ?? null,
    [countries, countryCode],
  );

  useEffect(() => {
    if (selectedCountry) {
      setCountryName(selectedCountry.label);
      setCountryInput(selectedCountry.label);
    }
  }, [selectedCountry]);

  const filteredCountries = useMemo(() => {
    const query = countryInput.trim().toLowerCase();
    if (!query) {
      return countries.slice(0, 120);
    }

    return countries
      .filter((item) => {
        return (
          item.label.toLowerCase().includes(query) ||
          item.englishName.toLowerCase().includes(query) ||
          item.isoCode.toLowerCase().includes(query)
        );
      })
      .slice(0, 120);
  }, [countries, countryInput]);

  const cityOptions = useMemo<CityOption[]>(() => {
    if (!countryCode) {
      return [];
    }

    const rawCities = (City.getCitiesOfCountry(countryCode) || []) as Array<{ name: string; stateCode?: string }>;
    const byName = new Map<string, CityOption>();
    for (const item of rawCities) {
      const cityName = item.name?.trim();
      if (!cityName) {
        continue;
      }
      const key = cityName.toLowerCase();
      if (!byName.has(key)) {
        byName.set(key, {
          name: cityName,
          stateCode: item.stateCode || '',
        });
      }
    }

    return Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name, locale));
  }, [countryCode, locale]);

  const filteredCities = useMemo(() => {
    const query = cityInput.trim().toLowerCase();
    if (!query) {
      return cityOptions.slice(0, 120);
    }
    return cityOptions.filter((item) => item.name.toLowerCase().includes(query)).slice(0, 120);
  }, [cityOptions, cityInput]);

  const visibleTopicOptions = useMemo(() => {
    const selected = new Set(selectedTopics);
    const query = topicSearch.trim().toLowerCase();

    return TOPIC_OPTIONS.filter((topic) => {
      if (selected.has(topic)) {
        return false;
      }
      if (!query) {
        return true;
      }
      const label = getTopicLabel(topic, language).toLowerCase();
      return label.includes(query) || topic.includes(query);
    });
  }, [language, selectedTopics, topicSearch]);

  const stepTitle = useMemo(() => {
    if (registerStep === 'account') {
      return t('auth.step.account');
    }
    if (registerStep === 'verify') {
      return t('auth.step.verify');
    }
    return t('auth.step.interests');
  }, [registerStep, t]);

  const submitLogin = async (loginIdentifier: string, loginPassword: string) => {
    const tokenResponse = await authService.login({
      identifier: loginIdentifier,
      password: loginPassword,
    });

    localStorage.setItem('token', tokenResponse.access_token);
    const currentUser = await authService.getMe();
    login(tokenResponse.access_token, currentUser);
    navigate('/app/home', { replace: true });
  };

  const resetRegisterFlow = () => {
    setRegisterStep('account');
    setVerificationId('');
    setVerificationCode('');
    setDebugCode('');
    setSelectedTopics([]);
    setCustomTopics([]);
    setTopicSearch('');
    setCustomTopicInput('');
    setProfession('');
    setCountryCode('');
    setCountryName('');
    setCountryInput('');
    setCityInput('');
    setRegionCode('');
  };

  const startRegistration = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setInfo('');
    setIsSubmitting(true);

    try {
      const availability = await authService.checkAvailability({ username, email });
      if (availability.username_exists) {
        throw new Error(t('auth.availability.usernameExists'));
      }
      if (availability.email_exists) {
        throw new Error(t('auth.availability.emailExists'));
      }

      const started = await authService.registerStart({
        username,
        email,
        password: registerPassword,
      });

      setVerificationId(started.verification_id);
      setDebugCode(started.debug_code || '');
      setRegisterStep('verify');

      if (started.debug_code) {
        setInfo(t('auth.info.debugCode', { code: started.debug_code }));
      } else {
        setInfo(t('auth.info.codeSent'));
      }
    } catch (err) {
      setError(toErrorMessage(err, t('common.networkFallback')));
    } finally {
      setIsSubmitting(false);
    }
  };

  const verifyCode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setInfo('');
    setIsSubmitting(true);

    try {
      await authService.verifyCode({
        verification_id: verificationId,
        code: verificationCode,
      });
      setRegisterStep('interests');
      setInfo(t('auth.info.verified'));
    } catch (err) {
      setError(toErrorMessage(err, t('common.networkFallback')));
    } finally {
      setIsSubmitting(false);
    }
  };

  const completeRegistration = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setInfo('');

    const normalizedTopics = dedupeItems(selectedTopics);
    const normalizedCustom = dedupeItems(customTopics);
    if (normalizedTopics.length === 0 && normalizedCustom.length === 0) {
      setError(t('auth.interests.requiredError'));
      return;
    }
    if (!countryCode) {
      setError(t('auth.location.requiredCountry'));
      return;
    }
    if (!cityInput.trim()) {
      setError(t('auth.location.requiredCity'));
      return;
    }

    setIsSubmitting(true);

    try {
      await authService.registerComplete({
        verification_id: verificationId,
        interests: normalizedTopics,
        custom_interests: normalizedCustom,
        profession: profession || null,
        country_code: countryCode,
        country_name: countryName || selectedCountry?.label || null,
        city: cityInput.trim(),
        region_code: regionCode || null,
      });

      await submitLogin(email, registerPassword);
    } catch (err) {
      setError(toErrorMessage(err, t('common.networkFallback')));
    } finally {
      setIsSubmitting(false);
    }
  };

  const onLoginSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setInfo('');
    setIsSubmitting(true);

    try {
      await submitLogin(identifier, password);
    } catch (err) {
      localStorage.removeItem('token');
      setError(toErrorMessage(err, t('common.networkFallback')));
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleTopic = (topic: string) => {
    setSelectedTopics((prev) => {
      if (prev.includes(topic)) {
        return prev.filter((item) => item !== topic);
      }
      return [...prev, topic];
    });
  };

  const addCustomTopic = () => {
    const next = dedupeItems([...customTopics, customTopicInput]);
    setCustomTopics(next);
    setCustomTopicInput('');
  };

  const onCustomTopicKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter' && event.key !== ',') {
      return;
    }
    event.preventDefault();
    if (customTopicInput.trim()) {
      addCustomTopic();
    }
  };

  const removeCustomTopic = (topic: string) => {
    setCustomTopics((prev) => prev.filter((item) => item.toLowerCase() !== topic.toLowerCase()));
  };

  const selectCountry = (item: CountryOption) => {
    setCountryCode(item.isoCode);
    setCountryName(item.label);
    setCountryInput(item.label);
    setCityInput('');
    setRegionCode('');
    setIsCountryOpen(false);
  };

  const selectCity = (item: CityOption) => {
    setCityInput(item.name);
    setRegionCode(item.stateCode || '');
    setIsCityOpen(false);
  };

  return (
    <div className="w-full max-w-3xl rounded-xl border border-outline-variant/30 bg-surface-container-low p-8 shadow-sm">
      <h1 className="mb-2 text-3xl font-bold tracking-tight text-on-surface">{t('auth.title')}</h1>
      <p className="mb-6 text-sm text-on-surface-variant">{t('auth.subtitle')}</p>

      <div className="mb-6 flex gap-2 rounded-lg bg-surface-container p-1">
        <button
          type="button"
          onClick={() => {
            setMode('login');
            setError('');
            setInfo('');
          }}
          className={`flex-1 rounded-md px-4 py-2 text-sm font-semibold transition ${
            mode === 'login' ? 'bg-primary-container text-white' : 'text-on-surface-variant hover:text-on-surface'
          }`}
        >
          {t('auth.mode.login')}
        </button>
        <button
          type="button"
          onClick={() => {
            setMode('register');
            setError('');
            setInfo('');
            resetRegisterFlow();
          }}
          className={`flex-1 rounded-md px-4 py-2 text-sm font-semibold transition ${
            mode === 'register' ? 'bg-primary-container text-white' : 'text-on-surface-variant hover:text-on-surface'
          }`}
        >
          {t('auth.mode.register')}
        </button>
      </div>

      {mode === 'login' ? (
        <form className="space-y-4" onSubmit={onLoginSubmit}>
          <div>
            <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="identifier">
              {t('auth.login.identifier')}
            </label>
            <input
              id="identifier"
              className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container"
              required
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder="demo@example.com"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="loginPassword">
              {t('auth.login.password')}
            </label>
            <input
              id="loginPassword"
              type="password"
              className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container"
              required
              minLength={8}
              maxLength={128}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="********"
            />
          </div>

          {error ? <p className="rounded-md bg-error-container px-3 py-2 text-sm text-on-error-container">{error}</p> : null}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-lg bg-primary-container px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? t('auth.login.submitting') : t('auth.login.submit')}
          </button>
        </form>
      ) : null}

      {mode === 'register' ? (
        <>
          <div className="mb-3 rounded-md bg-surface-container px-3 py-2 text-xs font-medium text-on-surface-variant">{stepTitle}</div>

          {registerStep === 'account' ? (
            <form className="space-y-4" onSubmit={startRegistration}>
              <div>
                <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="username">
                  {t('auth.register.username')}
                </label>
                <input
                  id="username"
                  className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container"
                  required
                  minLength={3}
                  maxLength={100}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="my_login"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="email">
                  {t('auth.register.email')}
                </label>
                <input
                  id="email"
                  type="email"
                  className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="mail@example.com"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="registerPassword">
                  {t('auth.register.password')}
                </label>
                <input
                  id="registerPassword"
                  type="password"
                  className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container"
                  required
                  minLength={8}
                  maxLength={128}
                  value={registerPassword}
                  onChange={(event) => setRegisterPassword(event.target.value)}
                  placeholder="********"
                />
              </div>

              {error ? <p className="rounded-md bg-error-container px-3 py-2 text-sm text-on-error-container">{error}</p> : null}
              {info ? <p className="rounded-md bg-surface-container px-3 py-2 text-sm text-on-surface-variant">{info}</p> : null}

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full rounded-lg bg-primary-container px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSubmitting ? t('auth.register.sending') : t('auth.register.sendCode')}
              </button>
            </form>
          ) : null}

          {registerStep === 'verify' ? (
            <form className="space-y-4" onSubmit={verifyCode}>
              <div>
                <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="verificationCode">
                  {t('auth.verify.code')}
                </label>
                <input
                  id="verificationCode"
                  className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container"
                  required
                  value={verificationCode}
                  onChange={(event) => setVerificationCode(event.target.value)}
                  placeholder="6-digit code"
                />
              </div>

              {debugCode ? (
                <p className="rounded-md bg-surface-container px-3 py-2 text-sm text-on-surface-variant">
                  {t('auth.verify.debug')}: <strong>{debugCode}</strong>
                </p>
              ) : null}

              {error ? <p className="rounded-md bg-error-container px-3 py-2 text-sm text-on-error-container">{error}</p> : null}
              {info ? <p className="rounded-md bg-surface-container px-3 py-2 text-sm text-on-surface-variant">{info}</p> : null}

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full rounded-lg bg-primary-container px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSubmitting ? t('auth.verify.submitting') : t('auth.verify.submit')}
              </button>
            </form>
          ) : null}

          {registerStep === 'interests' ? (
            <form className="space-y-5" onSubmit={completeRegistration}>
              <div>
                <p className="mb-2 text-sm font-medium text-on-surface">{t('auth.interests.required')}</p>

                <div className="rounded-xl border border-outline-variant/40 bg-white p-3">
                  <div className="mb-3 flex flex-wrap gap-2">
                    {selectedTopics.map((topic) => (
                      <button
                        key={topic}
                        type="button"
                        onClick={() => toggleTopic(topic)}
                        className="rounded-full border border-primary-container/40 bg-primary-container/10 px-3 py-1 text-xs font-semibold text-on-surface"
                      >
                        {getTopicLabel(topic, language)} ×
                      </button>
                    ))}

                    {customTopics.map((topic) => (
                      <button
                        key={topic}
                        type="button"
                        onClick={() => removeCustomTopic(topic)}
                        className="rounded-full border border-secondary/30 bg-secondary-container/40 px-3 py-1 text-xs font-semibold text-on-surface"
                      >
                        {topic} ×
                      </button>
                    ))}
                  </div>

                  <input
                    className="mb-3 w-full rounded-lg border border-outline-variant/40 px-3 py-2 text-sm outline-none focus:border-primary-container"
                    value={topicSearch}
                    onChange={(event) => setTopicSearch(event.target.value)}
                    placeholder={t('auth.interests.search')}
                  />

                  <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                    {visibleTopicOptions.map((topic) => (
                      <button
                        key={topic}
                        type="button"
                        onClick={() => toggleTopic(topic)}
                        className="rounded-lg border border-outline-variant/40 bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant transition hover:border-primary-container/50 hover:text-on-surface"
                      >
                        {getTopicLabel(topic, language)}
                      </button>
                    ))}
                  </div>

                  {visibleTopicOptions.length === 0 ? (
                    <p className="mt-2 text-xs text-on-surface-variant">{t('auth.interests.empty')}</p>
                  ) : null}

                  <div className="mt-4">
                    <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-on-surface-variant" htmlFor="customTopic">
                      {t('auth.interests.customLabel')}
                    </label>
                    <div className="flex gap-2">
                      <input
                        id="customTopic"
                        value={customTopicInput}
                        onChange={(event) => setCustomTopicInput(event.target.value)}
                        onKeyDown={onCustomTopicKeyDown}
                        className="flex-1 rounded-lg border border-outline-variant/40 px-3 py-2 text-sm outline-none focus:border-primary-container"
                        placeholder={t('auth.interests.customPlaceholder')}
                      />
                      <button
                        type="button"
                        onClick={addCustomTopic}
                        className="rounded-lg bg-primary-container px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90"
                      >
                        {t('auth.interests.add')}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="profession">
                  {t('auth.profession')}
                </label>
                <input
                  id="profession"
                  className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container"
                  value={profession}
                  onChange={(event) => setProfession(event.target.value)}
                  placeholder="Product manager"
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="relative">
                  <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="countrySearch">
                    {t('auth.country')}
                  </label>
                  <input
                    id="countrySearch"
                    value={countryInput}
                    onFocus={() => setIsCountryOpen(true)}
                    onBlur={() => window.setTimeout(() => setIsCountryOpen(false), 120)}
                    onChange={(event) => {
                      setCountryInput(event.target.value);
                      setCountryCode('');
                      setCountryName('');
                      setCityInput('');
                      setRegionCode('');
                      setIsCountryOpen(true);
                    }}
                    className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container"
                    placeholder={t('auth.country.placeholder')}
                    required
                  />

                  {isCountryOpen ? (
                    <div className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-outline-variant/40 bg-white p-1 shadow">
                      {filteredCountries.length > 0 ? (
                        filteredCountries.map((item) => (
                          <button
                            key={item.isoCode}
                            type="button"
                            onMouseDown={(event) => {
                              event.preventDefault();
                              selectCountry(item);
                            }}
                            className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-surface-container"
                          >
                            <span>{item.label}</span>
                            <span className="text-xs uppercase text-on-surface-variant">{item.isoCode}</span>
                          </button>
                        ))
                      ) : (
                        <p className="px-3 py-2 text-sm text-on-surface-variant">{t('auth.country.noResults')}</p>
                      )}
                    </div>
                  ) : null}
                </div>

                <div className="relative">
                  <label className="mb-1 block text-sm font-medium text-on-surface" htmlFor="citySearch">
                    {t('auth.city')}
                  </label>
                  <input
                    id="citySearch"
                    value={cityInput}
                    onFocus={() => setIsCityOpen(true)}
                    onBlur={() => window.setTimeout(() => setIsCityOpen(false), 120)}
                    onChange={(event) => {
                      const next = event.target.value;
                      setCityInput(next);
                      setRegionCode('');
                      setIsCityOpen(true);
                    }}
                    className="w-full rounded-lg border border-outline-variant/40 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-primary-container disabled:bg-surface-container"
                    placeholder={t('auth.city.placeholder')}
                    disabled={!countryCode}
                    required
                  />

                  {isCityOpen && countryCode ? (
                    <div className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-outline-variant/40 bg-white p-1 shadow">
                      {filteredCities.length > 0 ? (
                        filteredCities.map((item) => (
                          <button
                            key={`${item.name}-${item.stateCode}`}
                            type="button"
                            onMouseDown={(event) => {
                              event.preventDefault();
                              selectCity(item);
                            }}
                            className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-surface-container"
                          >
                            <span>{item.name}</span>
                            {item.stateCode ? (
                              <span className="text-xs uppercase text-on-surface-variant">{item.stateCode}</span>
                            ) : null}
                          </button>
                        ))
                      ) : (
                        <p className="px-3 py-2 text-sm text-on-surface-variant">{t('auth.city.noResults')}</p>
                      )}
                    </div>
                  ) : null}

                  {!countryCode ? <p className="mt-1 text-xs text-on-surface-variant">{t('auth.city.selectCountryFirst')}</p> : null}
                </div>
              </div>

              {error ? <p className="rounded-md bg-error-container px-3 py-2 text-sm text-on-error-container">{error}</p> : null}
              {info ? <p className="rounded-md bg-surface-container px-3 py-2 text-sm text-on-surface-variant">{info}</p> : null}

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full rounded-lg bg-primary-container px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSubmitting ? t('auth.complete.submitting') : t('auth.complete.submit')}
              </button>
            </form>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
