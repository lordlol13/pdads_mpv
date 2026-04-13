import { useState, type FormEvent } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { motion } from "motion/react";
import { useLanguage } from "../context/LanguageContext";

interface LoginFormProps {
  onToggleMode: () => void;
  onSubmit: (payload: { identifier: string; password: string }) => Promise<void> | void;
  isLoading?: boolean;
  error?: string | null;
  defaultEmail?: string;
}

export function LoginForm({ onToggleMode, onSubmit, isLoading = false, error = null, defaultEmail = "" }: LoginFormProps) {
  const { t } = useLanguage();
  const [email, setEmail] = useState(defaultEmail);
  const [password, setPassword] = useState("");

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit({ identifier: email.trim(), password });
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
          <h2 className="text-3xl font-bold tracking-tight">{t.login}</h2>
          <p className="text-zinc-500">{t.alreadyHaveAccount}</p>
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">{t.email}</Label>
            <Input 
              id="email" 
              type="email" 
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@example.com" 
              className="bg-zinc-900 border-zinc-800 h-12 rounded-xl focus:ring-white"
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">{t.password}</Label>
              <button type="button" className="text-sm text-white hover:text-zinc-300">{t.forgotPassword}</button>
            </div>
            <Input 
              id="password" 
              type="password" 
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••••" 
              className="bg-zinc-900 border-zinc-800 h-12 rounded-xl focus:ring-white"
            />
          </div>
        </div>

        {error ? <p className="text-sm text-red-400">{error}</p> : null}

        <Button type="submit" isLoading={isLoading} className="w-full h-12 rounded-xl bg-white hover:bg-zinc-200 text-zinc-950 font-semibold shadow-lg shadow-white/5">
          {t.login}
        </Button>
      </form>

      <div className="text-center lg:hidden">
        <p className="text-zinc-500 text-sm">
          {t.dontHaveAccount}
          <button 
            type="button"
            onClick={onToggleMode}
            className="ml-2 text-white hover:text-zinc-300 font-medium"
          >
            {t.register}
          </button>
        </p>
      </div>
    </motion.div>
  );
}
