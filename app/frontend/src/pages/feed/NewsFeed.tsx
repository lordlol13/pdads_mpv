import { type TouchEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Bookmark, Heart, MessageCircle, RefreshCw, X } from 'lucide-react';

import { newsService } from '../../api/services';
import { useAuth } from '../../context/AuthContext';
import { useI18n } from '../../context/I18nContext';
import { useNewsFeed, useReactToNews } from '../../hooks/useNews';
import { getUzbekHeadlineFallback, normalizeFeedTitle } from '../../lib/newsText';
import { CommentItem, FeedItem } from '../../types';

const FALLBACK_IMAGE =
  'https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&q=80&w=1400';

const ENGLISH_STOPWORDS = new Set([
  'the', 'and', 'of', 'to', 'in', 'for', 'with', 'on', 'from', 'by', 'is', 'are', 'was', 'were',
  'after', 'before', 'into', 'warning', 'adds', 'uncertainty', 'shipping',
]);

function normalizeMediaUrl(url: string): string {
  const trimmed = url.trim();
  if (!trimmed) {
    return FALLBACK_IMAGE;
  }

  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }

  return FALLBACK_IMAGE;
}

function buildImageDedupeKey(url: string): string {
  const value = (url || '').trim();
  if (!value) {
    return '';
  }

  try {
    const parsed = new URL(value);
    const host = parsed.hostname.replace(/^www\./i, '').toLowerCase();
    let path = decodeURIComponent(parsed.pathname || '/').toLowerCase();
    path = path.replace(/\/+/g, '/');
    path = path.replace(/\b\d{2,4}x\d{2,4}\b/g, '{size}');
    path = path.replace(/(w|h|width|height|q|quality)[=_-]?\d{1,4}/g, '$1={n}');
    return `${host}${path}`;
  } catch {
    return value.toLowerCase();
  }
}

function getFeedImages(item: FeedItem): string[] {
  if (!Array.isArray(item.image_urls) || item.image_urls.length === 0) {
    return [FALLBACK_IMAGE];
  }

  const prepared = item.image_urls
    .map((url) => normalizeMediaUrl(url))
    .filter(Boolean);

  const uniqueByKey = new Map<string, string>();
  for (const url of prepared) {
    const key = buildImageDedupeKey(url);
    if (!key || uniqueByKey.has(key)) {
      continue;
    }
    uniqueByKey.set(key, url);
    if (uniqueByKey.size >= 4) {
      break;
    }
  }

  const unique = Array.from(uniqueByKey.values());
  return unique.length > 0 ? unique : [FALLBACK_IMAGE];
}

function stripLikelyEnglishSentences(text: string): string {
  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .map((part) => part.trim())
    .filter(Boolean);

  const filtered = sentences.filter((sentence) => {
    const words = sentence.toLowerCase().match(/[a-z']+/g) || [];
    if (words.length < 5) {
      return true;
    }

    const hits = words.reduce((acc, word) => acc + (ENGLISH_STOPWORDS.has(word) ? 1 : 0), 0);
    return !(hits >= 2 && hits / words.length >= 0.2);
  });

  return filtered.join(' ').trim();
}

function formatScore(score: number | null): string {
  if (typeof score !== 'number') {
    return 'n/a';
  }
  return score.toFixed(2);
}

function normalizeArticleText(value: string): string {
  const cleaned = (value || '')
    .replace(/\r/g, '\n')
    .replace(/\[\+\d+\s+chars\]/gi, '')
    .replace(/\uFFFD/g, '')
    .replace(/\b(?:lid|yanglik|yangilik|headline|sarlavha)\b\s*:?/gi, '')
    .replace(/\b(?:news|новость|asosiy\s+yangilik)\b\s*:?/gi, '')
    .replace(/bo['’`]yicha\s+asosiy\s+yangilikni\s+qisqa\s+va\s+aniq\s+formatda\s+beraman\.?/gi, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\s{2,}/g, ' ')
    .trim();

  const uzbekOnly = stripLikelyEnglishSentences(cleaned);

  if (!uzbekOnly) {
    return '';
  }

  const paragraphs = uzbekOnly.split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean);
  if (paragraphs.length >= 2) {
    return paragraphs.join('\n\n');
  }

  const sentences = uzbekOnly.split(/(?<=[.!?])\s+/).map((part) => part.trim()).filter(Boolean);
  if (sentences.length >= 4) {
    const chunkSize = Math.ceil(sentences.length / 3);
    const chunks: string[] = [];
    for (let index = 0; index < sentences.length; index += chunkSize) {
      chunks.push(sentences.slice(index, index + chunkSize).join(' ').trim());
    }
    return chunks.filter(Boolean).join('\n\n');
  }

  return uzbekOnly;
}

function ImageWithSkeleton({ src, alt }: { src: string; alt: string }) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  return (
    <div
      className="relative w-full"
      style={{
        width: 'min(96vw, 980px)',
        aspectRatio: '16 / 9',
        background: '#222',
        borderRadius: '18px',
        overflow: 'hidden',
        boxShadow: '0 2px 16px rgba(0,0,0,0.18)',
      }}
    >
      {!loaded ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-neutral-800 animate-pulse">
          <svg width="64" height="64" fill="#444" viewBox="0 0 24 24">
            <rect width="100%" height="100%" rx="12" fill="#444" />
            <path d="M8 17l4-4 4 4M12 13V7" stroke="#888" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      ) : null}

      <img
        src={error ? FALLBACK_IMAGE : src}
        alt={alt}
        className="absolute inset-0 h-full w-full object-cover transition-opacity duration-500"
        style={{ opacity: loaded ? 1 : 0 }}
        onLoad={() => setLoaded(true)}
        onError={() => {
          setError(true);
          setLoaded(true);
        }}
        draggable={false}
      />
    </div>
  );
}

export function NewsFeed() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { data: feedItems, isLoading, isError, error, refetch } = useNewsFeed();
  const interactionMutation = useReactToNews();

  const [likedOverrides, setLikedOverrides] = useState<Record<number, boolean>>({});
  const [savedOverrides, setSavedOverrides] = useState<Record<number, boolean>>({});

  const [commentsOpenFor, setCommentsOpenFor] = useState<number | null>(null);
  const [commentsByNews, setCommentsByNews] = useState<Record<number, CommentItem[]>>({});
  const [commentsLoadingFor, setCommentsLoadingFor] = useState<number | null>(null);
  const [commentDraft, setCommentDraft] = useState('');
  const [replyTarget, setReplyTarget] = useState<{ commentId: number; username: string } | null>(null);
  const [commentError, setCommentError] = useState<string>('');
  const [textSheetItem, setTextSheetItem] = useState<FeedItem | null>(null);
  const [activeCardId, setActiveCardId] = useState<number | null>(null);
  const [imageIndexByCard, setImageIndexByCard] = useState<Record<number, number>>({});
  const [likePulseByCard, setLikePulseByCard] = useState<Record<number, boolean>>({});

  const feedContainerRef = useRef<HTMLElement | null>(null);
  const sectionRefs = useRef<Record<number, HTMLElement | null>>({});
  const imageSwipeStartXRef = useRef<Record<number, number | null>>({});
  const viewedAiNewsIdsRef = useRef<Set<number>>(new Set());
  const likeAnimationTimersRef = useRef<Record<number, number | null>>({});

  const orderedFeed = useMemo(() => {
    return [...feedItems].sort((a, b) => {
      const left = a.ai_score ?? -1;
      const right = b.ai_score ?? -1;
      if (left !== right) {
        return right - left;
      }
      return b.user_feed_id - a.user_feed_id;
    });
  }, [feedItems]);

  useEffect(() => {
    if (!orderedFeed.length) {
      setActiveCardId(null);
      return;
    }

    setActiveCardId((prev) => {
      if (prev && orderedFeed.some((item) => item.user_feed_id === prev)) {
        return prev;
      }
      return orderedFeed[0].user_feed_id;
    });
  }, [orderedFeed]);

  useEffect(() => {
    return () => {
      Object.values(likeAnimationTimersRef.current).forEach((timerId) => {
        if (timerId !== null) {
          window.clearTimeout(timerId);
        }
      });
    };
  }, []);

  useEffect(() => {
    if (!orderedFeed.length) {
      return;
    }

    const sections = orderedFeed
      .map((item) => sectionRefs.current[item.user_feed_id])
      .filter((node): node is HTMLElement => Boolean(node));

    if (!sections.length) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        let topVisible: { cardId: number; ratio: number } | null = null;

        for (const entry of entries) {
          if (!entry.isIntersecting) {
            continue;
          }

          const cardId = Number((entry.target as HTMLElement).dataset.cardId || '0');
          if (!cardId) {
            continue;
          }

          if (!topVisible || entry.intersectionRatio > topVisible.ratio) {
            topVisible = { cardId, ratio: entry.intersectionRatio };
          }
        }

        if (topVisible && topVisible.ratio >= 0.55) {
          setActiveCardId(topVisible.cardId);
        }
      },
      {
        root: feedContainerRef.current,
        threshold: [0.35, 0.55, 0.75],
      },
    );

    sections.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [orderedFeed]);

  useEffect(() => {
    if (!user || !activeCardId) {
      return;
    }

    const activeItem = orderedFeed.find((item) => item.user_feed_id === activeCardId);
    if (!activeItem) {
      return;
    }

    const aiNewsId = activeItem.ai_news_id;
    if (viewedAiNewsIdsRef.current.has(aiNewsId)) {
      return;
    }

    viewedAiNewsIdsRef.current.add(aiNewsId);

    void newsService
      .react({
        user_id: user.id,
        ai_news_id: aiNewsId,
        viewed: true,
        watch_time: 8,
      })
      .catch(() => {
        viewedAiNewsIdsRef.current.delete(aiNewsId);
      });
  }, [activeCardId, orderedFeed, user]);

  const handleImageChange = (cardId: number, imageCount: number, delta: number) => {
    if (imageCount < 2) {
      return;
    }

    setImageIndexByCard((prev) => {
      const currentIndex = prev[cardId] ?? 0;
      const nextIndex = (currentIndex + delta + imageCount) % imageCount;
      return { ...prev, [cardId]: nextIndex };
    });
  };

  const handleImageTouchStart = (cardId: number, event: TouchEvent<HTMLDivElement>) => {
    if (event.touches.length !== 1) {
      return;
    }
    imageSwipeStartXRef.current[cardId] = event.touches[0].clientX;
  };

  const handleImageTouchEnd = (cardId: number, imageCount: number, event: TouchEvent<HTMLDivElement>) => {
    if (imageCount < 2) {
      return;
    }

    const startX = imageSwipeStartXRef.current[cardId];
    imageSwipeStartXRef.current[cardId] = null;

    if (typeof startX !== 'number') {
      return;
    }

    const endX = event.changedTouches[0]?.clientX ?? startX;
    const delta = endX - startX;
    if (Math.abs(delta) < 40) {
      return;
    }

    handleImageChange(cardId, imageCount, delta < 0 ? 1 : -1);
  };

  const handleLikeToggle = (item: FeedItem, currentlyLiked: boolean) => {
    if (!user) {
      return;
    }

    const nextLiked = !currentlyLiked;
    const previousLiked = currentlyLiked;

    const existingTimer = likeAnimationTimersRef.current[item.ai_news_id];
    if (existingTimer !== null) {
      window.clearTimeout(existingTimer);
    }

    setLikePulseByCard((prev) => ({ ...prev, [item.ai_news_id]: true }));
    likeAnimationTimersRef.current[item.ai_news_id] = window.setTimeout(() => {
      setLikePulseByCard((prev) => ({ ...prev, [item.ai_news_id]: false }));
      likeAnimationTimersRef.current[item.ai_news_id] = null;
    }, 220);

    setLikedOverrides((prev) => ({ ...prev, [item.ai_news_id]: nextLiked }));

    interactionMutation.mutate(
      {
        user_id: user.id,
        ai_news_id: item.ai_news_id,
        liked: nextLiked,
      },
      {
        onSuccess: () => {
          // Keep the optimistic state and let the feed refetch update ranking in the background.
        },
        onError: () => {
          setLikedOverrides((prev) => ({ ...prev, [item.ai_news_id]: previousLiked }));
        },
      },
    );
  };

  const loadComments = async (aiNewsId: number) => {
    setCommentsLoadingFor(aiNewsId);
    setCommentError('');
    try {
      const data = await newsService.getComments(aiNewsId);
      setCommentsByNews((prev) => ({ ...prev, [aiNewsId]: data }));
    } catch {
      setCommentError(t('common.networkFallback'));
    } finally {
      setCommentsLoadingFor(null);
    }
  };

  const handleOpenComments = async (aiNewsId: number) => {
    setCommentsOpenFor(aiNewsId);
    setCommentDraft('');
    setReplyTarget(null);
    if (!commentsByNews[aiNewsId]) {
      await loadComments(aiNewsId);
    }
  };

  const handleToggleSaved = async (item: FeedItem) => {
    try {
      const response = await newsService.toggleSaved({ ai_news_id: item.ai_news_id });
      setSavedOverrides((prev) => ({ ...prev, [item.ai_news_id]: response.saved }));
    } catch {
      // Keep UI responsive on transient network issues.
    }
  };

  const handleSubmitComment = async () => {
    if (!commentsOpenFor) {
      return;
    }

    const content = commentDraft.trim();
    if (!content) {
      return;
    }

    setCommentError('');
    try {
      await newsService.createComment({
        ai_news_id: commentsOpenFor,
        parent_comment_id: replyTarget?.commentId ?? null,
        content,
      });
      setCommentDraft('');
      setReplyTarget(null);
      await loadComments(commentsOpenFor);
      await refetch();
    } catch {
      setCommentError(t('common.networkFallback'));
    }
  };

  const handleCommentLike = async (commentId: number) => {
    if (!commentsOpenFor) {
      return;
    }
    try {
      await newsService.toggleCommentLike(commentId);
      await loadComments(commentsOpenFor);
    } catch {
      setCommentError(t('common.networkFallback'));
    }
  };

  const activeComments = commentsOpenFor ? commentsByNews[commentsOpenFor] || [] : [];

  const renderCommentNodes = (items: CommentItem[], depth = 0): JSX.Element[] => {
    return items.map((comment) => (
      <div key={comment.id} className={`space-y-2 rounded-lg border border-outline-variant/20 bg-white p-3 ${depth > 0 ? 'ml-6' : ''}`}>
        <div className="flex items-center justify-between text-xs text-on-surface-variant">
          <span className="font-semibold text-on-surface">{comment.username}</span>
          <span>{comment.created_at ? new Date(comment.created_at).toLocaleString() : ''}</span>
        </div>

        <p className="text-sm text-on-surface">{comment.content}</p>

        <div className="flex items-center gap-3 text-xs">
          <button
            type="button"
            onClick={() => handleCommentLike(comment.id)}
            className={`inline-flex items-center gap-1 rounded-md px-2 py-1 ${comment.liked_by_me ? 'bg-primary-container text-white' : 'bg-surface-container text-on-surface-variant'}`}
          >
            <Heart size={13} fill={comment.liked_by_me ? 'currentColor' : 'none'} />
            {comment.like_count}
          </button>

          <button
            type="button"
            onClick={() => setReplyTarget({ commentId: comment.id, username: comment.username })}
            className="rounded-md bg-surface-container px-2 py-1 text-on-surface-variant"
          >
            {t('common.reply')}
          </button>
        </div>

        {Array.isArray(comment.replies) && comment.replies.length > 0 ? <div className="space-y-2 pt-1">{renderCommentNodes(comment.replies, depth + 1)}</div> : null}
      </div>
    ));
  };

  return (
    <div className="relative h-[100dvh] overflow-hidden bg-black text-white">
      <header className="pointer-events-none absolute inset-x-0 top-0 z-20">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <div className="pointer-events-auto">
            <p className="text-xs uppercase tracking-wide text-white/70">pdadsmvp</p>
            <h1 className="text-base font-bold">{t('feed.title')}</h1>
          </div>

          <div className="pointer-events-auto flex items-center gap-2 rounded-full bg-black/30 px-2 py-1 backdrop-blur">
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-full p-2 hover:bg-white/10"
              title={t('common.refresh')}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
      </header>

      <main ref={feedContainerRef} className="h-full overflow-y-auto snap-y snap-mandatory">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-white/80">{t('feed.loading')}</div>
        ) : null}

        {isError ? (
          <div className="mx-auto mt-24 w-[min(92vw,640px)] rounded-xl bg-red-600/90 p-4 text-sm text-white">
            <p>{t('feed.failed')}</p>
            <p className="mt-1 opacity-90">{String(error)}</p>
          </div>
        ) : null}

        {!isLoading && !isError && orderedFeed.length === 0 ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-white/85">
            <div>
              <h2 className="text-lg font-semibold">{t('feed.empty.title')}</h2>
              <p className="mt-2 text-sm text-white/70">{t('feed.empty.text')}</p>
            </div>
          </div>
        ) : null}

        {orderedFeed.map((item) => {
          const liked = likedOverrides[item.ai_news_id] ?? Boolean(item.liked);
          const saved = savedOverrides[item.ai_news_id] ?? Boolean(item.saved);
          const feedImages = getFeedImages(item);
          const displayTitle = normalizeFeedTitle(item.final_title);
          const imageCount = feedImages.length;
          const currentImageIndex = ((imageIndexByCard[item.user_feed_id] ?? 0) + imageCount) % imageCount;
          const currentImage = feedImages[currentImageIndex] ?? FALLBACK_IMAGE;

          return (
            <section
              key={item.user_feed_id}
              data-card-id={item.user_feed_id}
              ref={(node) => {
                sectionRefs.current[item.user_feed_id] = node;
              }}
              className="relative h-[100dvh] snap-start snap-always overflow-hidden"
            >
              <div className="absolute inset-0 bg-black">
                <div
                  className="absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center px-3 touch-pan-y"
                  onTouchStart={(event) => handleImageTouchStart(item.user_feed_id, event)}
                  onTouchEnd={(event) => handleImageTouchEnd(item.user_feed_id, imageCount, event)}
                >
                  <div className="relative w-full max-w-[980px]">
                    <ImageWithSkeleton src={currentImage} alt={displayTitle || t('feed.imageAlt')} />

                    {imageCount > 1 ? (
                      <>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            handleImageChange(item.user_feed_id, imageCount, -1);
                          }}
                          className="absolute left-3 top-1/2 z-20 -translate-y-1/2 rounded-full bg-black/55 px-3 py-2 text-xl leading-none text-white backdrop-blur hover:bg-black/70"
                          aria-label="Previous image"
                        >
                          {'‹'}
                        </button>

                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            handleImageChange(item.user_feed_id, imageCount, 1);
                          }}
                          className="absolute right-3 top-1/2 z-20 -translate-y-1/2 rounded-full bg-black/55 px-3 py-2 text-xl leading-none text-white backdrop-blur hover:bg-black/70"
                          aria-label="Next image"
                        >
                          {'›'}
                        </button>

                        <div className="absolute bottom-5 left-1/2 z-20 -translate-x-1/2 rounded-full bg-black/50 px-3 py-1 text-xs font-semibold text-white/90 backdrop-blur">
                          {currentImageIndex + 1}/{imageCount}
                        </div>
                      </>
                    ) : null}
                  </div>
                </div>
              </div>

              <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/85 via-black/30 to-black/35" />

              <div className="absolute inset-x-0 bottom-0 z-10 p-4 pb-24">
                <div className="mx-auto flex max-w-6xl items-end justify-between gap-4">
                  <div className="max-w-[78%] space-y-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-white/90">
                      <span className="rounded-full bg-white/20 px-2.5 py-1 font-semibold backdrop-blur">{item.category || t('feed.category.general')}</span>
                      <span className="rounded-full bg-black/35 px-2.5 py-1">{t('feed.badge.score', { score: formatScore(item.ai_score) })}</span>
                    </div>

                    <h2 className="text-xl font-bold leading-tight">{displayTitle || getUzbekHeadlineFallback(item.ai_news_id)}</h2>

                    <button
                      type="button"
                      onClick={() => setTextSheetItem(item)}
                      className="w-full rounded-xl border border-white/20 bg-black/30 p-3 text-left backdrop-blur hover:bg-black/40"
                    >
                      <p className="line-clamp-3 whitespace-pre-line text-sm leading-relaxed text-white/90">
                        {normalizeArticleText(item.final_text || t('feed.noText'))}
                      </p>
                      <p className="mt-1 text-xs text-white/65">{t('feed.description.tap')}</p>
                    </button>
                  </div>

                  <div className="mb-1 flex flex-col items-end gap-3">
                    <button
                      type="button"
                      onClick={() => handleLikeToggle(item, liked)}
                      disabled={interactionMutation.isPending}
                      className={`flex h-11 min-w-11 items-center justify-center rounded-full transition-transform duration-200 ${likePulseByCard[item.ai_news_id] ? 'scale-110' : 'scale-100'} ${liked ? 'bg-green-600' : 'bg-white/20'} backdrop-blur hover:bg-white/30 disabled:cursor-not-allowed disabled:opacity-70`}
                      title={liked ? t('common.unlike') : t('common.like')}
                    >
                      <Heart size={18} fill={liked ? 'currentColor' : 'none'} />
                    </button>

                    <button
                      type="button"
                      onClick={() => handleToggleSaved(item)}
                      className={`flex h-11 min-w-11 items-center justify-center rounded-full ${saved ? 'bg-blue-600' : 'bg-white/20'} backdrop-blur hover:bg-white/30`}
                      title={saved ? t('common.unsave') : t('common.save')}
                    >
                      <Bookmark size={18} fill={saved ? 'currentColor' : 'none'} />
                    </button>

                    <button
                      type="button"
                      onClick={() => handleOpenComments(item.ai_news_id)}
                      className="flex h-11 min-w-11 items-center justify-center rounded-full bg-white/20 backdrop-blur hover:bg-white/30"
                      title={t('common.comments')}
                    >
                      <MessageCircle size={18} />
                    </button>
                    <span className="text-xs text-white/80">{item.comment_count || 0}</span>
                  </div>
                </div>
              </div>
            </section>
          );
        })}
      </main>

      {textSheetItem ? (
        <div className="fixed inset-0 z-[95] flex items-end bg-black/55" onClick={() => setTextSheetItem(null)}>
          <div
            className="w-full max-h-[86vh] overflow-hidden rounded-t-3xl bg-surface-container-low shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-outline-variant/30 px-5 py-4">
              <h3 className="text-base font-bold text-on-surface">{t('feed.description.fullTitle')}</h3>
              <button
                type="button"
                onClick={() => setTextSheetItem(null)}
                className="rounded-md p-1 text-on-surface-variant hover:bg-surface-container"
              >
                <X size={18} />
              </button>
            </div>

            <div className="max-h-[calc(86vh-64px)] overflow-y-auto px-5 py-4 pb-[calc(6rem+env(safe-area-inset-bottom))]">
              <h4 className="mb-3 text-lg font-semibold text-on-surface">{normalizeFeedTitle(textSheetItem.final_title) || getUzbekHeadlineFallback(textSheetItem.ai_news_id)}</h4>
              <p className="whitespace-pre-line text-sm leading-relaxed text-on-surface-variant">
                {normalizeArticleText(textSheetItem.final_text || t('feed.noText'))}
              </p>
            </div>
          </div>
        </div>
      ) : null}

      {commentsOpenFor ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6">
          <div className="flex h-full max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-surface-container-low shadow-2xl">
            <div className="flex items-center justify-between border-b border-outline-variant/30 px-5 py-4">
              <h3 className="text-lg font-bold text-on-surface">{t('feed.comments.title')}</h3>
              <button type="button" onClick={() => setCommentsOpenFor(null)} className="rounded-md p-1 text-on-surface-variant hover:bg-surface-container">
                <X size={18} />
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {commentsLoadingFor === commentsOpenFor ? (
                <p className="text-sm text-on-surface-variant">{t('common.loading')}</p>
              ) : null}

              {commentsLoadingFor !== commentsOpenFor && activeComments.length === 0 ? (
                <p className="text-sm text-on-surface-variant">{t('feed.comments.empty')}</p>
              ) : null}

              {activeComments.length > 0 ? <div className="space-y-3">{renderCommentNodes(activeComments)}</div> : null}
            </div>

            <div className="border-t border-outline-variant/30 p-4">
              {replyTarget ? (
                <div className="mb-2 flex items-center justify-between rounded-md bg-surface-container px-3 py-2 text-xs text-on-surface-variant">
                  <span>{t('feed.comments.replyTo', { username: replyTarget.username })}</span>
                  <button type="button" onClick={() => setReplyTarget(null)} className="font-semibold text-on-surface-variant">
                    {t('common.cancel')}
                  </button>
                </div>
              ) : null}

              <div className="flex gap-2">
                <input
                  value={commentDraft}
                  onChange={(event) => setCommentDraft(event.target.value)}
                  placeholder={t('feed.comments.inputPlaceholder')}
                  className="flex-1 rounded-lg border border-outline-variant/40 bg-white px-3 py-2 text-sm outline-none focus:border-primary-container"
                />
                <button
                  type="button"
                  onClick={handleSubmitComment}
                  className="rounded-lg bg-primary-container px-4 py-2 text-sm font-semibold text-white"
                >
                  {t('common.send')}
                </button>
              </div>

              {commentError ? <p className="mt-2 text-xs text-error">{commentError}</p> : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
