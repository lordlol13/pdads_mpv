import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Bookmark, ChevronLeft, ChevronRight, Heart, MessageCircle, Play, Send, Share2 } from 'lucide-react';
import { useDoubleTap } from 'use-double-tap';

import { newsService } from '../api/services';
import { useLanguage } from '../context/LanguageContext';
import { CommentItem, FeedItem } from '../types';

interface BackendFeedPostProps {
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
  const title = item.final_title?.trim() || item.target_persona?.trim() || item.category?.trim() || 'News item';
  const author = item.target_persona?.trim() || item.category?.trim() || 'news';
  const previewText = item.final_text?.trim() || '';
  const commentCount = item.comment_count + commentsList.length;

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

  const handleSave = async (event: React.MouseEvent<HTMLButtonElement>) => {
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
  const shareUrl = `${window.location.origin}/app/home?ai_news_id=${item.ai_news_id}`;

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
            className="w-full h-full object-contain bg-black"
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
                    className="absolute left-4 top-1/2 -translate-y-1/2 p-2 bg-black/20 backdrop-blur-md rounded-full text-white hover:bg-black/40 transition-all z-10"
                  >
                    <ChevronLeft className="w-6 h-6" />
                  </button>
                ) : null}
                {currentImageIndex < urls.length - 1 ? (
                  <button
                    onClick={(event) => navigateComments('next', event)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 p-2 bg-black/20 backdrop-blur-md rounded-full text-white hover:bg-black/40 transition-all z-10"
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
          <div className="absolute inset-0 flex items-center justify-center bg-black/20">
            <motion.div initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
              <Play className="w-20 h-20 text-white fill-white opacity-80" />
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
              <Heart className="w-32 h-32 text-red-500 fill-red-500 shadow-2xl" />
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      <div className="absolute right-2 sm:right-4 bottom-32 flex flex-col gap-4 sm:gap-6 z-40">
        <div className="flex flex-col items-center gap-1">
          <button
            onClick={(event) => {
              event.stopPropagation();
              void handleLike();
            }}
            className="p-2.5 sm:p-3 bg-black/40 backdrop-blur-xl rounded-full border border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Heart className={`w-6 h-6 sm:w-7 sm:h-7 ${isLiked ? 'text-red-500 fill-red-500' : 'text-white'}`} />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-white drop-shadow-md">{likesCount}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button
            onClick={(event) => {
              event.stopPropagation();
              setShowComments(true);
            }}
            className="p-2.5 sm:p-3 bg-black/40 backdrop-blur-xl rounded-full border border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <MessageCircle className="w-6 h-6 sm:w-7 sm:h-7 text-white" />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-white drop-shadow-md">{commentCount}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button
            onClick={handleSave}
            className="p-2.5 sm:p-3 bg-black/40 backdrop-blur-xl rounded-full border border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Bookmark className={`w-6 h-6 sm:w-7 sm:h-7 ${isSaved ? 'text-yellow-500 fill-yellow-500' : 'text-white'}`} />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-white drop-shadow-md">{t.save}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button
            onClick={(event) => {
              event.stopPropagation();
              setShowShareSheet(true);
            }}
            className="p-2.5 sm:p-3 bg-black/40 backdrop-blur-xl rounded-full border border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Share2 className="w-6 h-6 sm:w-7 sm:h-7 text-white" />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-white drop-shadow-md">{t.share}</span>
        </div>
      </div>

      <div className="absolute bottom-0 left-0 w-full p-6 bg-gradient-to-t from-black/80 via-black/40 to-transparent z-30">
        <div className="max-w-[80%] space-y-3">
          <h3 className="font-bold text-lg text-white">@{author}</h3>
          <p
            className="text-white/90 text-sm line-clamp-2 cursor-pointer hover:text-white transition-colors"
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
              className="absolute inset-0 bg-black/60 backdrop-blur-sm z-[60]"
            />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="absolute bottom-0 left-0 w-full bg-zinc-950 rounded-t-[32px] p-8 z-[70] border-t border-white/5"
            >
              <div className="w-12 h-1.5 bg-zinc-700 rounded-full mx-auto mb-8" />
              <div className="space-y-6">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-zinc-800 rounded-full border border-white/10" />
                  <div>
                    <h4 className="font-bold text-white">@{author}</h4>
                    <p className="text-xs text-zinc-500">{t.posted} {relativeLabel(item.created_at, t.now)}</p>
                  </div>
                </div>
                <div className="prose prose-invert max-w-none">
                  <p className="text-zinc-300 leading-relaxed text-lg whitespace-pre-wrap">
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
              className="absolute inset-0 bg-black/60 backdrop-blur-sm z-[80]"
            />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="absolute bottom-0 left-0 w-full h-[70vh] bg-zinc-950 rounded-t-[32px] flex flex-col z-[90] border-t border-white/5"
            >
              <div className="p-4 border-b border-white/5 flex flex-col items-center">
                <div className="w-12 h-1.5 bg-zinc-700 rounded-full mb-4" />
                <h3 className="font-bold text-white">{commentCount} {t.comments}</h3>
              </div>

              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {commentsLoading ? (
                  <p className="text-sm text-zinc-400">{t.loading}</p>
                ) : null}
                {commentsError ? <p className="text-sm text-red-400">{commentsError}</p> : null}
                {!commentsLoading && commentsList.length === 0 && !commentsError ? (
                  <p className="text-sm text-zinc-500">{t.noComments}</p>
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

              <div className="p-6 border-t border-white/5 bg-black/40 backdrop-blur-xl">
                <div className="flex items-center gap-3 bg-zinc-900 rounded-2xl px-4 py-2">
                  <input
                    type="text"
                    value={newComment}
                    onChange={(event) => setNewComment(event.target.value)}
                    placeholder={t.addComment}
                    className="flex-1 bg-transparent border-none outline-none text-sm text-white py-2"
                  />
                  <button
                    onClick={handleAddComment}
                    className={`p-2 rounded-xl transition-all ${newComment.trim() ? 'bg-white text-black scale-100' : 'bg-zinc-700 text-zinc-500 scale-90'}`}
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
              className="absolute inset-0 bg-black/60 backdrop-blur-sm z-[100]"
            />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="absolute bottom-0 left-0 w-full bg-zinc-950 rounded-t-[32px] p-8 z-[110] border-t border-white/5"
            >
              <div className="w-12 h-1.5 bg-zinc-700 rounded-full mx-auto mb-8" />
              <div className="space-y-6">
                <h3 className="text-xl font-bold text-white text-center">{t.share}</h3>
                <div className="bg-zinc-900 p-4 rounded-2xl border border-white/5 break-all">
                  <p className="text-zinc-400 text-sm mb-2 uppercase tracking-widest font-bold">Post Link</p>
                  <code className="text-white text-sm">{shareUrl}</code>
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
                    className="py-4 bg-zinc-800 text-white font-bold rounded-2xl hover:bg-zinc-700 transition-colors"
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
        <div className="w-10 h-10 bg-zinc-800 rounded-full flex-shrink-0" />
        <div className="flex-1 space-y-1">
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-sm font-bold text-white">@{comment.username}</h4>
            <button onClick={() => onToggleLike(comment.id)} className="flex flex-col items-center gap-0.5">
              <Heart className={`w-4 h-4 ${comment.liked_by_me ? 'text-red-500 fill-red-500' : 'text-zinc-500'}`} />
              <span className="text-[10px] text-zinc-500">{comment.like_count}</span>
            </button>
          </div>
          <p className="text-sm text-zinc-300">{comment.content}</p>
          <div className="flex items-center gap-4 text-xs font-bold text-zinc-500">
            <span>{relativeLabel(comment.created_at, t.now)}</span>
            <button className="hover:text-white transition-colors">{t.reply}</button>
          </div>
        </div>
      </div>

      {comment.replies.map((reply) => (
        <CommentThread key={reply.id} comment={reply} onToggleLike={onToggleLike} depth={depth + 1} />
      ))}
    </div>
  );
}
