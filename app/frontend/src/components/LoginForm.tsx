import { useState, type FormEvent } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { motion } from "motion/react";
import { useLanguage } from "../context/LanguageContext";

interface LoginFormProps {
  key?: string | number;
  onToggleMode: () => void;
  onSubmit: (payload: { identifier: string; password: string }) => Promise<void> | void;
  onForgotPassword?: () => void;
  isLoading?: boolean;
  error?: string | null;
  defaultEmail?: string;
}

export function LoginForm({
  onToggleMode,
  onSubmit,
  onForgotPassword,
  isLoading = false,
  error = null,
  defaultEmail = "",
}: LoginFormProps) {
  const { t } = useLanguage();
  const [identifier, setIdentifier] = useState(defaultEmail);
  const [password, setPassword] = useState("");

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit({ identifier: identifier.trim(), password });
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="space-y-8"
    >
      <form className="space-y-8" onSubmit={handleSubmit}>
        <div className="space-y-2">
          {/* branding removed from inside the form; kept only on AuthLayout left panel */}
          <h2 className="text-xl md:text-3xl font-bold tracking-tight">{t.login}</h2>
          <p className="text-zinc-500">{t.alreadyHaveAccount}</p>
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="identifier">{(t as any).emailOrUsername ?? t.email}</Label>
            <Input
              id="identifier"
              type="text"
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder={(t as any).emailOrUsername ?? "name@example.com or username"}
              className="h-12 rounded-xl border-zinc-800 bg-zinc-900 focus:ring-white"
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">{t.password}</Label>
              <button type="button" onClick={onForgotPassword} className="text-sm text-white hover:text-zinc-300">
                {t.forgotPassword}
              </button>
            </div>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="********"
              className="h-12 rounded-xl border-zinc-800 bg-zinc-900 focus:ring-white"
            />
          </div>
        </div>

        {error ? <p className="text-sm text-red-400">{error}</p> : null}

        <Button
          type="submit"
          isLoading={isLoading}
          className="h-12 w-full rounded-xl bg-white font-semibold text-zinc-950 shadow-lg shadow-white/5 hover:bg-zinc-200"
        >
          {t.login}
        </Button>
      </form>

      <div className="text-center lg:hidden">
        <p className="text-sm text-zinc-500">
          {t.dontHaveAccount}
          <button type="button" onClick={onToggleMode} className="ml-2 font-medium text-white hover:text-zinc-300">
            {t.register}
          </button>
        </p>
      </div>
    </motion.div>
  );
}




