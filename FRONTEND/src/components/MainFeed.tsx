import { useState, useRef, useEffect, useMemo } from "react";
import { motion } from "motion/react";
import { Home, Search, User, Settings, Globe, Moon, Sun, Bookmark, ChevronRight, ChevronDown, ChevronLeft } from "lucide-react";
import { FeedPost } from "./FeedPost";
import { useLanguage } from "../context/LanguageContext";
import { Language } from "../translations";

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

const MOCK_DATA: MediaItem[] = [
  {
    id: "1",
    type: "video" as const,
    urls: ["https://assets.mixkit.co/videos/preview/mixkit-girl-in-neon-light-1282-large.mp4"],
    description: "Future of News Cloud is here! 🚀 #tech #future",
    fullDescription: "We are excited to announce the launch of our new AI-driven news platform. News Cloud brings you the most relevant stories in a format you love. Stay tuned for more updates and features coming your way soon!",
    author: "news_cloud_official",
    likes: 12400,
    comments: 856,
    isLiked: false,
    isSaved: false,
  },
  {
    id: "2",
    type: "image" as const,
    urls: [
      "https://picsum.photos/seed/news1/1080/1920",
      "https://picsum.photos/seed/news2/1080/1920",
      "https://picsum.photos/seed/news3/1080/1920"
    ],
    description: "Exploring the hidden gems of the digital world. Swipe to see more! 🌍",
    fullDescription: "Digital exploration is not just about finding new sites, it's about understanding the architecture of the web. These images capture the essence of modern digital infrastructure and the beauty of data visualization.",
    author: "digital_explorer",
    likes: 8900,
    comments: 432,
    isLiked: true,
    isSaved: true,
  },
  {
    id: "3",
    type: "video" as const,
    urls: ["https://assets.mixkit.co/videos/preview/mixkit-tree-with-yellow-leaves-low-angle-shot-1571-large.mp4"],
    description: "Nature is the best designer. 🍂 #nature #peace",
    fullDescription: "Sometimes we need to step back from our screens and appreciate the natural world. This short clip reminds us of the simple beauty that surrounds us every day, often unnoticed in our busy digital lives.",
    author: "nature_vibes",
    likes: 45600,
    comments: 1200,
    isLiked: false,
    isSaved: false,
  }
];

export function MainFeed() {
  const { language, setLanguage, t } = useLanguage();
  const [feedData, setFeedData] = useState<MediaItem[]>(MOCK_DATA);
  const [activeTab, setActiveTab] = useState<"home" | "search" | "profile">("home");
  const [showSavedOnly, setShowSavedOnly] = useState(false);
  const [activePostIndex, setActivePostIndex] = useState(0);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const feedRef = useRef<HTMLDivElement>(null);

  const savedPosts = useMemo(() => feedData.filter(post => post.isSaved), [feedData]);

  const toggleSave = (id: string) => {
    setFeedData(prev => prev.map(post => 
      post.id === id ? { ...post, isSaved: !post.isSaved } : post
    ));
  };

  // Scroll to active post when index changes programmatically (e.g. from Saved posts)
  useEffect(() => {
    if (feedRef.current && activeTab === "home") {
      feedRef.current.scrollTo({
        top: activePostIndex * feedRef.current.clientHeight,
        behavior: "smooth"
      });
    }
  }, [activePostIndex, activeTab]);

  const handleScroll = () => {
    if (feedRef.current) {
      const index = Math.round(feedRef.current.scrollTop / feedRef.current.clientHeight);
      setActivePostIndex(index);
    }
  };

  const languages: { name: string; code: Language }[] = [
    { name: "O'zbekcha", code: "uz" },
    { name: "Русский", code: "ru" },
    { name: "English", code: "en" }
  ];

  return (
    <div className={`fixed inset-0 flex flex-col transition-colors duration-500 ${theme === "dark" ? "bg-black text-white" : "bg-white text-black"}`}>
      {/* Main Content Area */}
      <div className="flex-1 relative overflow-hidden">
        {activeTab === "home" && (
          <div 
            ref={feedRef}
            onScroll={handleScroll}
            className="h-full overflow-y-scroll snap-y snap-mandatory scrollbar-hide"
          >
            {feedData.map((item, index) => (
              <FeedPost 
                key={item.id} 
                item={item} 
                isActive={activePostIndex === index}
                onToggleSave={toggleSave}
              />
            ))}
          </div>
        )}

        {activeTab === "search" && (
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className={`h-full overflow-y-auto p-6 pt-20 space-y-6 ${theme === "dark" ? "bg-black" : "bg-zinc-50"}`}
          >
            <h2 className="text-3xl font-bold">{t.explore}</h2>
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-zinc-500" />
              <input 
                type="text" 
                placeholder={t.searchPlaceholder}
                className={`w-full h-14 rounded-2xl pl-12 pr-4 outline-none transition-all ${theme === "dark" ? "bg-zinc-900 text-white border border-white/5 focus:ring-1 focus:ring-white/10" : "bg-white text-black border border-zinc-200 focus:ring-1 focus:ring-black/10"}`}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              {["Technology", "Science", "Politics", "Entertainment", "Sports", "Business"].map(tag => (
                <div key={tag} className={`h-32 rounded-3xl flex items-center justify-center border transition-colors cursor-pointer ${theme === "dark" ? "bg-zinc-900 border-white/5 hover:bg-zinc-800" : "bg-white border-zinc-200 hover:bg-zinc-50"}`}>
                  <span className="font-bold">#{tag}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {activeTab === "profile" && (
          <motion.div 
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className={`h-full overflow-y-auto p-6 pt-20 space-y-8 ${theme === "dark" ? "bg-black" : "bg-zinc-50"}`}
          >
            {showSavedOnly ? (
              <div className="space-y-6">
                <div className="flex items-center gap-4">
                  <button 
                    onClick={() => setShowSavedOnly(false)}
                    className={`p-2 rounded-full transition-colors ${theme === "dark" ? "bg-zinc-900 hover:bg-zinc-800" : "bg-white border border-zinc-200 hover:bg-zinc-100"}`}
                  >
                    <ChevronLeft className="w-6 h-6" />
                  </button>
                  <h2 className="text-2xl font-bold">{t.savedPosts}</h2>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  {savedPosts.map(post => (
                    <div 
                      key={post.id} 
                      className={`aspect-[9/16] rounded-3xl overflow-hidden relative group cursor-pointer border ${theme === "dark" ? "bg-zinc-900 border-white/5" : "bg-white border-zinc-200"}`}
                      onClick={() => {
                        setActiveTab("home");
                        const index = feedData.findIndex(p => p.id === post.id);
                        setActivePostIndex(index);
                        setShowSavedOnly(false);
                      }}
                    >
                      <img 
                        src={post.urls[0]} 
                        alt={post.description} 
                        className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                        referrerPolicy="no-referrer"
                      />
                      <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-4">
                        <p className="text-xs font-medium line-clamp-2">{post.description}</p>
                      </div>
                    </div>
                  ))}
                </div>
                {savedPosts.length === 0 && (
                  <div className="text-center py-20 text-zinc-500">
                    <Bookmark className="w-12 h-12 mx-auto mb-4 opacity-20" />
                    <p>No saved posts yet</p>
                  </div>
                )}
              </div>
            ) : (
              <>
                <div className="flex flex-col items-center gap-4">
                  <div className={`w-24 h-24 rounded-full border-4 ${theme === "dark" ? "bg-zinc-900 border-white/5" : "bg-white border-zinc-200"}`} />
                  <div className="text-center">
                    <h2 className="text-2xl font-bold">Murodhojaev Muzaffarhoja</h2>
                    <p className="text-zinc-500 text-sm">@muzaffar_dev</p>
                  </div>
                </div>

                <div className="space-y-4">
                  <h3 className="text-sm font-bold text-zinc-500 uppercase tracking-widest px-2">{t.settings}</h3>
                  <div className={`rounded-[32px] overflow-hidden border ${theme === "dark" ? "bg-zinc-900 border-white/5" : "bg-white border-zinc-200"}`}>
                    <button 
                      onClick={() => setShowSavedOnly(true)}
                      className={`w-full flex items-center justify-between p-5 transition-colors group ${theme === "dark" ? "hover:bg-white/5" : "hover:bg-zinc-50"}`}
                    >
                      <div className="flex items-center gap-4">
                        <div className="p-2 bg-blue-500/10 rounded-xl text-blue-500">
                          <Bookmark className="w-5 h-5" />
                        </div>
                        <span className="font-medium">{t.savedPosts}</span>
                      </div>
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${theme === "dark" ? "bg-white/5 group-hover:bg-white/10" : "bg-zinc-100 group-hover:bg-zinc-200"}`}>
                        <ChevronRight className="w-4 h-4 text-zinc-400" />
                      </div>
                    </button>

                    <div className={`p-5 border-t ${theme === "dark" ? "border-white/5" : "border-zinc-100"}`}>
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
                          onChange={(e) => setLanguage(e.target.value as Language)}
                          className={`w-full h-12 border rounded-xl px-4 text-sm font-bold appearance-none outline-none cursor-pointer ${theme === "dark" ? "bg-black border-white/5 text-white focus:ring-1 focus:ring-white/10" : "bg-zinc-50 border-zinc-200 text-black focus:ring-1 focus:ring-black/10"}`}
                        >
                          {languages.map(lang => (
                            <option key={lang.code} value={lang.code} className={theme === "dark" ? "bg-black text-white" : "bg-white text-black"}>
                              {lang.name}
                            </option>
                          ))}
                        </select>
                        <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 pointer-events-none" />
                      </div>
                    </div>

                    <button 
                      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                      className={`w-full flex items-center justify-between p-5 transition-colors border-t ${theme === "dark" ? "border-white/5 hover:bg-white/5" : "border-zinc-100 hover:bg-zinc-50"}`}
                    >
                      <div className="flex items-center gap-4">
                        <div className="p-2 bg-yellow-500/10 rounded-xl text-yellow-500">
                          {theme === "dark" ? <Moon className="w-5 h-5" /> : <Sun className="w-5 h-5" />}
                        </div>
                        <span className="font-medium">{t.theme}</span>
                      </div>
                      <div className={`w-12 h-6 rounded-full relative transition-colors ${theme === "dark" ? "bg-zinc-700" : "bg-zinc-200"}`}>
                        <div className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow-sm transition-all ${theme === "dark" ? "left-7" : "left-1"}`} />
                      </div>
                    </button>

                    <button className={`w-full flex items-center justify-between p-5 transition-colors border-t ${theme === "dark" ? "border-white/5 hover:bg-white/5" : "border-zinc-100 hover:bg-zinc-50"}`}>
                      <div className="flex items-center gap-4">
                        <div className="p-2 bg-red-500/10 rounded-xl text-red-500">
                          <Settings className="w-5 h-5" />
                        </div>
                        <span className="font-medium">{t.accountSettings}</span>
                      </div>
                    </button>
                  </div>
                </div>
              </>
            )}
          </motion.div>
        )}
      </div>

      {/* Bottom Navigation Bar */}
      <div className={`h-20 border-t transition-colors duration-500 flex items-center justify-around px-6 pb-2 ${theme === "dark" ? "bg-black border-white/10" : "bg-white border-zinc-200"}`}>
        <button 
          onClick={() => setActiveTab("home")}
          className={`flex flex-col items-center gap-1 transition-all ${activeTab === "home" ? (theme === "dark" ? "text-white scale-110" : "text-black scale-110") : "text-zinc-500 hover:text-zinc-300"}`}
        >
          <Home className={`w-6 h-6 ${activeTab === "home" ? (theme === "dark" ? "fill-white" : "fill-black") : ""}`} />
          <span className="text-[10px] font-bold uppercase tracking-widest">{t.home}</span>
        </button>

        <button 
          onClick={() => setActiveTab("search")}
          className={`flex flex-col items-center gap-1 transition-all ${activeTab === "search" ? (theme === "dark" ? "text-white scale-110" : "text-black scale-110") : "text-zinc-500 hover:text-zinc-300"}`}
        >
          <Search className="w-6 h-6" />
          <span className="text-[10px] font-bold uppercase tracking-widest">{t.search}</span>
        </button>

        <button 
          onClick={() => setActiveTab("profile")}
          className={`flex flex-col items-center gap-1 transition-all ${activeTab === "profile" ? (theme === "dark" ? "text-white scale-110" : "text-black scale-110") : "text-zinc-500 hover:text-zinc-300"}`}
        >
          <User className={`w-6 h-6 ${activeTab === "profile" ? (theme === "dark" ? "fill-white" : "fill-black") : ""}`} />
          <span className="text-[10px] font-bold uppercase tracking-widest">{t.profile}</span>
        </button>
      </div>
    </div>
  );
}
