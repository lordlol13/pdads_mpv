import { motion } from "motion/react";
import { AuthStep } from "@/src/types";

interface ProgressBarProps {
  currentStep: AuthStep;
}

const STEP_NAMES = ["Account", "Verify", "Profile", "Success"];

export function ProgressBar({ currentStep }: ProgressBarProps) {
  const isComplete = currentStep === 4;
  const isExpanded = currentStep > 1;

  return (
    <motion.div 
      initial={false}
      animate={{ 
        maxWidth: isExpanded ? "100%" : "320px",
      }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="w-full px-4 mb-16 relative z-50 mx-auto"
    >
      <div className="flex gap-4 h-2.5">
        {STEP_NAMES.map((name, i) => {
          const s = i + 1;
          return (
            <div key={s} className="flex-1 relative">
              <div className="h-full bg-zinc-800 rounded-full overflow-hidden border border-zinc-700/50 shadow-inner">
                <motion.div
                  className={`h-full ${isComplete ? "bg-green-500" : "bg-white"}`}
                  initial={{ width: 0 }}
                  animate={{ 
                    width: currentStep >= s ? "100%" : "0%" 
                  }}
                  transition={{ duration: 0.5, ease: "easeInOut" }}
                />
              </div>
              <motion.span 
                animate={{
                  color: currentStep >= s ? "#ffffff" : "#52525b",
                  opacity: currentStep >= s ? 1 : 0.4,
                  scale: currentStep === s ? 1 : 0.95
                }}
                className="absolute -bottom-7 left-1/2 -translate-x-1/2 text-[10px] uppercase tracking-[0.2em] font-black whitespace-nowrap"
              >
                {name}
              </motion.span>
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}
