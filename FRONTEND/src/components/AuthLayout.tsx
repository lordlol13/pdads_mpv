import { motion, AnimatePresence } from "motion/react";
import { ReactNode } from "react";
import { SlotText } from "./SlotText";
import { SocialButtons } from "./SocialButtons";
import { useLanguage } from "../context/LanguageContext";

interface AuthLayoutProps {
  children: ReactNode;
  showLeftPanel: boolean;
  isRegistering: boolean;
  onToggleMode: () => void;
  step: number;
}

export function AuthLayout({ children, showLeftPanel, isRegistering, onToggleMode, step }: AuthLayoutProps) {
  const { t } = useLanguage();
  const showSocials = step === 1;

  return (
    <div className="min-h-screen text-zinc-100 flex items-center justify-center p-4 lg:p-8 font-sans">
      {/* Main Card Container */}
      <div className="w-full max-w-5xl h-auto lg:h-[700px] bg-gradient-to-br from-black via-[#0a0f1a] to-zinc-900 backdrop-blur-md rounded-3xl shadow-2xl overflow-hidden flex flex-col lg:flex-row relative">
        {/* Star Background Pattern Overlay */}
        <div className="absolute inset-0 opacity-30 pointer-events-none animate-twinkle" style={{
          backgroundImage: `
            radial-gradient(1px 1px at 20px 30px, #fff, rgba(0,0,0,0)),
            radial-gradient(1px 1px at 40px 70px, #fff, rgba(0,0,0,0)),
            radial-gradient(1px 1px at 50px 160px, #fff, rgba(0,0,0,0)),
            radial-gradient(1px 1px at 90px 40px, #fff, rgba(0,0,0,0)),
            radial-gradient(1px 1px at 130px 80px, #fff, rgba(0,0,0,0)),
            radial-gradient(1px 1px at 160px 120px, #fff, rgba(0,0,0,0))
          `,
          backgroundSize: '200px 200px'
        }} />
        
        {/* Left Panel (Desktop only) */}
        <AnimatePresence mode="wait">
          {showLeftPanel && (
            <motion.div
              key="left-panel"
              initial={{ x: 0, opacity: 1 }}
              exit={{ x: "-100%", opacity: 0 }}
              transition={{ duration: 0.8, ease: [0.4, 0, 0.2, 1] }}
              className="hidden lg:flex w-1/2 bg-black/20 flex-col justify-center px-12 relative overflow-hidden"
            >
              <div className="space-y-8 max-w-md relative z-10">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 bg-white rounded-xl flex items-center justify-center shadow-lg shadow-white/10 overflow-hidden">
                    <img src="/input_file_1.png" alt="news cloud logo" className="w-full h-full object-cover" referrerPolicy="no-referrer" />
                  </div>
                  <h1 className="text-2xl font-bold tracking-tight">news cloud</h1>
                </div>
                
                <div className="space-y-4">
                  <h2 className="text-4xl font-light leading-tight min-h-[100px]">
                    <SlotText 
                      text={isRegistering ? t.joinFuture : t.welcomeBack} 
                    />
                    <br />
                    <span className="text-white font-medium underline underline-offset-8 decoration-zinc-700">
                      <SlotText text="news cloud" />
                    </span>
                  </h2>
                  <p className="text-zinc-500 text-lg">
                    {t.platformDesc}
                  </p>
                </div>

                <AnimatePresence>
                  {showSocials && (
                    <motion.div
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -20 }}
                    >
                      <SocialButtons variant="desktop" />
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="pt-8">
                  <p className="text-zinc-500 text-sm">
                    {isRegistering ? t.alreadyHaveAccount : t.dontHaveAccount}
                    <button 
                      onClick={onToggleMode}
                      className="ml-2 text-white hover:text-zinc-300 font-medium underline-offset-4 hover:underline transition-all"
                    >
                      {isRegistering ? t.login : t.createAccount}
                    </button>
                  </p>
                </div>
              </div>

              {/* Decorative elements */}
              <div className="absolute bottom-0 left-0 w-full h-64 bg-gradient-to-t from-white/5 to-transparent pointer-events-none" />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Right Panel / Content */}
        <motion.div 
          layout
          transition={{ 
            layout: { duration: 0.8, ease: [0.4, 0, 0.2, 1] },
            opacity: { duration: 0.4 }
          }}
          className={`flex-1 flex flex-col p-8 lg:p-16 bg-white/5 relative z-10 ${!showLeftPanel ? 'w-full' : ''}`}
        >
          <div className="w-full max-w-xl mx-auto flex flex-col h-full">
            {/* Content Area */}
            <div className="flex-1 flex flex-col">
              {children}
            </div>

            {/* Mobile Social Logins (Visible only on mobile) */}
            <AnimatePresence>
              {showSocials && (
                <motion.div 
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="lg:hidden mt-12 pt-8 w-full space-y-6 overflow-hidden"
                >
                  <div className="flex flex-col items-center gap-2">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-[0.2em] font-bold">
                      {t.orContinueWith}
                    </p>
                  </div>
                  <SocialButtons variant="mobile" />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
