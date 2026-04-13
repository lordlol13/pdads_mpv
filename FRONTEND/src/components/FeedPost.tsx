import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Heart, MessageCircle, Bookmark, Share2, Play, Pause, ChevronLeft, ChevronRight, Send } from "lucide-react";
import { useDoubleTap } from "use-double-tap";
import { useLanguage } from "../context/LanguageContext";

interface Comment {
  id: string;
  author: string;
  text: string;
  likes: number;
  isLiked: boolean;
  replies: Comment[];
  timestamp: string;
}

interface MediaItem {
  id: string;
  type: "image" | "video";
  urls: string[];
  description: string;
  fullDescription: string;
  author: string;
  likes: number;
  comments: number;
  isLiked: boolean;
  isSaved: boolean;
}

interface FeedPostProps {
  item: MediaItem;
  isActive: boolean;
  onToggleSave?: (id: string) => void;
  key?: string;
}

export function FeedPost({ item, isActive, onToggleSave }: FeedPostProps) {
  const { t } = useLanguage();
  const [isLiked, setIsLiked] = useState(item.isLiked);
  const [isSaved, setIsSaved] = useState(item.isSaved);
  const [likesCount, setLikesCount] = useState(item.likes);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [showHeartAnimation, setShowHeartAnimation] = useState(false);
  const [showDescription, setShowDescription] = useState(false);
  const [showComments, setShowComments] = useState(false);
  const [showShareSheet, setShowShareSheet] = useState(false);
  const [newComment, setNewComment] = useState("");
  const [commentsList, setCommentsList] = useState<Comment[]>([
    {
      id: "c1",
      author: "alex_j",
      text: "This is amazing! 🔥",
      likes: 24,
      isLiked: false,
      timestamp: "2h",
      replies: []
    },
    {
      id: "c2",
      author: "sarah_k",
      text: "Love the visuals here.",
      likes: 12,
      isLiked: true,
      timestamp: "1h",
      replies: [
        {
          id: "r1",
          author: "nature_vibes",
          text: "Thank you Sarah!",
          likes: 5,
          isLiked: false,
          timestamp: "30m",
          replies: []
        }
      ]
    }
  ]);

  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (isActive && item.type === "video" && videoRef.current) {
      if (isPlaying) videoRef.current.play().catch(() => {});
      else videoRef.current.pause();
    } else if (!isActive && videoRef.current) {
      videoRef.current.pause();
    }
  }, [isActive, isPlaying, item.type]);

  const handleLike = () => {
    if (!isLiked) {
      setLikesCount(prev => prev + 1);
      setIsLiked(true);
    } else {
      setLikesCount(prev => prev - 1);
      setIsLiked(false);
    }
  };

  const doubleTap = useDoubleTap(() => {
    if (!isLiked) {
      setLikesCount(prev => prev + 1);
      setIsLiked(true);
    }
    setShowHeartAnimation(true);
    setTimeout(() => setShowHeartAnimation(false), 1000);
  });

  const handleVideoToggle = () => {
    if (item.type === "video") {
      setIsPlaying(!isPlaying);
    }
  };

  const handleSave = (e: any) => {
    e.stopPropagation();
    setIsSaved(!isSaved);
    onToggleSave?.(item.id);
  };

  const nextImage = (e: any) => {
    e.stopPropagation();
    if (currentImageIndex < item.urls.length - 1) {
      setCurrentImageIndex(prev => prev + 1);
    }
  };

  const prevImage = (e: any) => {
    e.stopPropagation();
    if (currentImageIndex > 0) {
      setCurrentImageIndex(prev => prev - 1);
    }
  };

  const handleAddComment = () => {
    if (!newComment.trim()) return;
    const comment: Comment = {
      id: Date.now().toString(),
      author: "you",
      text: newComment,
      likes: 0,
      isLiked: false,
      timestamp: t.now,
      replies: []
    };
    setCommentsList([comment, ...commentsList]);
    setNewComment("");
  };

  const toggleCommentLike = (id: string) => {
    setCommentsList(prev => prev.map(c => {
      if (c.id === id) return { ...c, isLiked: !c.isLiked, likes: c.isLiked ? c.likes - 1 : c.likes + 1 };
      return c;
    }));
  };

  return (
    <div className="relative w-full h-full bg-transparent flex items-center justify-center overflow-hidden snap-start">
      {/* Media Content */}
      <div 
        className="relative w-full h-full flex items-center justify-center cursor-pointer"
        {...doubleTap}
        onClick={handleVideoToggle}
      >
        {item.type === "video" ? (
          <video
            ref={videoRef}
            src={item.urls[0]}
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
                  if (info.offset.x < -threshold && currentImageIndex < item.urls.length - 1) {
                    setCurrentImageIndex(prev => prev + 1);
                  } else if (info.offset.x > threshold && currentImageIndex > 0) {
                    setCurrentImageIndex(prev => prev - 1);
                  }
                }}
              >
                <AnimatePresence mode="wait">
                  <motion.img
                    key={currentImageIndex}
                    src={item.urls[currentImageIndex]}
                    initial={{ opacity: 0, x: 100 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -100 }}
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                    className="w-full h-full object-contain flex-shrink-0 pointer-events-none"
                    referrerPolicy="no-referrer"
                  />
                </AnimatePresence>
              </motion.div>
              
              {item.urls.length > 1 && (
              <>
                {currentImageIndex > 0 && (
                  <button 
                    onClick={prevImage}
                    className="absolute left-4 top-1/2 -translate-y-1/2 p-2 bg-black/20 backdrop-blur-md rounded-full text-white hover:bg-black/40 transition-all z-10"
                  >
                    <ChevronLeft className="w-6 h-6" />
                  </button>
                )}
                {currentImageIndex < item.urls.length - 1 && (
                  <button 
                    onClick={nextImage}
                    className="absolute right-4 top-1/2 -translate-y-1/2 p-2 bg-black/20 backdrop-blur-md rounded-full text-white hover:bg-black/40 transition-all z-10"
                  >
                    <ChevronRight className="w-6 h-6" />
                  </button>
                )}
                {/* Dots at the bottom */}
                <div className="absolute bottom-24 left-1/2 -translate-x-1/2 flex gap-1.5 z-10">
                  {item.urls.map((_, i) => (
                    <div 
                      key={i} 
                      className={`w-1.5 h-1.5 rounded-full transition-all duration-300 ${i === currentImageIndex ? "bg-white w-4" : "bg-white/40"}`} 
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* Play/Pause Overlay */}
        {item.type === "video" && !isPlaying && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/20">
            <motion.div initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
              <Play className="w-20 h-20 text-white fill-white opacity-80" />
            </motion.div>
          </div>
        )}

        {/* Double Tap Heart Animation */}
        <AnimatePresence>
          {showHeartAnimation && (
            <motion.div
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: [0, 1.2, 1], opacity: [0, 1, 0] }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 flex items-center justify-center pointer-events-none z-50"
            >
              <Heart className="w-32 h-32 text-red-500 fill-red-500 shadow-2xl" />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Right Sidebar Actions */}
      <div className="absolute right-2 sm:right-4 bottom-32 flex flex-col gap-4 sm:gap-6 z-40">
        <div className="flex flex-col items-center gap-1">
          <button 
            onClick={(e) => { e.stopPropagation(); handleLike(); }}
            className="p-2.5 sm:p-3 bg-black/40 backdrop-blur-xl rounded-full border border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Heart className={`w-6 h-6 sm:w-7 sm:h-7 ${isLiked ? "text-red-500 fill-red-500" : "text-white"}`} />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-white drop-shadow-md">{likesCount}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button 
            onClick={(e) => { e.stopPropagation(); setShowComments(true); }}
            className="p-2.5 sm:p-3 bg-black/40 backdrop-blur-xl rounded-full border border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <MessageCircle className="w-6 h-6 sm:w-7 sm:h-7 text-white" />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-white drop-shadow-md">{item.comments}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button 
            onClick={handleSave}
            className="p-2.5 sm:p-3 bg-black/40 backdrop-blur-xl rounded-full border border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Bookmark className={`w-6 h-6 sm:w-7 sm:h-7 ${isSaved ? "text-yellow-500 fill-yellow-500" : "text-white"}`} />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-white drop-shadow-md">{t.save}</span>
        </div>

        <div className="flex flex-col items-center gap-1">
          <button 
            onClick={(e) => { e.stopPropagation(); setShowShareSheet(true); }}
            className="p-2.5 sm:p-3 bg-black/40 backdrop-blur-xl rounded-full border border-white/5 hover:scale-110 active:scale-95 transition-all"
          >
            <Share2 className="w-6 h-6 sm:w-7 sm:h-7 text-white" />
          </button>
          <span className="text-[10px] sm:text-xs font-bold text-white drop-shadow-md">{t.share}</span>
        </div>
      </div>

      {/* Bottom Info */}
      <div className="absolute bottom-0 left-0 w-full p-6 bg-gradient-to-t from-black/80 via-black/40 to-transparent z-30">
        <div className="max-w-[80%] space-y-3">
          <h3 className="font-bold text-lg text-white">@{item.author}</h3>
          <p 
            className="text-white/90 text-sm line-clamp-2 cursor-pointer hover:text-white transition-colors"
            onClick={(e) => { e.stopPropagation(); setShowDescription(true); }}
          >
            {item.description}
          </p>
        </div>
      </div>

      {/* Description Sheet */}
      <AnimatePresence>
        {showDescription && (
          <>
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowDescription(false)}
              className="absolute inset-0 bg-black/60 backdrop-blur-sm z-[60]"
            />
            <motion.div
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="absolute bottom-0 left-0 w-full bg-zinc-950 rounded-t-[32px] p-8 z-[70] border-t border-white/5"
            >
              <div className="w-12 h-1.5 bg-zinc-700 rounded-full mx-auto mb-8" />
              <div className="space-y-6">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-zinc-800 rounded-full border border-white/10" />
                  <div>
                    <h4 className="font-bold text-white">@{item.author}</h4>
                    <p className="text-xs text-zinc-500">{t.posted} 2 {t.hoursAgo}</p>
                  </div>
                </div>
                <div className="prose prose-invert max-w-none">
                  <p className="text-zinc-300 leading-relaxed text-lg">
                    {item.fullDescription}
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
        )}
      </AnimatePresence>

      {/* Comments Sheet */}
      <AnimatePresence>
        {showComments && (
          <>
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowComments(false)}
              className="absolute inset-0 bg-black/60 backdrop-blur-sm z-[60]"
            />
            <motion.div
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="absolute bottom-0 left-0 w-full h-[70vh] bg-zinc-950 rounded-t-[32px] flex flex-col z-[70] border-t border-white/5"
            >
              <div className="p-4 border-b border-white/5 flex flex-col items-center">
                <div className="w-12 h-1.5 bg-zinc-700 rounded-full mb-4" />
                <h3 className="font-bold text-white">{item.comments} {t.comments}</h3>
              </div>

              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {commentsList.map(comment => (
                  <div key={comment.id} className="space-y-4">
                    <div className="flex gap-3">
                      <div className="w-10 h-10 bg-zinc-800 rounded-full flex-shrink-0" />
                      <div className="flex-1 space-y-1">
                        <div className="flex items-center justify-between">
                          <h4 className="text-sm font-bold text-white">@{comment.author}</h4>
                          <button 
                            onClick={() => toggleCommentLike(comment.id)}
                            className="flex flex-col items-center gap-0.5"
                          >
                            <Heart className={`w-4 h-4 ${comment.isLiked ? "text-red-500 fill-red-500" : "text-zinc-500"}`} />
                            <span className="text-[10px] text-zinc-500">{comment.likes}</span>
                          </button>
                        </div>
                        <p className="text-sm text-zinc-300">{comment.text}</p>
                        <div className="flex items-center gap-4 text-xs font-bold text-zinc-500">
                          <span>{comment.timestamp}</span>
                          <button className="hover:text-white transition-colors">{t.reply}</button>
                        </div>
                      </div>
                    </div>
                    
                    {/* Replies */}
                    {comment.replies.map(reply => (
                      <div key={reply.id} className="flex gap-3 ml-12">
                        <div className="w-8 h-8 bg-zinc-800 rounded-full flex-shrink-0" />
                        <div className="flex-1 space-y-1">
                          <div className="flex items-center justify-between">
                            <h4 className="text-sm font-bold text-white">@{reply.author}</h4>
                            <Heart className="w-3.5 h-3.5 text-zinc-500" />
                          </div>
                          <p className="text-sm text-zinc-300">{reply.text}</p>
                          <div className="flex items-center gap-4 text-xs font-bold text-zinc-500">
                            <span>{reply.timestamp}</span>
                            <button className="hover:text-white transition-colors">{t.reply}</button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>

              <div className="p-6 border-t border-white/5 bg-black/40 backdrop-blur-xl">
                <div className="flex items-center gap-3 bg-zinc-900 rounded-2xl px-4 py-2">
                  <input 
                    type="text" 
                    value={newComment}
                    onChange={(e) => setNewComment(e.target.value)}
                    placeholder={t.addComment}
                    className="flex-1 bg-transparent border-none outline-none text-sm text-white py-2"
                  />
                  <button 
                    onClick={handleAddComment}
                    className={`p-2 rounded-xl transition-all ${newComment.trim() ? "bg-white text-black scale-100" : "bg-zinc-700 text-zinc-500 scale-90"}`}
                  >
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Share Sheet */}
      <AnimatePresence>
        {showShareSheet && (
          <>
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowShareSheet(false)}
              className="absolute inset-0 bg-black/60 backdrop-blur-sm z-[80]"
            />
            <motion.div
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="absolute bottom-0 left-0 w-full bg-zinc-950 rounded-t-[32px] p-8 z-[90] border-t border-white/5"
            >
              <div className="w-12 h-1.5 bg-zinc-700 rounded-full mx-auto mb-8" />
              <div className="space-y-6">
                <h3 className="text-xl font-bold text-white text-center">{t.share}</h3>
                <div className="bg-zinc-900 p-4 rounded-2xl border border-white/5 break-all">
                  <p className="text-zinc-400 text-sm mb-2 uppercase tracking-widest font-bold">Post Link</p>
                  <code className="text-white text-sm">https://newscloud.app/post/{item.id}</code>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <button 
                    onClick={() => {
                      navigator.clipboard.writeText(`https://newscloud.app/post/${item.id}`);
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
        )}
      </AnimatePresence>
    </div>
  );
}
