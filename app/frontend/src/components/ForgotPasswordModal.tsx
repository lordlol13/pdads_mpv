import { useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "motion/react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useLanguage } from "../context/LanguageContext";

interface ForgotPasswordModalProps {
  open: boolean;
  defaultEmail?: string;
  onClose: () => void;
  onSendCode: (email: string) => Promise<void>;
  onResetPassword: (payload: { email: string; code: string; newPassword: string }) => Promise<void>;
}

export function ForgotPasswordModal({
  open,
  defaultEmail = "",
  onClose,
  onSendCode,
  onResetPassword,
}: ForgotPasswordModalProps) {
  const { t } = useLanguage();
  const [email, setEmail] = useState(defaultEmail);
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [step, setStep] = useState<"request" | "reset">("request");
  const [isLoading, setIsLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");
  const [error, setError] = useState("");

  const handleSendCode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSuccessMessage("");
    setIsLoading(true);
    try {
      await onSendCode(email.trim());
      setStep("reset");
      setSuccessMessage("Reset code has been sent to your email.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send reset code.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setSuccessMessage("");
    setIsLoading(true);
    try {
      await onResetPassword({ email: email.trim(), code: code.trim(), newPassword: newPassword.trim() });
      setSuccessMessage("Password was updated. You can log in now.");
      setCode("");
      setNewPassword("");
      setStep("request");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-[150] bg-black/70 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 40 }}
            className="fixed left-1/2 top-1/2 z-[160] w-[92vw] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-3xl border border-white/10 bg-zinc-950 p-6 text-white shadow-2xl"
          >
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-xl font-bold">{t.forgotPassword}</h3>
              <button type="button" onClick={onClose} className="text-sm text-zinc-400 hover:text-zinc-200">
                {t.close}
              </button>
            </div>

            {step === "request" ? (
              <form onSubmit={handleSendCode} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="forgot-email">{t.email}</Label>
                  <Input
                    id="forgot-email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    className="h-11 rounded-xl border-zinc-800 bg-zinc-900"
                    placeholder="name@example.com"
                    required
                  />
                </div>
                {error ? <p className="text-sm text-red-400">{error}</p> : null}
                {successMessage ? <p className="text-sm text-green-400">{successMessage}</p> : null}
                <Button type="submit" isLoading={isLoading} className="h-11 w-full rounded-xl bg-white text-black hover:bg-zinc-200">
                  Send reset code
                </Button>
              </form>
            ) : (
              <form onSubmit={handleResetPassword} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="forgot-code">Verification code</Label>
                  <Input
                    id="forgot-code"
                    value={code}
                    onChange={(event) => setCode(event.target.value)}
                    className="h-11 rounded-xl border-zinc-800 bg-zinc-900"
                    placeholder="6-digit code"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="forgot-password">New password</Label>
                  <Input
                    id="forgot-password"
                    type="password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    className="h-11 rounded-xl border-zinc-800 bg-zinc-900"
                    placeholder="At least 8 characters"
                    required
                  />
                </div>
                {error ? <p className="text-sm text-red-400">{error}</p> : null}
                {successMessage ? <p className="text-sm text-green-400">{successMessage}</p> : null}
                <div className="grid grid-cols-2 gap-3">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setStep("request")}
                    className="h-11 rounded-xl border-zinc-700 bg-zinc-900 text-white hover:bg-zinc-800"
                  >
                    Back
                  </Button>
                  <Button type="submit" isLoading={isLoading} className="h-11 rounded-xl bg-white text-black hover:bg-zinc-200">
                    Update password
                  </Button>
                </div>
              </form>
            )}
          </motion.div>
        </>
      ) : null}
    </AnimatePresence>
  );
}

