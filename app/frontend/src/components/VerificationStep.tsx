import { useRef, useState, useEffect, KeyboardEvent } from "react";
import { motion, useAnimation } from "motion/react";
import { Check, Mail, ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLanguage } from "../context/LanguageContext";

interface VerificationStepProps {
  email: string;
  verificationId: string;
  onVerify: (code: string) => Promise<void> | void;
  onBack?: () => void;
  direction?: number;
  isLoading?: boolean;
  error?: string | null;
}

export function VerificationStep({ email, verificationId, onVerify, onBack, direction = 1, isLoading = false, error = null }: VerificationStepProps) {
  const { t } = useLanguage();
  const [code, setCode] = useState<string[]>(Array(6).fill(""));
  const [status, setStatus] = useState<"idle" | "error" | "success">("idle");
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const controls = useAnimation();

  const handleChange = (index: number, value: string) => {
    if (value.length > 1) value = value[0];
    if (!/^\d*$/.test(value)) return;

    const newCode = [...code];
    newCode[index] = value;
    setCode(newCode);

    if (value && index < 5) {
      inputs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index: number, e: KeyboardEvent) => {
    if (e.key === "Backspace" && !code[index] && index > 0) {
      inputs.current[index - 1]?.focus();
    }
  };

  const verifyCode = async () => {
    const fullCode = code.join("");
    if (fullCode.length < 6) return;

    try {
      await onVerify(fullCode);
      setStatus("success");
    } catch {
      setStatus("error");
      await controls.start({
        x: [0, -10, 10, -10, 10, 0],
        transition: { duration: 0.4 }
      });
      setTimeout(() => {
        setStatus("idle");
        setCode(Array(6).fill(""));
        inputs.current[0]?.focus();
      }, 500);
    }
  };

  useEffect(() => {
    if (code.every(digit => digit !== "")) {
      verifyCode();
    }
  }, [code]);

  return (
    <motion.div
      initial={{ opacity: 0, x: direction > 0 ? 50 : -50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: direction > 0 ? -50 : 50 }}
      className="space-y-8 text-center relative"
    >
      <div className="flex justify-center">
        <div className="w-16 h-16 bg-white/10 rounded-full flex items-center justify-center relative">
          <Mail className="w-8 h-8 text-white" />
          {status === "success" && (
            <motion.div 
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              className="absolute -top-1 -right-1 w-6 h-6 bg-green-500 rounded-full flex items-center justify-center border-2 border-zinc-950"
            >
              <Check className="w-4 h-4 text-white" />
            </motion.div>
          )}
        </div>
      </div>

      <div className="space-y-2">
        <h2 className="text-3xl font-bold tracking-tight">{t.verifyEmail}</h2>
        <p className="text-zinc-500">
          {t.verifyDesc} <span className="text-zinc-200 font-medium">{email || "your email"}</span>
        </p>
      </div>

      <motion.div 
        animate={controls}
        className="flex justify-center gap-2 sm:gap-4"
      >
        {code.map((digit, i) => (
          <div key={i} className="relative">
            <input
              ref={(el) => (inputs.current[i] = el)}
              type="text"
              maxLength={1}
              value={digit}
              onChange={(e) => handleChange(i, e.target.value)}
              onKeyDown={(e) => handleKeyDown(i, e)}
              className={`w-12 h-14 sm:w-14 sm:h-16 text-center text-2xl font-bold bg-zinc-900 border-2 rounded-xl focus:outline-none transition-all duration-200 ${
                status === "error" 
                  ? "border-red-500 text-red-500" 
                  : status === "success" 
                    ? "border-green-500 text-green-500" 
                    : "border-zinc-800 focus:border-white text-white"
              }`}
            />
            {status === "success" && (
              <motion.div
                initial={{ scale: 0, opacity: 0 }}
                animate={{ scale: [1, 2], opacity: [0.5, 0] }}
                className="absolute inset-0 bg-green-500/20 rounded-xl pointer-events-none"
              />
            )}
          </div>
        ))}
      </motion.div>

      <div className="space-y-4">
        <p className="text-sm text-zinc-500">
          Didn't receive the code? 
          <button className="ml-2 text-white hover:text-zinc-300 font-medium">{t.resend}</button>
        </p>
        <Button 
          type="button"
          variant="ghost" 
          onClick={() => setCode(verificationId ? Array(6).fill("") : Array(6).fill(""))}
          className="text-zinc-500 hover:text-zinc-300"
        >
          {isLoading ? "Verifying..." : 'Reset code'}
        </Button>
        {error ? <p className="text-sm text-red-400">{error}</p> : null}
      </div>
    </motion.div>
  );
}
