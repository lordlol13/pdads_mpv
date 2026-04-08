import { Bookmark, LogOut, RefreshCw, UserRound } from 'lucide-react';
import { Link } from 'react-router-dom';

import { LanguageSwitcher } from '../../components/ui/LanguageSwitcher';
import { useAuth } from '../../context/AuthContext';
import { useI18n } from '../../context/I18nContext';
import { useNewsFeed } from '../../hooks/useNews';
import { getUzbekHeadlineFallback, normalizeFeedTitle } from '../../lib/newsText';

export function ProfilePage() {
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const { data: feedItems, isLoading, refetch } = useNewsFeed();

  const savedItems = feedItems.filter((item) => Boolean(item.saved));

  return (
    <div className="min-h-screen bg-black px-4 pb-24 pt-6 text-white">
      <div className="mx-auto max-w-xl space-y-4">
        <h1 className="text-xl font-bold">{t('profile.title')}</h1>

        <section className="rounded-2xl border border-white/15 bg-white/10 p-4 backdrop-blur">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white/15">
              <UserRound size={20} />
            </div>
            <div>
              <p className="text-sm text-white/70">{t('profile.username')}</p>
              <p className="font-semibold">{user?.username || 'User'}</p>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-white/15 bg-white/10 p-4 backdrop-blur">
          <p className="mb-3 text-sm font-semibold text-white/80">{t('profile.language')}</p>
          <LanguageSwitcher inline />
        </section>

        <section className="rounded-2xl border border-white/15 bg-white/10 p-4 backdrop-blur">
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-white/90">{t('profile.saved.title')}</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-lg border border-white/20 px-2 py-1 text-xs text-white/85 hover:bg-white/10"
              title={t('common.refresh')}
            >
              <span className="inline-flex items-center gap-1">
                <RefreshCw size={12} />
                {t('common.refresh')}
              </span>
            </button>
          </div>

          <p className="mb-3 text-xs text-white/65">{t('profile.saved.count', { count: savedItems.length })}</p>

          {isLoading ? <p className="text-sm text-white/70">{t('common.loading')}</p> : null}

          {!isLoading && savedItems.length === 0 ? <p className="text-sm text-white/70">{t('profile.saved.empty')}</p> : null}

          {!isLoading && savedItems.length > 0 ? (
            <div className="space-y-2">
              {savedItems.slice(0, 7).map((item) => (
                <Link
                  key={item.user_feed_id}
                  to="/app/home"
                  className="flex items-start gap-2 rounded-xl border border-white/15 bg-black/25 px-3 py-2 hover:bg-black/35"
                >
                  <Bookmark size={14} className="mt-0.5 text-blue-300" />
                  <div>
                    <p className="line-clamp-2 text-sm font-medium text-white/90">
                      {normalizeFeedTitle(item.final_title) || getUzbekHeadlineFallback(item.ai_news_id)}
                    </p>
                    <p className="mt-0.5 text-xs text-white/60">{item.category || t('feed.category.general')}</p>
                  </div>
                </Link>
              ))}
            </div>
          ) : null}
        </section>

        <section className="rounded-2xl border border-white/15 bg-white/10 p-4 backdrop-blur">
          <p className="text-sm font-semibold text-white/90">{t('profile.settings.title')}</p>
          <p className="mt-2 text-sm text-white/70">{t('profile.settings.hint')}</p>
        </section>

        <button
          type="button"
          onClick={logout}
          className="flex w-full items-center justify-center gap-2 rounded-2xl border border-red-300/25 bg-red-500/20 px-4 py-3 text-sm font-semibold text-red-100 transition hover:bg-red-500/30"
        >
          <LogOut size={16} />
          {t('common.logout')}
        </button>
      </div>
    </div>
  );
}
