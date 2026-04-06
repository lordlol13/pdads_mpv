import { useMemo, useState } from 'react';
import { Bookmark, Heart, LogOut, MessageCircle, RefreshCw, X } from 'lucide-react';

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

function isDirectVideoFile(url: string): boolean {
  return /\.(mp4|webm|ogg|m3u8)(\?|#|$)/i.test(url);
}

function formatScore(score: number | null): string {
  if (typeof score !== 'number') {
    return 'n/a';
  }
  return score.toFixed(2);
}

export function NewsFeed() {
  const { t } = useI18n();
  const { user, logout } = useAuth();
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
    <div className="min-h-screen bg-surface text-on-surface">
      <header className="sticky top-0 z-10 border-b border-outline-variant/20 bg-surface-container-low/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-on-surface-variant">PDADS MVP</p>
            <h1 className="text-lg font-bold">{t('feed.title')}</h1>
          </div>

          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-on-surface-variant sm:inline">{user?.username}</span>
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-lg border border-outline-variant/30 px-3 py-2 text-sm font-medium hover:bg-surface-container"
            >
              <span className="inline-flex items-center gap-1.5">
                <RefreshCw size={16} /> {t('common.refresh')}
              </span>
            </button>
            <button
              type="button"
              onClick={logout}
              className="rounded-lg border border-outline-variant/30 px-3 py-2 text-sm font-medium hover:bg-surface-container"
            >
              <span className="inline-flex items-center gap-1.5">
                <LogOut size={16} /> {t('common.logout')}
              </span>
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6">
        {isLoading ? (
          <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-8 text-center text-sm text-on-surface-variant">
            {t('feed.loading')}
          </div>
        ) : null}

        {isError ? (
          <div className="rounded-xl border border-error/30 bg-error-container p-4 text-sm text-on-error-container">
            <p>{t('feed.failed')}</p>
            <p className="mt-1 opacity-80">{String(error)}</p>
          </div>
        ) : null}

        {!isLoading && !isError && orderedFeed.length === 0 ? (
          <div className="rounded-xl border border-outline-variant/20 bg-surface-container-low p-8 text-center">
            <h2 className="text-lg font-semibold">{t('feed.empty.title')}</h2>
            <p className="mt-2 text-sm text-on-surface-variant">{t('feed.empty.text')}</p>
          </div>
        ) : null}

        <div className="grid gap-6">
          {orderedFeed.map((item) => {
            const liked = likedOverrides[item.ai_news_id] ?? Boolean(item.liked);
            const saved = savedOverrides[item.ai_news_id] ?? Boolean(item.saved);
            const primaryVideoUrl = getPrimaryVideoUrl(item);
            const youtubeEmbedUrl = primaryVideoUrl ? getYouTubeEmbedUrl(primaryVideoUrl) : null;

            return (
              <article
                key={item.user_feed_id}
                className="overflow-hidden rounded-2xl border border-outline-variant/20 bg-surface-container-low shadow-sm"
              >
                <div className="grid gap-0 md:grid-cols-[2fr,3fr]">
                  {youtubeEmbedUrl ? (
                    <iframe
                      src={youtubeEmbedUrl}
                      title={item.final_title || t('feed.videoAlt')}
                      className="h-56 w-full md:h-full"
                      loading="lazy"
                      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                      allowFullScreen
                    />
                  ) : primaryVideoUrl && isDirectVideoFile(primaryVideoUrl) ? (
                    <video
                      className="h-56 w-full object-cover md:h-full"
                      controls
                      preload="metadata"
                      src={primaryVideoUrl}
                    />
                  ) : primaryVideoUrl ? (
                    <div className="flex h-56 w-full flex-col items-center justify-center gap-3 bg-surface-container text-center md:h-full">
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
                    <img
                      src={getFeedImage(item)}
                      alt={item.final_title || t('feed.imageAlt')}
                      className="h-56 w-full object-cover md:h-full"
                    />
                  )}

                  <div className="space-y-4 p-5">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded-full bg-primary-container px-2.5 py-1 font-semibold text-white">
                        {item.category || t('feed.category.general')}
                      </span>
                      <span className="rounded-full bg-surface-container px-2.5 py-1 text-on-surface-variant">
                        {t('feed.badge.score', { score: formatScore(item.ai_score) })}
                      </span>
                      <span className="rounded-full bg-surface-container px-2.5 py-1 text-on-surface-variant">
                        {t('feed.badge.persona', { persona: item.target_persona || t('feed.persona.na') })}
                      </span>
                    </div>

                    <h2 className="text-xl font-bold leading-tight">{item.final_title || `AI News #${item.ai_news_id}`}</h2>

                    <p className="line-clamp-6 whitespace-pre-line text-sm leading-relaxed text-on-surface-variant">{item.final_text || t('feed.noText')}</p>

                    <div className="flex items-center justify-between pt-2">
                      <span className="text-xs text-on-surface-variant">{t('feed.badge.raw', { id: item.raw_news_id ?? t('feed.score.na') })}</span>

                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleOpenComments(item.ai_news_id)}
                          className="rounded-lg bg-surface-container px-3 py-2 text-sm font-semibold text-on-surface-variant"
                        >
                          <span className="inline-flex items-center gap-1.5">
                            <MessageCircle size={16} /> {t('common.comments')} ({item.comment_count || 0})
                          </span>
                        </button>

                        <button
                          type="button"
                          onClick={() => handleToggleSaved(item)}
                          className={`rounded-lg px-3 py-2 text-sm font-semibold ${saved ? 'bg-blue-600 text-white' : 'bg-surface-container text-on-surface-variant'}`}
                        >
                          <span className="inline-flex items-center gap-1.5">
                            <Bookmark size={16} fill={saved ? 'currentColor' : 'none'} />
                            {saved ? t('common.unsave') : t('common.save')}
                          </span>
                        </button>

                        <button
                          type="button"
                          onClick={() => handleLikeToggle(item, liked)}
                          disabled={interactionMutation.isPending}
                          className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
                            liked ? 'bg-green-600 text-white' : 'bg-primary-container text-white hover:opacity-90'
                          } disabled:cursor-not-allowed disabled:opacity-70`}
                        >
                          <span className="inline-flex items-center gap-2">
                            <Heart size={16} fill={liked ? 'currentColor' : 'none'} />
                            {liked ? t('common.unlike') : t('common.like')}
                          </span>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </main>

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
