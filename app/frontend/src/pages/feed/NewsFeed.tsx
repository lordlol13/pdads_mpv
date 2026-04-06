import { useEffect, useMemo, useRef, useState } from 'react';
import { Bookmark, Heart, MessageCircle, RefreshCw, X } from 'lucide-react';

import { newsService } from '../../api/services';
import { useAuth } from '../../context/AuthContext';
import { useI18n } from '../../context/I18nContext';
import { useNewsFeed, useReactToNews } from '../../hooks/useNews';
import { CommentItem, FeedItem } from '../../types';

const FALLBACK_IMAGE =
  'https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&q=80&w=1200';

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

function getFeedImage(item: FeedItem): string {
  if (Array.isArray(item.image_urls) && item.image_urls.length > 0) {
    return normalizeMediaUrl(item.image_urls[0]);
  }
  return FALLBACK_IMAGE;
}

function getPrimaryVideoUrl(item: FeedItem): string | null {
  if (!Array.isArray(item.video_urls) || item.video_urls.length === 0) {
    return null;
  }

  for (const rawUrl of item.video_urls) {
    const candidate = (rawUrl || '').trim();
    if (!candidate || !/^https?:\/\//i.test(candidate)) {
      continue;
    }

    const lower = candidate.toLowerCase();
    // Hide obvious legacy fallback/music links from older feed items.
    if (
      lower.includes('dqw4w9wx') ||
      lower.includes('music') ||
      lower.includes('song') ||
      lower.includes('lyrics') ||
      lower.includes('karaoke')
    ) {
      continue;
    }

    return candidate;
  }

  return null;
}

function getYouTubeEmbedUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();

    if (host.includes('youtu.be')) {
      const id = parsed.pathname.replace('/', '').trim();
      return id ? `https://www.youtube.com/embed/${id}` : null;
    }

    if (host.includes('youtube.com')) {
      const idFromQuery = parsed.searchParams.get('v')?.trim() || '';
      if (idFromQuery) {
        return `https://www.youtube.com/embed/${idFromQuery}`;
      }

      const shortMatch = parsed.pathname.match(/\/shorts\/([^/?]+)/i);
      if (shortMatch?.[1]) {
        return `https://www.youtube.com/embed/${shortMatch[1]}`;
      }

      const pathParts = parsed.pathname.split('/').filter(Boolean);
      const embedIdx = pathParts.findIndex((part) => part === 'embed');
      if (embedIdx >= 0 && pathParts[embedIdx + 1]) {
        return `https://www.youtube.com/embed/${pathParts[embedIdx + 1]}`;
      }
    }
  } catch {
    return null;
  }

  return null;
}

function withYouTubePlaybackMode(embedUrl: string, autoplay: boolean): string {
  try {
    const parsed = new URL(embedUrl);
    parsed.searchParams.set('autoplay', autoplay ? '1' : '0');
    parsed.searchParams.set('mute', '1');
    parsed.searchParams.set('playsinline', '1');
    parsed.searchParams.set('rel', '0');
    parsed.searchParams.set('modestbranding', '1');
    return parsed.toString();
  } catch {
    return embedUrl;
  }
}

function isDirectVideoFile(url: string): boolean {
  return /\.(mp4|webm|ogg|m3u8)(\?|#|$)/i.test(url);
}

function formatScore(score: number | null): string {
  if (typeof score !== 'number') {
    return 'n/a';
  }
  return score.toFixed(2);
}

function normalizeArticleText(value: string): string {
  return (value || '').replace(/\r/g, '').replace(/\n{3,}/g, '\n\n').trim();
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

  const feedContainerRef = useRef<HTMLElement | null>(null);
  const sectionRefs = useRef<Record<number, HTMLElement | null>>({});
  const videoRefs = useRef<Record<number, HTMLVideoElement | null>>({});
  const viewedAiNewsIdsRef = useRef<Set<number>>(new Set());

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

  useEffect(() => {
    for (const [cardIdRaw, video] of Object.entries(videoRefs.current)) {
      if (!video) {
        continue;
      }

      const cardId = Number(cardIdRaw);
      if (activeCardId && cardId === activeCardId) {
        const playAttempt = video.play();
        if (playAttempt && typeof playAttempt.catch === 'function') {
          playAttempt.catch(() => undefined);
        }
      } else {
        video.pause();
      }
    }
  }, [activeCardId, orderedFeed]);

  const handleLikeToggle = (item: FeedItem, currentlyLiked: boolean) => {
    if (!user) {
      return;
    }

    const nextLiked = !currentlyLiked;

    interactionMutation.mutate(
      {
        user_id: user.id,
        ai_news_id: item.ai_news_id,
        liked: nextLiked,
        viewed: true,
        watch_time: 12,
      },
      {
        onSuccess: () => {
          setLikedOverrides((prev) => ({ ...prev, [item.ai_news_id]: nextLiked }));
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
    <div className="relative h-screen overflow-hidden bg-black text-white">
      <header className="pointer-events-none absolute inset-x-0 top-0 z-20">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <div className="pointer-events-auto">
            <p className="text-xs uppercase tracking-wide text-white/70">PDADS MVP</p>
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
          const primaryVideoUrl = getPrimaryVideoUrl(item);
          const youtubeEmbedUrl = primaryVideoUrl ? getYouTubeEmbedUrl(primaryVideoUrl) : null;
          const isActiveCard = activeCardId === item.user_feed_id;
          const shouldRenderYoutubePlayer = Boolean(youtubeEmbedUrl && isActiveCard);

          return (
            <section
              key={item.user_feed_id}
              data-card-id={item.user_feed_id}
              ref={(node) => {
                sectionRefs.current[item.user_feed_id] = node;
              }}
              className="relative h-screen snap-start overflow-hidden"
            >
              <div className="absolute inset-0 bg-black">
                {youtubeEmbedUrl && shouldRenderYoutubePlayer ? (
                  <iframe
                    key={`${item.user_feed_id}-${isActiveCard ? 'active' : 'idle'}`}
                    src={withYouTubePlaybackMode(youtubeEmbedUrl, isActiveCard)}
                    title={item.final_title || t('feed.videoAlt')}
                    className="h-full w-full"
                    loading="lazy"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                  />
                ) : youtubeEmbedUrl ? (
                  <img src={getFeedImage(item)} alt={item.final_title || t('feed.imageAlt')} className="h-full w-full object-cover" />
                ) : primaryVideoUrl && isDirectVideoFile(primaryVideoUrl) ? (
                  <video
                    ref={(node) => {
                      videoRefs.current[item.user_feed_id] = node;
                    }}
                    className="h-full w-full object-cover"
                    controls={isActiveCard}
                    muted
                    playsInline
                    preload={isActiveCard ? 'auto' : 'metadata'}
                    autoPlay={isActiveCard}
                    src={primaryVideoUrl}
                  />
                ) : primaryVideoUrl ? (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-surface-container text-center">
                    <p className="max-w-xs text-sm text-on-surface-variant">{t('feed.videoAlt')}</p>
                    <a
                      href={primaryVideoUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-lg bg-primary-container px-4 py-2 text-sm font-semibold text-white"
                    >
                      Open Video
                    </a>
                  </div>
                ) : (
                  <img src={getFeedImage(item)} alt={item.final_title || t('feed.imageAlt')} className="h-full w-full object-cover" />
                )}
              </div>

              <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/30 to-black/35" />

              <div className="absolute inset-x-0 bottom-0 z-10 p-4 pb-24">
                <div className="mx-auto flex max-w-6xl items-end justify-between gap-4">
                  <div className="max-w-[78%] space-y-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-white/90">
                      <span className="rounded-full bg-white/20 px-2.5 py-1 font-semibold backdrop-blur">{item.category || t('feed.category.general')}</span>
                      <span className="rounded-full bg-black/35 px-2.5 py-1">{t('feed.badge.score', { score: formatScore(item.ai_score) })}</span>
                    </div>

                    <h2 className="text-xl font-bold leading-tight">{item.final_title || `AI News #${item.ai_news_id}`}</h2>

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
                      className={`flex h-11 min-w-11 items-center justify-center rounded-full ${liked ? 'bg-green-600' : 'bg-white/20'} backdrop-blur hover:bg-white/30 disabled:cursor-not-allowed disabled:opacity-70`}
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
        <div className="fixed inset-0 z-[60] flex items-end bg-black/55" onClick={() => setTextSheetItem(null)}>
          <div
            className="w-full max-h-[78vh] overflow-hidden rounded-t-3xl bg-surface-container-low shadow-2xl"
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

            <div className="max-h-[calc(78vh-64px)] overflow-y-auto px-5 py-4">
              <h4 className="mb-3 text-lg font-semibold text-on-surface">{textSheetItem.final_title || `AI News #${textSheetItem.ai_news_id}`}</h4>
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
