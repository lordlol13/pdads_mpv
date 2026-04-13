import { motion } from "motion/react";
import { CheckCircle2 } from "lucide-react";
import ReactConfetti from "react-confetti";
import { useEffect, useState } from "react";
import { useLanguage } from "../context/LanguageContext";

interface SuccessStepProps {
  onComplete?: () => void;
  key?: string | number;
}

export function SuccessStep({ onComplete }: SuccessStepProps) {
  const { t } = useLanguage();
  const [windowSize, setWindowSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    setWindowSize({ width: window.innerWidth, height: window.innerHeight });
    
    // Simulate automatic redirect after 3 seconds
    const timer = setTimeout(() => {
      console.log("Redirecting to dashboard...");
      if (onComplete) onComplete();
    }, 3000);

    return () => clearTimeout(timer);
  }, [onComplete]);

  return (
    <motion.div
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      className="text-center space-y-8 py-10"
    >
      <ReactConfetti
        width={windowSize.width}
        height={windowSize.height}
        recycle={false}
        numberOfPieces={200}
        colors={["#ffffff", "#22c55e", "#f59e0b", "#ef4444"]}
      />

      <div className="flex justify-center">
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", damping: 12, stiffness: 200, delay: 0.2 }}
          className="w-24 h-24 bg-green-500/10 rounded-full flex items-center justify-center relative"
        >
          <CheckCircle2 className="w-16 h-16 text-green-500" />
          <motion.div
            initial={{ opacity: 0, scale: 0 }}
            animate={{ opacity: [0, 1, 0], scale: [1, 2] }}
            transition={{ duration: 1, repeat: Infinity, repeatDelay: 2 }}
            className="absolute inset-0 bg-green-500/20 rounded-full"
          />
        </motion.div>
      </div>

      <div className="space-y-4">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          <h2 className="text-4xl font-bold tracking-tight text-white">{t.success}</h2>
          <p className="text-zinc-500 text-lg mt-2">
            {t.redirecting}
          </p>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.8 }}
        className="pt-4"
      >
        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2 text-zinc-400">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
              className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full"
            />
            <span className="text-sm font-medium">{t.redirecting}</span>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

