import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";

import { authService } from "../api/services";
import { buildApiUrl } from "../api/client";
import { useLanguage } from "../context/LanguageContext";

const GoogleIcon = () => (
  <svg viewBox="0 0 24 24" className="w-5 h-5">
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05" />
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
  </svg>
);

const MicrosoftIcon = () => (
  <svg viewBox="0 0 23 23" className="w-5 h-5">
    <path fill="#f35022" d="M0 0h11.4v11.4H0z" />
    <path fill="#80bb03" d="M11.6 0H23v11.4H11.6z" />
    <path fill="#03a4ef" d="M0 11.6h11.4V23H0z" />
    <path fill="#ffb903" d="M11.6 11.6H23V23H11.6z" />
  </svg>
);

interface SocialButtonsProps {
  variant?: "desktop" | "mobile";
}

export function SocialButtons({ variant = "desktop" }: SocialButtonsProps) {
  const { t } = useLanguage();
  const isMobile = variant === "mobile";
  const [enabledProviders, setEnabledProviders] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;

    const loadProviders = async () => {
      try {
        const response = await authService.getOAuthProviders();
        if (!cancelled) {
          setEnabledProviders(new Set((response.providers || []).map((item) => item.toLowerCase())));
        }
      } catch {
        if (!cancelled) {
          setEnabledProviders(new Set());
        }
      }
    };

    void loadProviders();
    return () => {
      cancelled = true;
    };
  }, []);

  const providers = useMemo(
    () => [
      {
        key: "google",
        label: t.continueWithGoogle,
        icon: <GoogleIcon />,
      },
      {
        key: "microsoft",
        label: t.continueWithMicrosoft,
        icon: <MicrosoftIcon />,
      },
    ],
    [t.continueWithGoogle, t.continueWithMicrosoft],
  );

  const containerClasses = isMobile ? "flex flex-row justify-center gap-6" : "flex flex-col gap-3";
  const buttonClasses = isMobile
    ? "w-14 h-14 rounded-full flex items-center justify-center transition-all duration-300 hover:scale-110 active:scale-95 shadow-lg bg-white border border-zinc-200"
    : "flex items-center justify-center gap-3 py-3 px-4 rounded-xl transition-all duration-200 group w-full bg-white hover:bg-zinc-100 border border-zinc-200";

  const startOAuth = (provider: string) => {
    window.location.href = buildApiUrl(`/auth/oauth/${provider}/login`);
  };

  return (
    <motion.div initial="hidden" animate="visible" variants={{ visible: {} }} className={containerClasses}>
      {providers.map((provider) => {
        const enabled = enabledProviders.has(provider.key);
        return (
          <motion.button
            key={provider.key}
            variants={{
              hidden: { opacity: 0, y: isMobile ? 20 : 0, x: isMobile ? 0 : -20 },
              visible: { opacity: 1, y: 0, x: 0 },
            }}
            whileHover={enabled ? { scale: 1.08, boxShadow: "0 4px 24px 0 rgba(66,133,244,0.15)" } : {}}
            whileTap={enabled ? { scale: 0.96, boxShadow: "0 2px 8px 0 rgba(66,133,244,0.10)" } : {}}
            transition={{ type: "spring", stiffness: 400, damping: 20 }}
            type="button"
            disabled={!enabled}
            onClick={() => startOAuth(provider.key)}
            title={enabled ? provider.label : `${provider.label} (OAuth not configured)`}
            className={`${buttonClasses} ${!enabled ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            {provider.icon}
            {!isMobile ? <span className="font-medium text-sm text-zinc-900">{provider.label}</span> : null}
          </motion.button>
        );
      })}
    </motion.div>
  );
}

