import { useEffect, useMemo, useRef, useState, type MouseEvent, type WheelEvent } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Bookmark, ChevronLeft, ChevronRight, Heart, MessageCircle, Play, Send, Share2, ExternalLink } from 'lucide-react';
import { useDoubleTap } from 'use-double-tap';

import { newsService } from '../api/services';
import { useLanguage } from '../context/LanguageContext';
import { CommentItem, FeedItem } from '../types';

interface BackendFeedPostProps {
  key?: string | number;
  item: FeedItem;
  isActive: boolean;
  currentUserId: number;
  onToggleSaved: (aiNewsId: number) => Promise<boolean>;
  onReactToNews: (aiNewsId: number, liked: boolean) => Promise<void>;
  onViewed: (aiNewsId: number) => Promise<void>;
}

function mediaUrls(item: FeedItem): string[] {
  if (Array.isArray(item.video_urls) && item.video_urls.length > 0) {
    return item.video_urls;
  }
  if (Array.isArray(item.image_urls) && item.image_urls.length > 0) {
    return item.image_urls;
  }
  return [];
}

function formatPersonaToken(raw: string): string {
  const value = raw.trim();
  if (!value) {
    return '';
  }

  if (/^[a-z]{2,3}$/i.test(value)) {
    return value.toUpperCase();
  }

  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .split(' ')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function parseNewsToc(
  finalTitle?: string | null,
  finalText?: string | null,
  category?: string | null,
): { headline: string; toc: string[] } {
  const normalizedTitle = (finalTitle || '').replace(/\s+/g, ' ').trim();
  const normalizedText = (finalText || '').replace(/\s+/g, ' ').trim();
  const fallbackHeadline = formatPersonaToken((category || 'News').trim()) || 'News';

  const headline = normalizedTitle || fallbackHeadline;
  const source = `${normalizedTitle}. ${normalizedText}`.trim();
  if (!source) {
    return { headline, toc: [] };
  }

  const stopwords = new Set([
    'the', 'and', 'for', 'with', 'that', 'this', 'from', 'into', 'after', 'before',
    'about', 'were', 'was', 'have', 'has', 'had', 'will', 'news', 'update',
  ]);

  const candidates = source
    .split(/[.,;:!?()\[\]{}"'\n\r]+/g)
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk.length >= 4 && chunk.length <= 48);

  const deduped: string[] = [];
  const seen = new Set<string>();

  for (const chunk of candidates) {
    const words = chunk
      .split(/\s+/g)
      .map((word) => word.replace(/[^\p{L}\p{N}\-]/gu, '').trim())
      .filter(Boolean);

    if (words.length === 0 || words.length > 7) {
      continue;
    }

    const meaningful = words.filter((word) => !stopwords.has(word.toLowerCase()));
    if (meaningful.length < 2) {
      continue;
    }

    const topic = meaningful.map(formatPersonaToken).join(' ').trim();
    const key = topic.toLowerCase();
    if (!topic || seen.has(key)) {
      continue;
    }

    seen.add(key);
    deduped.push(topic);
    if (deduped.length >= 4) {
      break;
    }
  }

  return { headline, toc: deduped };
}

function stripToPreview(text: string, maxLength = 180): string {
  const value = text.trim();
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength).trimEnd()}...`;
}

function relativeLabel(createdAt: string | null | undefined, fallback: string): string {
  if (!createdAt) {
    return fallback;
  }
  const timestamp = new Date(createdAt);
  if (Number.isNaN(timestamp.getTime())) {
    return fallback;
  }

  const diffMinutes = Math.max(0, Math.floor((Date.now() - timestamp.getTime()) / 60000));
  if (diffMinutes < 1) {
    return fallback;
  }
  if (diffMinutes < 60) {
    return `${diffMinutes}m`;
  }
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}h`;
  }
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d`;
}

function mapCommentsById(comments: CommentItem[], updater: (comment: CommentItem) => CommentItem): CommentItem[] {
  return comments.map((comment) => {
    const updated = updater(comment);
    if (updated.id === comment.id && updated.replies.length > 0) {
      return { ...updated, replies: mapCommentsById(updated.replies, updater) };
    }
    return updated;
  });
}

function findAndUpdateComment(comments: CommentItem[], commentId: number, updater: (comment: CommentItem) => CommentItem): CommentItem[] {
  return comments.map((comment) => {
    if (comment.id === commentId) {
      return updater(comment);
    }
    if (comment.replies.length === 0) {
      return comment;
    }
    return {
      ...comment,
      replies: findAndUpdateComment(comment.replies, commentId, updater),
    };
  });
}

export function BackendFeedPost({
  item,
  isActive,
  currentUserId,
  onToggleSaved,
  onReactToNews,
  onViewed,
}: BackendFeedPostProps) {
  const { t } = useLanguage();
  const [isLiked, setIsLiked] = useState(Boolean(item.liked));
  const [isSaved, setIsSaved] = useState(Boolean(item.saved));
  const [likesCount, setLikesCount] = useState(Math.max(0, Number(item.like_count || 0)));
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [showHeartAnimation, setShowHeartAnimation] = useState(false);
  const [showDescription, setShowDescription] = useState(false);
  const [descHeight, setDescHeight] = useState<number>(60); // viewport height in vh for modal
  const [showComments, setShowComments] = useState(false);
  const [showShareSheet, setShowShareSheet] = useState(false);
  const [newComment, setNewComment] = useState('');
  const [commentsList, setCommentsList] = useState<CommentItem[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [commentsError, setCommentsError] = useState('');
  const [actionError, setActionError] = useState('');
  const viewedRef = useRef(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const urls = useMemo(() => mediaUrls(item), [item]);
  const hasVideo = Array.isArray(item.video_urls) && item.video_urls.length > 0;
  const hasImages = Array.isArray(item.image_urls) && item.image_urls.length > 0;
  const personaMeta = useMemo(
    () => parseNewsToc(item.final_title, item.final_text, item.category),
    [item.final_title, item.final_text, item.category],
  );
  const title = item.final_title?.trim() || personaMeta.headline || item.category?.trim() || 'News item';
  const author = personaMeta.headline || item.category?.trim() || 'News';
  const previewText = item.final_text?.trim() || '';
  const commentCount = item.comment_count + commentsList.length;

  const [isWide, setIsWide] = useState<boolean>(false);
  const [showAllTags, setShowAllTags] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const m = window.matchMedia('(min-width: 768px)');
    const handler = (e: MediaQueryListEvent) => setIsWide(e.matches);
    setIsWide(m.matches);
    try {
      m.addEventListener('change', handler);
    } catch {
      // fallback for older browsers
      // @ts-ignore
      m.addListener(handler);
    }
    return () => {
      try {
        m.removeEventListener('change', handler);
      } catch {
        // @ts-ignore
        m.removeListener(handler);
      }
    };
  }, []);
  useEffect(() => {
    setIsLiked(Boolean(item.liked));
    setIsSaved(Boolean(item.saved));
    setLikesCount(Math.max(0, Number(item.like_count || 0)));
  }, [item]);

  useEffect(() => {
    if (isActive && !viewedRef.current) {
      viewedRef.current = true;
      void onViewed(item.ai_news_id);
    }
  }, [isActive, item.ai_news_id, onViewed]);

  useEffect(() => {
    if (!videoRef.current || !hasVideo) {
      return;
    }

    if (isActive && isPlaying) {
      void videoRef.current.play().catch(() => undefined);
    } else {
      videoRef.current.pause();
    }
  }, [hasVideo, isActive, isPlaying, item.ai_news_id]);

  useEffect(() => {
    if (!showComments) {
      return;
    }

    let cancelled = false;

    const loadComments = async () => {
      setCommentsLoading(true);
      setCommentsError('');
      try {
        const items = await newsService.getComments(item.ai_news_id);
        if (!cancelled) {
          setCommentsList(items);
        }
      } catch (error) {
        if (!cancelled) {
          setCommentsError(error instanceof Error ? error.message : 'Unable to load comments');
        }
      } finally {
        if (!cancelled) {
          setCommentsLoading(false);
        }
      }
    };

    if (commentsList.length === 0) {
      void loadComments();
    } else {
      setCommentsLoading(false);
    }

    return () => {
      cancelled = true;
    };
  }, [commentsList.length, item.ai_news_id, showComments]);

  const handleLike = async () => {
    const nextLiked = !isLiked;
    setIsLiked(nextLiked);
    setLikesCount((previous) => Math.max(0, previous + (nextLiked ? 1 : -1)));
    setActionError('');

    try {
      await onReactToNews(item.ai_news_id, nextLiked);
    } catch (error) {
      setIsLiked(!nextLiked);
      setLikesCount((previous) => previous + (nextLiked ? -1 : 1));
      setActionError(error instanceof Error ? error.message : 'Unable to update reaction');
    }
  };

  const handleDoubleTap = useDoubleTap(() => {
    if (!isLiked) {
      void handleLike();
    }
    setShowHeartAnimation(true);
    window.setTimeout(() => setShowHeartAnimation(false), 900);
  });

  const handleSave = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const nextSaved = !isSaved;
    setIsSaved(nextSaved);
    setActionError('');

    try {
      const saved = await onToggleSaved(item.ai_news_id);
      setIsSaved(saved);
    } catch (error) {
      setIsSaved(!nextSaved);
      setActionError(error instanceof Error ? error.message : 'Unable to update saved state');
    }
  };

  const handleVideoToggle = () => {
    if (hasVideo) {
      setIsPlaying((previous) => !previous);
    }
  };

  const handleDescWheel = (e: WheelEvent) => {
    // Adjust modal height with mouse wheel when hovering the handle
    e.stopPropagation();
    e.preventDefault();
    const delta = e.deltaY;
    const step = e.shiftKey ? 10 : 5; // larger step when holding Shift
    setDescHeight((prev) => {
      const next = prev - (delta > 0 ? step : -step);
      return Math.max(30, Math.min(95, Math.round(next)));
    });
  };

  const handleAddComment = async () => {
    const content = newComment.trim();
    if (!content) {
      return;
    }

    setCommentsLoading(true);
    setCommentsError('');
    try {
      const created = await newsService.createComment({ ai_news_id: item.ai_news_id, content });
      setCommentsList((previous) => [created, ...previous]);
      setNewComment('');
    } catch (error) {
      setCommentsError(error instanceof Error ? error.message : 'Unable to add comment');
    } finally {
      setCommentsLoading(false);
    }
  };

  const handleToggleCommentLike = async (commentId: number) => {
    try {
      const result = await newsService.toggleCommentLike(commentId);
      setCommentsList((previous) =>
        findAndUpdateComment(previous, commentId, (comment) => ({
          ...comment,
          like_count: result.like_count,
          liked_by_me: result.liked,
        })),
      );
    } catch (error) {
      setCommentsError(error instanceof Error ? error.message : 'Unable to update comment');
    }
  };

  const navigateComments = (direction: 'next' | 'prev', event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (!urls.length) {
      return;
    }
    setCurrentImageIndex((previous) => {
      if (direction === 'next') {
        return Math.min(previous + 1, urls.length - 1);
      }
      return Math.max(previous - 1, 0);
    });
  };

  const topMediaUrl = urls[currentImageIndex] || urls[0] || '';
  const shareUrl = `${window.location.origin}/?ai_news_id=${item.ai_news_id}`;

  return (
    <div className="relative w-full h-full bg-transparent flex items-center justify-center overflow-hidden snap-start">
      <div
        className="relative w-full h-full flex items-center justify-center cursor-pointer"
        {...handleDoubleTap}
        onClick={handleVideoToggle}
      >
        {hasVideo ? (
          <video
            ref={videoRef}
            src={topMediaUrl}
            className="w-full h-full object-contain bg-[var(--card)] dark:bg-black"
            loop
            playsInline
            muted={false}
          />
        ) : (
          <div className="relative w-full h-full flex items-center justify-center overflow-hidden">
            <motion.div
              className="flex w-full h-full cursor-grab active:cursor-grabbing"
              drag="x"
              dragConstraints={{ left: 0, right: 0 }}
              onDragEnd={(_, info) => {
                const threshold = 50;
                if (info.offset.x < -threshold && currentImageIndex < urls.length - 1) {
                  setCurrentImageIndex((previous) => previous + 1);
                } else if (info.offset.x > threshold && currentImageIndex > 0) {
                  setCurrentImageIndex((previous) => previous - 1);
                }
              }}
            >
              <AnimatePresence mode="wait">
                <motion.img
                  key={currentImageIndex}
                  src={topMediaUrl}
                  initial={{ opacity: 0, x: 100 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -100 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                  className="w-full h-full object-contain flex-shrink-0 pointer-events-none"
                  referrerPolicy="no-referrer"
                  alt={title}
                />
              </AnimatePresence>
            </motion.div>

            {urls.length > 1 ? (
              <>
                  {currentImageIndex > 0 ? (
                  <button
                    onClick={(event) => navigateComments('prev', event)}
                    className="absolute left-4 top-1/2 -translate-y-1/2 p-2 bg-white/10 dark:bg-black/20 backdrop-blur-md rounded-full text-[var(--popover-foreground)] dark:text-white hover:bg-white/20 dark:hover:bg-black/40 transition-all z-10"
                  >
                    <ChevronLeft className="w-6 h-6" />
                  </button>
                ) : null}
                {currentImageIndex < urls.length - 1 ? (
                  <button
                    onClick={(event) => navigateComments('next', event)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 p-2 bg-white/10 dark:bg-black/20 backdrop-blur-md rounded-full text-[var(--popover-foreground)] dark:text-white hover:bg-white/20 dark:hover:bg-black/40 transition-all z-10"
                  >
                    <ChevronRight className="w-6 h-6" />
                  </button>
                ) : null}
                <div className="absolute bottom-24 left-1/2 -translate-x-1/2 flex gap-1.5 z-10">
                  {urls.map((_, index) => (
                    <div
                      key={index}
                      className={`w-1.5 h-1.5 rounded-full transition-all duration-300 ${index === currentImageIndex ? 'bg-white w-4' : 'bg-white/40'}`}
                    />
                  ))}
                </div>
              </>
            ) : null}
          </div>
        )}

        {hasVideo && !isPlaying ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white/10 dark:bg-black/20">
            <motion.div initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
              <Play className="w-16 h-16 md:w-20 md:h-20 text-[var(--popover-foreground)] dark:text-white opacity-80" />
            </motion.div>
          </div>
        ) : null}

        <AnimatePresence>
          {showHeartAnimation ? (
            <motion.div
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: [0, 1.2, 1], opacity: [0, 1, 0] }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 flex items-center justify-center pointer-events-none z-50"
            >
              <Heart className="w-20 h-20 md:w-32 md:h-32 text-red-500 fill-red-500 shadow-2xl" />
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

        <div
          className={
            `absolute bottom-20 md:bottom-32 flex flex-col gap-4 sm:gap-6 z-40 ` +
            (isWide && (showDescription || showComments) ? 'right-[33.333%]' : 'right-2 sm:right-4')
          }
        >
        <div className="flex flex-col items-center gap-1">
          <button
            onClick={(event) => {
              event.stopPropagation();
              void handleLike();
            }}
            className="p-2.5 sm:p-3 bg-white/10 dark:bg-black/40 backdrop-blur-xl rounded-full border border-border dark:border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Heart className={`w-6 h-6 sm:w-7 sm:h-7 ${isLiked ? 'text-red-500 fill-red-500' : 'text-[var(--popover-foreground)] dark:text-white'}`} />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-[var(--popover-foreground)] dark:text-white drop-shadow-md">{likesCount}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button
            onClick={(event) => {
              event.stopPropagation();
              setShowComments(true);
            }}
            className="p-2.5 sm:p-3 bg-white/10 dark:bg-black/40 backdrop-blur-xl rounded-full border border-border dark:border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <MessageCircle className="w-6 h-6 sm:w-7 sm:h-7 text-[var(--popover-foreground)] dark:text-white" />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-[var(--popover-foreground)] dark:text-white drop-shadow-md">{commentCount}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button
            onClick={handleSave}
            className="p-2.5 sm:p-3 bg-white/10 dark:bg-black/40 backdrop-blur-xl rounded-full border border-border dark:border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Bookmark className={`w-6 h-6 sm:w-7 sm:h-7 ${isSaved ? 'text-yellow-500 fill-yellow-500' : 'text-[var(--popover-foreground)] dark:text-white'}`} />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-[var(--popover-foreground)] dark:text-white drop-shadow-md">{t.save}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button
            onClick={(event) => {
              event.stopPropagation();
              setShowShareSheet(true);
            }}
            className="p-2.5 sm:p-3 bg-white/10 dark:bg-black/40 backdrop-blur-xl rounded-full border border-border dark:border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Share2 className="w-6 h-6 sm:w-7 sm:h-7 text-[var(--popover-foreground)] dark:text-white" />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-[var(--popover-foreground)] dark:text-white drop-shadow-md">{t.share}</span>
        </div>
        <div className="flex flex-col items-center gap-1">
          <button
            onClick={(event) => {
              event.stopPropagation();
              try {
                const url = item.source_url;
                if (typeof window !== 'undefined' && url && String(url).startsWith('http')) {
                  window.open(String(url), '_blank', 'noopener');
                }
              } catch (e) {
                // noop
              }
            }}
            className="p-2.5 sm:p-3 bg-white/10 dark:bg-black/40 backdrop-blur-xl rounded-full border border-border dark:border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <ExternalLink className="w-6 h-6 sm:w-7 sm:h-7 text-[var(--popover-foreground)] dark:text-white" />
          </button>
        </div>
      </div>

      <div className="absolute bottom-0 left-0 w-full p-4 md:p-6 dark:bg-gradient-to-t dark:from-black/80 dark:via-black/40 dark:to-transparent bg-transparent z-30">
        <div className="max-w-[80%] space-y-3">
          <h3 className="font-bold text-lg text-[var(--popover-foreground)] dark:text-white">{author}</h3>
          {personaMeta.toc.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {((showAllTags ? personaMeta.toc : personaMeta.toc.slice(0, isWide ? 3 : 2))).map((topic) => (
                <span
                  key={topic}
                  className="rounded-full border border-border dark:border-white/25 dark:bg-black/35 bg-[var(--popover)] px-2.5 py-1 text-[10px] sm:text-[10px] font-semibold uppercase tracking-wide text-[var(--popover-foreground)] dark:text-white/90"
                >
                  {topic}
                </span>
              ))}
              {!showAllTags && personaMeta.toc.length > (isWide ? 3 : 2) ? (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowAllTags(true);
                  }}
                  className="rounded-full border border-border dark:border-white/25 dark:bg-black/35 bg-[var(--popover)] px-2.5 py-1 text-[10px] sm:text-[10px] font-semibold uppercase tracking-wide text-[var(--popover-foreground)] dark:text-white/90"
                >
                  +{personaMeta.toc.length - (isWide ? 3 : 2)}
                </button>
              ) : null}
            </div>
          ) : null}
          <p
            className={`text-[var(--popover-foreground)] dark:text-white/90 ${isWide ? 'text-sm' : 'text-xs'} ${isWide ? 'line-clamp-2' : 'line-clamp-1'} cursor-pointer hover:text-white transition-colors`}
            onClick={(event) => {
              event.stopPropagation();
              setShowDescription(true);
            }}
          >
            {stripToPreview(title)}
          </p>
        </div>
      </div>

      <AnimatePresence>
        {showDescription ? (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowDescription(false)}
              className="absolute inset-0 bg-white/30 dark:bg-black/60 backdrop-blur-sm z-[60]"
            />
            <motion.div
              initial={isWide ? { x: '100%' } : { y: '100%' }}
              animate={isWide ? { x: 0 } : { y: 0 }}
              exit={isWide ? { x: '100%' } : { y: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              style={isWide ? undefined : { height: `${descHeight}vh` }}
              className={
                `absolute z-[70] flex flex-col border-t border-border dark:border-white/5 p-4 md:p-8 ` +
                (isWide
                  ? 'top-0 right-0 h-full w-full md:w-1/3 bg-[var(--popover)]'
                  : 'bottom-0 left-0 w-full bg-[var(--popover)] rounded-t-[24px] md:rounded-t-[32px]')
              }
            >
              <div className="flex items-center justify-center gap-2 mb-4">
                <div
                  className="w-12 h-1.5 bg-[var(--muted)] dark:bg-zinc-700 rounded-full"
                  onWheel={handleDescWheel}
                  title="Прокрутите колесом для изменения высоты модалки"
                />
                <span className="text-xs text-[var(--muted-foreground)]">{descHeight}vh</span>
              </div>

                <div className="flex-1 overflow-y-auto space-y-6 text-[var(--popover-foreground)] dark:text-white/90">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-[var(--card)] dark:bg-zinc-800 rounded-full border border-border dark:border-white/10" />
                  <div>
                    <h4 className="font-bold text-[var(--popover-foreground)] dark:text-white">{author}</h4>
                    <p className="text-xs text-[var(--muted-foreground)]">{t.posted} {relativeLabel(item.created_at, t.now)}</p>
                  </div>
                </div>
                {personaMeta.toc.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {personaMeta.toc.map((topic) => (
                      <span
                        key={`modal-${topic}`}
                        className="rounded-full border border-border dark:border-white/15 bg-[var(--card)] dark:bg-zinc-900 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--popover-foreground)] dark:text-zinc-200"
                      >
                        {topic}
                      </span>
                    ))}
                  </div>
                ) : null}
                <div className="prose prose-invert max-w-none">
                  <p className="text-[var(--muted-foreground)] leading-relaxed text-base md:text-lg whitespace-pre-wrap">
                    {previewText || t.noComments}
                  </p>
                </div>
                <button
                  onClick={() => setShowDescription(false)}
                  className="w-full py-4 bg-white text-black font-bold rounded-2xl hover:bg-zinc-200 transition-colors"
                >
                  {t.close}
                </button>
              </div>
            </motion.div>
          </>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {showComments ? (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowComments(false)}
              className="absolute inset-0 bg-white/30 dark:bg-black/60 backdrop-blur-sm z-[80]"
            />
            <motion.div
              initial={isWide ? { x: '100%' } : { y: '100%' }}
              animate={isWide ? { x: 0 } : { y: 0 }}
              exit={isWide ? { x: '100%' } : { y: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className={
                `absolute flex flex-col z-[90] border-t border-border dark:border-white/5 ` +
                (isWide
                  ? 'top-0 right-0 h-full w-full md:w-1/3 bg-[var(--popover)]'
                  : 'bottom-0 left-0 w-full h-[60vh] md:h-[70vh] bg-[var(--popover)] rounded-t-[24px] md:rounded-t-[32px]')
              }
            >
              <div className="p-4 border-b border-border dark:border-white/5 flex flex-col items-center">
                <div className="w-12 h-1.5 bg-[var(--muted)] dark:bg-zinc-700 rounded-full mb-4" />
                <h3 className="font-bold text-[var(--popover-foreground)] dark:text-white">{commentCount} {t.comments}</h3>
              </div>

              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {commentsLoading ? (
                  <p className="text-sm text-[var(--muted-foreground)]">{t.loading}</p>
                ) : null}
                {commentsError ? <p className="text-sm text-red-400">{commentsError}</p> : null}
                {!commentsLoading && commentsList.length === 0 && !commentsError ? (
                  <p className="text-sm text-[var(--muted-foreground)]">{t.noComments}</p>
                ) : null}
                {commentsList.map((comment) => (
                  <CommentThread
                    key={comment.id}
                    comment={comment}
                    onToggleLike={handleToggleCommentLike}
                    depth={0}
                  />
                ))}
              </div>

              <div className="p-4 md:p-6 border-t border-border dark:border-white/5 bg-[var(--popover)] backdrop-blur-xl">
                <div className="flex items-center gap-3 bg-[var(--card)] rounded-2xl px-4 py-2">
                  <input
                    type="text"
                    value={newComment}
                    onChange={(event) => setNewComment(event.target.value)}
                    placeholder={t.addComment}
                    className="flex-1 bg-transparent border-none outline-none text-sm text-[var(--popover-foreground)] py-2"
                  />
                  <button
                    onClick={handleAddComment}
                    className={`p-2 rounded-xl transition-all ${newComment.trim() ? 'bg-white text-black scale-100' : 'bg-white/10 dark:bg-zinc-700 text-[var(--muted-foreground)] dark:text-zinc-500 scale-90'}`}
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </motion.div>
          </>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {showShareSheet ? (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowShareSheet(false)}
              className="absolute inset-0 bg-white/30 dark:bg-black/60 backdrop-blur-sm z-[100]"
            />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="absolute bottom-0 left-0 w-full bg-[var(--popover)] dark:bg-zinc-950 rounded-t-[24px] md:rounded-t-[32px] p-4 md:p-8 z-[110] border-t border-border dark:border-white/5"
            >
              <div className="w-12 h-1.5 bg-[var(--muted)] dark:bg-zinc-700 rounded-full mx-auto mb-8" />
              <div className="space-y-6">
                <h3 className="text-xl font-bold text-white text-center">{t.share}</h3>
                <div className="bg-[var(--card)] dark:bg-zinc-900 p-4 rounded-2xl border border-border dark:border-white/5 break-all">
                  <p className="text-[var(--muted-foreground)] dark:text-zinc-400 text-sm mb-2 uppercase tracking-widest font-bold">Post Link</p>
                  <code className="text-[var(--popover-foreground)] dark:text-white text-sm">{shareUrl}</code>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <button
                    onClick={async () => {
                      await navigator.clipboard.writeText(shareUrl);
                      setShowShareSheet(false);
                    }}
                    className="py-4 bg-white text-black font-bold rounded-2xl hover:bg-zinc-200 transition-colors"
                  >
                    {t.copyLink}
                  </button>
                  <button
                    onClick={() => setShowShareSheet(false)}
                    className="py-4 bg-[var(--card)] dark:bg-zinc-800 text-[var(--popover-foreground)] dark:text-white font-bold rounded-2xl hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                  >
                    {t.close}
                  </button>
                </div>
              </div>
            </motion.div>
          </>
        ) : null}
      </AnimatePresence>

      {actionError ? (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-[120] rounded-full border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-200 backdrop-blur">
          {actionError}
        </div>
      ) : null}
    </div>
  );
}

interface CommentThreadProps {
  key?: string | number;
  comment: CommentItem;
  onToggleLike: (commentId: number) => void;
  depth?: number;
}

function CommentThread({ comment, onToggleLike, depth = 0 }: CommentThreadProps) {
  const { t } = useLanguage();
  const isReply = depth > 0;
  return (
    <div className={`space-y-4 ${isReply ? 'ml-12' : ''}`}>
      <div className="flex gap-3">
        <div className="w-10 h-10 bg-[var(--card)] dark:bg-zinc-800 rounded-full flex-shrink-0" />
        <div className="flex-1 space-y-1">
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-sm font-bold text-[var(--popover-foreground)] dark:text-white">@{comment.username}</h4>
            <button onClick={() => onToggleLike(comment.id)} className="flex flex-col items-center gap-0.5">
              <Heart className={`w-4 h-4 ${comment.liked_by_me ? 'text-red-500 fill-red-500' : 'text-[var(--muted-foreground)]'}`} />
              <span className="text-[10px] text-[var(--muted-foreground)]">{comment.like_count}</span>
            </button>
          </div>
          <p className="text-sm text-[var(--muted-foreground)]">{comment.content}</p>
          <div className="flex items-center gap-4 text-xs font-bold text-[var(--muted-foreground)]">
            <span>{relativeLabel(comment.created_at, t.now)}</span>
            <button className="hover:text-[var(--popover-foreground)] dark:hover:text-white transition-colors">{t.reply}</button>
          </div>
        </div>
      </div>

      {comment.replies.map((reply) => (
        <CommentThread key={reply.id} comment={reply} onToggleLike={onToggleLike} depth={depth + 1} />
      ))}
    </div>
  );
}




