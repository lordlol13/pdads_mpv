import { Search } from 'lucide-react';

import { useI18n } from '../../context/I18nContext';

export function SearchPage() {
  const { t } = useI18n();

  return (
    <div className="min-h-screen bg-black px-4 pb-24 pt-6 text-white">
      <div className="mx-auto max-w-xl">
        <h1 className="text-xl font-bold">{t('search.title')}</h1>

        <div className="mt-4 rounded-2xl border border-white/20 bg-white/10 p-3 backdrop-blur">
          <label className="flex items-center gap-2 rounded-xl border border-white/20 bg-black/35 px-3 py-2">
            <Search size={16} className="text-white/70" />
            <input
              type="text"
              placeholder={t('search.placeholder')}
              className="w-full bg-transparent text-sm text-white placeholder:text-white/60 outline-none"
            />
          </label>
        </div>

        <p className="mt-4 text-sm text-white/70">{t('search.hint')}</p>
      </div>
    </div>
  );
}
