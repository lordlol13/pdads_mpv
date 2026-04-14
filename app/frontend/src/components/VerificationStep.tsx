import { useRef, useState, useEffect, KeyboardEvent } from "react";
import { motion, useAnimation } from "motion/react";
import { Check, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLanguage } from "../context/LanguageContext";

interface VerificationStepProps {
  key?: string | number;
  email: string;
  verificationId: string;
  onVerify: (code: string) => Promise<void> | void;
  onResend?: () => Promise<{ sent: boolean; debug_code?: string | null } | void> | void;
  onBack?: () => void;
  direction?: number;
  isLoading?: boolean;
  error?: string | null;
}

export function VerificationStep({
  email,
  verificationId,
  onVerify,
  onResend,
  direction = 1,
  isLoading = false,
  error = null,
}: VerificationStepProps) {
  const { t } = useLanguage();
  const [code, setCode] = useState<string[]>(Array(6).fill(""));
  const [status, setStatus] = useState<"idle" | "error" | "success">("idle");
  const [resendInfo, setResendInfo] = useState<string | null>(null);
  const [resending, setResending] = useState(false);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const controls = useAnimation();

  const handleChange = (index: number, value: string) => {
    let normalized = value;
    if (normalized.length > 1) {
      normalized = normalized[0];
    }
    if (!/^\d*$/.test(normalized)) {
      return;
    }

    const newCode = [...code];
    newCode[index] = normalized;
    setCode(newCode);

    if (normalized && index < 5) {
      inputs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index: number, event: KeyboardEvent) => {
    if (event.key === "Backspace" && !code[index] && index > 0) {
      inputs.current[index - 1]?.focus();
    }
  };

  const verifyCode = async () => {
    const fullCode = code.join("");
    if (fullCode.length < 6 || isLoading) {
      return;
    }

    try {
      await onVerify(fullCode);
      setStatus("success");
    } catch {
      setStatus("error");
      await controls.start({
        x: [0, -10, 10, -10, 10, 0],
        transition: { duration: 0.4 },
      });
      setTimeout(() => {
        setStatus("idle");
        setCode(Array(6).fill(""));
        inputs.current[0]?.focus();
      }, 500);
    }
  };

  useEffect(() => {
    if (code.every((digit) => digit !== "")) {
      void verifyCode();
    }
  }, [code]);

  const handleResend = async () => {
    if (!onResend || !verificationId || resending) {
      return;
    }

    setResendInfo(null);
    setResending(true);
    try {
      const result = await onResend();
      setCode(Array(6).fill(""));
      inputs.current[0]?.focus();
      if (result && typeof result === "object" && "sent" in result && result.sent === false) {
        const debugCode =
          "debug_code" in result && typeof result.debug_code === "string" && result.debug_code.trim()
            ? ` Debug code: ${result.debug_code}`
            : "";
        setResendInfo(`Email delivery failed.${debugCode}`);
      } else {
        setResendInfo("Code sent. Check your email.");
      }
    } catch (err) {
      setResendInfo(err instanceof Error ? err.message : "Unable to resend code.");
    } finally {
      setResending(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: direction > 0 ? 50 : -50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: direction > 0 ? -50 : 50 }}
      className="relative space-y-8 text-center"
    >
      <div className="flex justify-center">
        <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-white/10">
          <Mail className="h-8 w-8 text-white" />
          {status === "success" ? (
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-zinc-950 bg-green-500"
            >
              <Check className="h-4 w-4 text-white" />
            </motion.div>
          ) : null}
        </div>
      </div>

      <div className="space-y-2">
        <h2 className="text-xl md:text-3xl font-bold tracking-tight">{t.verifyEmail}</h2>
        <p className="text-zinc-500">
          {t.verifyDesc} <span className="font-medium text-zinc-200">{email || "your email"}</span>
        </p>
      </div>

      <motion.div animate={controls} className="flex justify-center gap-2 sm:gap-4">
        {code.map((digit, index) => (
          <div key={index} className="relative">
            <input
              ref={(el) => {
                inputs.current[index] = el;
              }}
              type="text"
              maxLength={1}
              value={digit}
              onChange={(event) => handleChange(index, event.target.value)}
              onKeyDown={(event) => handleKeyDown(index, event)}
              className={`h-10 w-9 rounded-xl border-2 bg-zinc-900 text-center text-xl font-bold transition-all duration-200 focus:outline-none md:h-14 md:w-12 md:text-2xl sm:h-16 sm:w-14 ${
                status === "error"
                  ? "border-red-500 text-red-500"
                  : status === "success"
                    ? "border-green-500 text-green-500"
                    : "border-zinc-800 text-white focus:border-white"
              }`}
            />
            {status === "success" ? (
              <motion.div
                initial={{ scale: 0, opacity: 0 }}
                animate={{ scale: [1, 2], opacity: [0.5, 0] }}
                className="pointer-events-none absolute inset-0 rounded-xl bg-green-500/20"
              />
            ) : null}
          </div>
        ))}
      </motion.div>

      <div className="space-y-4">
        <p className="text-sm text-zinc-500">
          Didn't receive the code?
          <button
            type="button"
            onClick={() => void handleResend()}
            disabled={!verificationId || resending}
            className="ml-2 font-medium text-white hover:text-zinc-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {resending ? "Sending..." : t.resend}
          </button>
        </p>
        {resendInfo ? <p className="text-sm text-zinc-300">{resendInfo}</p> : null}
        {error ? <p className="text-sm text-red-400">{error}</p> : null}
      </div>

      <Button
        type="button"
        variant="ghost"
        onClick={() => {
          setCode(Array(6).fill(""));
          inputs.current[0]?.focus();
        }}
        className="text-zinc-500 hover:text-zinc-300"
      >
        {isLoading ? "Verifying..." : "Reset code"}
      </Button>
    </motion.div>
  );
}




