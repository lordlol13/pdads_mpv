import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { Bookmark, ChevronDown, ChevronLeft, Globe, Home, Moon, RefreshCw, Search, Settings, Sun, User } from 'lucide-react';

import { authService, newsService } from '../api/services';
import { useLanguage } from '../context/LanguageContext';
import { FeedItem, UserPublic } from '../types';
import { BackendFeedPost } from './BackendFeedPost';

interface BackendMainFeedProps {
  currentUser: UserPublic | null;
  onLogout: () => void;
}

const LANGUAGES: Array<{ name: string; code: 'uz' | 'ru' | 'en' }> = [
  { name: "O'zbekcha", code: 'uz' },
  { name: 'Русский', code: 'ru' },
  { name: 'English', code: 'en' },
];

function previewText(item: FeedItem): string {
  return (item.final_title || item.final_text || item.target_persona || item.category || 'News item').trim();
}

function personaBadge(item: FeedItem): string {
  const raw = (item.target_persona || '').trim();
  if (!raw) {
    return (item.category || 'general').trim();
  }

  const tokens = raw
    .split('|')
    .map((token) => token.trim())
    .filter(Boolean)
    .slice(0, 4)
    .map((token) => {
      if (/^[a-z]{2,3}$/i.test(token)) {
        return token.toUpperCase();
      }
      return token
        .replace(/[_-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .split(' ')
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
    });

  return tokens.join(' • ') || (item.category || 'general').trim();
}

export function BackendMainFeed({ currentUser, onLogout }: BackendMainFeedProps) {
  const { language, setLanguage, t } = useLanguage();
  const [feedData, setFeedData] = useState<FeedItem[]>([]);
  const [isFeedLoading, setIsFeedLoading] = useState(true);
  const [feedError, setFeedError] = useState('');
  const [activeTab, setActiveTab] = useState<'home' | 'search' | 'profile'>('home');
  const [showSavedOnly, setShowSavedOnly] = useState(false);
  const [activePostIndex, setActivePostIndex] = useState(0);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<FeedItem[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [homeRefreshing, setHomeRefreshing] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);
  const viewedIds = useRef<Set<number>>(new Set());

  const loadFeed = useCallback(async () => {
    setIsFeedLoading(true);
    setFeedError('');
    try {
      const items = await newsService.getFeed(50);
      setFeedData(items);
    } catch (error) {
      setFeedError(error instanceof Error ? error.message : 'Unable to load feed');
    } finally {
      setIsFeedLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFeed();
  }, [currentUser?.id, loadFeed]);

  useEffect(() => {
    const query = searchQuery.trim();
    if (query.length < 2) {
      setSearchResults([]);
      setSearchError('');
      setSearchLoading(false);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setSearchLoading(true);
      setSearchError('');
      try {
        const results = await newsService.search(query, 30);
        if (!cancelled) {
          setSearchResults(results);
        }
      } catch (error) {
        if (!cancelled) {
          setSearchError(error instanceof Error ? error.message : 'Unable to search');
        }
      } finally {
        if (!cancelled) {
          setSearchLoading(false);
        }
      }
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [searchQuery]);

  useEffect(() => {
    if (feedRef.current && activeTab === 'home') {
      feedRef.current.scrollTo({
        top: activePostIndex * feedRef.current.clientHeight,
        behavior: 'smooth',
      });
    }
  }, [activePostIndex, activeTab]);

  const savedPosts = useMemo(() => feedData.filter((post) => Boolean(post.saved)), [feedData]);

  const handleFeedScroll = () => {
    if (!feedRef.current) {
      return;
    }
    const index = Math.round(feedRef.current.scrollTop / feedRef.current.clientHeight);
    setActivePostIndex(index);
  };

  const handleToggleSaved = async (aiNewsId: number) => {
    const response = await newsService.toggleSaved({ ai_news_id: aiNewsId });
    setFeedData((previous) =>
      previous.map((item) => (item.ai_news_id === aiNewsId ? { ...item, saved: response.saved } : item)),
    );
    return response.saved;
  };

  const handleReactToNews = async (aiNewsId: number, liked: boolean) => {
    if (!currentUser) {
      return;
    }
    await newsService.react({ user_id: currentUser.id, ai_news_id: aiNewsId, liked });
    setFeedData((previous) =>
      previous.map((item) => (item.ai_news_id === aiNewsId ? { ...item, liked } : item)),
    );
  };

  const handleViewed = async (aiNewsId: number) => {
    if (!currentUser || viewedIds.current.has(aiNewsId)) {
      return;
    }
    viewedIds.current.add(aiNewsId);
    try {
      await newsService.react({ user_id: currentUser.id, ai_news_id: aiNewsId, viewed: true });
    } catch {
      viewedIds.current.delete(aiNewsId);
    }
  };

  const scrollToItem = (aiNewsId: number) => {
    const index = feedData.findIndex((item) => item.ai_news_id === aiNewsId);
    if (index >= 0) {
      setActiveTab('home');
      setShowSavedOnly(false);
      setActivePostIndex(index);
    }
  };

  const handleLogout = () => {
    authService.logout();
    onLogout();
  };

  return (
    <div className={`fixed inset-0 flex flex-col transition-colors duration-500 ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'}`}>
      <div className="flex-1 relative overflow-hidden">
        {activeTab === 'home' ? (
          <div ref={feedRef} onScroll={handleFeedScroll} className="h-full overflow-y-scroll snap-y snap-mandatory scrollbar-hide">
            {isFeedLoading ? (
              <div className="flex h-full items-center justify-center px-4 text-sm text-white/70">{t.loading}</div>
            ) : feedError ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-4 text-center">
                <p className="text-sm text-red-300">{feedError}</p>
                <button
                  type="button"
                  onClick={() => void loadFeed()}
                  className="rounded-full border border-white/20 px-4 py-2 text-sm text-white/85 hover:bg-white/10"
                >
                  {t.refresh}
                </button>
              </div>
            ) : feedData.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 px-4 text-center">
                <p className="text-lg font-bold">{t.feedEmptyTitle ?? 'Feed is empty'}</p>
                <p className="text-sm text-white/60">{t.feedEmptyText ?? 'Run ingestion/pipeline and refresh feed.'}</p>
                <button
                  type="button"
                  onClick={() => void loadFeed()}
                  className="rounded-full border border-white/20 px-4 py-2 text-sm text-white/85 hover:bg-white/10"
                >
                  {t.refresh}
                </button>
              </div>
            ) : (
              feedData.map((item, index) => (
                <BackendFeedPost
                  key={item.ai_news_id}
                  item={item}
                  isActive={activePostIndex === index}
                  currentUserId={currentUser?.id ?? 0}
                  onToggleSaved={handleToggleSaved}
                  onReactToNews={handleReactToNews}
                  onViewed={handleViewed}
                />
              ))
            )}
          </div>
        ) : null}

        {activeTab === 'search' ? (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className={`h-full overflow-y-auto p-6 pt-20 space-y-6 ${theme === 'dark' ? 'bg-black' : 'bg-zinc-50'}`}
          >
            <div className="space-y-2">
              <h2 className="text-3xl font-bold">{t.explore}</h2>
              <p className="text-sm text-white/60">{t.searchPlaceholder}</p>
            </div>
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder={t.searchPlaceholder}
                className={`w-full h-14 rounded-2xl pl-12 pr-4 outline-none transition-all ${theme === 'dark' ? 'bg-zinc-900 text-white border border-white/5 focus:ring-1 focus:ring-white/10' : 'bg-white text-black border border-zinc-200 focus:ring-1 focus:ring-black/10'}`}
              />
            </div>

            {searchLoading ? <p className="text-sm text-white/60">{t.loading}</p> : null}
            {searchError ? <p className="text-sm text-red-300">{searchError}</p> : null}

            {!searchLoading && !searchError && searchResults.length === 0 && searchQuery.trim().length >= 2 ? (
              <p className="text-sm text-white/60">{t.searchNoResults ?? 'No results found.'}</p>
            ) : null}

            <div className="space-y-4">
              {searchResults.map((item) => (
                <button
                  key={item.ai_news_id}
                  type="button"
                  onClick={() => scrollToItem(item.ai_news_id)}
                  className={`w-full rounded-3xl border p-4 text-left transition-colors ${theme === 'dark' ? 'bg-zinc-900 border-white/5 hover:bg-zinc-800' : 'bg-white border-zinc-200 hover:bg-zinc-50'}`}
                >
                  <div className="flex items-start gap-4">
                    <div className="h-20 w-20 overflow-hidden rounded-2xl bg-black/20">
                      {item.image_urls?.[0] ? (
                        <img src={item.image_urls[0]} alt={previewText(item)} className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full items-center justify-center text-xs text-white/40">news</div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs uppercase tracking-widest text-white/50">{personaBadge(item)}</span>
                        <span className="text-xs text-white/50">{item.saved ? 'saved' : ''}</span>
                      </div>
                      <p className="font-semibold leading-snug">{previewText(item)}</p>
                      <p className="line-clamp-2 text-sm text-white/60">{item.final_text || ''}</p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </motion.div>
        ) : null}

        {activeTab === 'profile' ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className={`h-full overflow-y-auto p-6 pt-20 space-y-8 ${theme === 'dark' ? 'bg-black' : 'bg-zinc-50'}`}
          >
            {showSavedOnly ? (
              <div className="space-y-6">
                <div className="flex items-center gap-4">
                  <button
                    onClick={() => setShowSavedOnly(false)}
                    className={`p-2 rounded-full transition-colors ${theme === 'dark' ? 'bg-zinc-900 hover:bg-zinc-800' : 'bg-white border border-zinc-200 hover:bg-zinc-100'}`}
                  >
                    <ChevronLeft className="w-6 h-6" />
                  </button>
                  <h2 className="text-2xl font-bold">{t.savedPosts}</h2>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  {savedPosts.map((post) => (
                    <button
                      key={post.ai_news_id}
                      type="button"
                      className={`aspect-[9/16] rounded-3xl overflow-hidden relative group cursor-pointer border text-left ${theme === 'dark' ? 'bg-zinc-900 border-white/5' : 'bg-white border-zinc-200'}`}
                      onClick={() => scrollToItem(post.ai_news_id)}
                    >
                      <img
                        src={post.image_urls?.[0] || post.video_urls?.[0] || 'https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&q=80&w=1400'}
                        alt={previewText(post)}
                        className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                        referrerPolicy="no-referrer"
                      />
                      <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-4">
                        <p className="text-xs font-medium line-clamp-2 text-white">{previewText(post)}</p>
                      </div>
                    </button>
                  ))}
                </div>
                {savedPosts.length === 0 ? (
                  <div className="text-center py-20 text-zinc-500">
                    <Bookmark className="w-12 h-12 mx-auto mb-4 opacity-20" />
                    <p>{t.noSavedPosts ?? 'No saved posts yet'}</p>
                  </div>
                ) : null}
              </div>
            ) : (
              <>
                <div className="flex flex-col items-center gap-4">
                  <div className={`w-24 h-24 rounded-full border-4 ${theme === 'dark' ? 'bg-zinc-900 border-white/5' : 'bg-white border-zinc-200'}`} />
                  <div className="text-center space-y-1">
                    <h2 className="text-2xl font-bold">{currentUser?.username || 'User'}</h2>
                    <p className="text-zinc-500 text-sm">{currentUser?.email || currentUser?.location || '@user'}</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <h3 className="text-sm font-bold text-zinc-500 uppercase tracking-widest px-2">{t.settings}</h3>
                  <div className={`rounded-[32px] overflow-hidden border ${theme === 'dark' ? 'bg-zinc-900 border-white/5' : 'bg-white border-zinc-200'}`}>
                    <button
                      onClick={() => setShowSavedOnly(true)}
                      className={`w-full flex items-center justify-between p-5 transition-colors group ${theme === 'dark' ? 'hover:bg-white/5' : 'hover:bg-zinc-50'}`}
                    >
                      <div className="flex items-center gap-4">
                        <div className="p-2 bg-blue-500/10 rounded-xl text-blue-500">
                          <Bookmark className="w-5 h-5" />
                        </div>
                        <span className="font-medium">{t.savedPosts}</span>
                      </div>
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${theme === 'dark' ? 'bg-white/5 group-hover:bg-white/10' : 'bg-zinc-100 group-hover:bg-zinc-200'}`}>
                        <ChevronDown className="w-4 h-4 text-zinc-400" />
                      </div>
                    </button>

                    <div className={`p-5 border-t ${theme === 'dark' ? 'border-white/5' : 'border-zinc-100'}`}>
                      <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-4">
                          <div className="p-2 bg-purple-500/10 rounded-xl text-purple-500">
                            <Globe className="w-5 h-5" />
                          </div>
                          <span className="font-medium">{t.language}</span>
                        </div>
                      </div>
                      <div className="relative">
                        <select
                          value={language}
                          onChange={(event) => setLanguage(event.target.value as 'uz' | 'ru' | 'en')}
                          className={`w-full h-12 border rounded-xl px-4 text-sm font-bold appearance-none outline-none cursor-pointer ${theme === 'dark' ? 'bg-black border-white/5 text-white focus:ring-1 focus:ring-white/10' : 'bg-zinc-50 border-zinc-200 text-black focus:ring-1 focus:ring-black/10'}`}
                        >
                          {LANGUAGES.map((lang) => (
                            <option key={lang.code} value={lang.code} className={theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'}>
                              {lang.name}
                            </option>
                          ))}
                        </select>
                        <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 pointer-events-none" />
                      </div>
                    </div>

                    <button
                      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                      className={`w-full flex items-center justify-between p-5 transition-colors border-t ${theme === 'dark' ? 'border-white/5 hover:bg-white/5' : 'border-zinc-100 hover:bg-zinc-50'}`}
                    >
                      <div className="flex items-center gap-4">
                        <div className="p-2 bg-yellow-500/10 rounded-xl text-yellow-500">
                          {theme === 'dark' ? <Moon className="w-5 h-5" /> : <Sun className="w-5 h-5" />}
                        </div>
                        <span className="font-medium">{t.theme}</span>
                      </div>
                      <div className={`w-12 h-6 rounded-full relative transition-colors ${theme === 'dark' ? 'bg-zinc-700' : 'bg-zinc-200'}`}>
                        <div className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow-sm transition-all ${theme === 'dark' ? 'left-7' : 'left-1'}`} />
                      </div>
                    </button>

                    <button className={`w-full flex items-center justify-between p-5 transition-colors border-t ${theme === 'dark' ? 'border-white/5 hover:bg-white/5' : 'border-zinc-100 hover:bg-zinc-50'}`}>
                      <div className="flex items-center gap-4">
                        <div className="p-2 bg-red-500/10 rounded-xl text-red-500">
                          <Settings className="w-5 h-5" />
                        </div>
                        <span className="font-medium">{t.accountSettings}</span>
                      </div>
                    </button>

                    <button
                      type="button"
                      onClick={handleLogout}
                      className={`w-full flex items-center justify-between p-5 transition-colors border-t ${theme === 'dark' ? 'border-white/5 hover:bg-white/5' : 'border-zinc-100 hover:bg-zinc-50'}`}
                    >
                      <div className="flex items-center gap-4">
                        <div className="p-2 bg-white/10 rounded-xl text-white">
                          <User className="w-5 h-5" />
                        </div>
                        <span className="font-medium">{t.logout}</span>
                      </div>
                    </button>
                  </div>
                </div>
              </>
            )}
          </motion.div>
        ) : null}
      </div>

      <div className={`h-20 border-t transition-colors duration-500 flex items-center justify-around px-6 pb-2 ${theme === 'dark' ? 'bg-black border-white/10' : 'bg-white border-zinc-200'}`}>
        <button
          onClick={async () => {
            if (activeTab === 'home') {
              setHomeRefreshing(true);
              try {
                await loadFeed();
              } finally {
                setHomeRefreshing(false);
              }
              return;
            }
            setActiveTab('home');
          }}
          className={`flex flex-col items-center gap-1 transition-all ${activeTab === 'home' ? (theme === 'dark' ? 'text-white scale-110' : 'text-black scale-110') : 'text-zinc-500 hover:text-zinc-300'}`}
        >
          {homeRefreshing ? (
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 0.8, ease: 'linear', repeat: Infinity }}
            >
              <RefreshCw className="w-6 h-6" />
            </motion.div>
          ) : (
            <Home className={`w-6 h-6 ${activeTab === 'home' ? (theme === 'dark' ? 'fill-white' : 'fill-black') : ''}`} />
          )}
          <span className="text-[10px] font-bold uppercase tracking-widest">{t.home}</span>
        </button>

        <button
          onClick={() => setActiveTab('search')}
          className={`flex flex-col items-center gap-1 transition-all ${activeTab === 'search' ? (theme === 'dark' ? 'text-white scale-110' : 'text-black scale-110') : 'text-zinc-500 hover:text-zinc-300'}`}
        >
          <Search className="w-6 h-6" />
          <span className="text-[10px] font-bold uppercase tracking-widest">{t.search}</span>
        </button>

        <button
          onClick={() => setActiveTab('profile')}
          className={`flex flex-col items-center gap-1 transition-all ${activeTab === 'profile' ? (theme === 'dark' ? 'text-white scale-110' : 'text-black scale-110') : 'text-zinc-500 hover:text-zinc-300'}`}
        >
          <User className={`w-6 h-6 ${activeTab === 'profile' ? (theme === 'dark' ? 'fill-white' : 'fill-black') : ''}`} />
          <span className="text-[10px] font-bold uppercase tracking-widest">{t.profile}</span>
        </button>
      </div>
    </div>
  );
}
