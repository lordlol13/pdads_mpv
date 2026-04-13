import { useState, type FormEvent } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { motion } from "motion/react";

import { AuthFormData } from "@/src/types";
import { useLanguage } from "../context/LanguageContext";

interface RegisterFormProps {
  key?: string | number;
  formData: AuthFormData;
  updateFormData: (data: Partial<AuthFormData>) => void;
  onSubmit: (payload: { name: string; email: string; password: string }) => Promise<void> | void;
  onToggleMode: () => void;
  direction?: number;
  isLoading?: boolean;
  error?: string | null;
}

export function RegisterForm({
  formData,
  updateFormData,
  onSubmit,
  onToggleMode,
  direction = 1,
  isLoading = false,
  error = null,
}: RegisterFormProps) {
  const { t } = useLanguage();
  const [password, setPassword] = useState(formData.password);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await onSubmit({
      name: formData.name.trim(),
      email: formData.email.trim(),
      password,
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: direction > 0 ? 50 : -50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: direction > 0 ? -50 : 50 }}
      className="space-y-8"
    >
      <form className="space-y-8" onSubmit={handleSubmit}>
        <div className="space-y-2">
          <div className="flex items-center gap-2 pb-2">
            <img src="/PR.ADS.png" alt="PR.ADS" className="h-8 w-8 rounded-md object-cover" />
            <span className="text-sm font-semibold text-zinc-300">PR.ADS</span>
          </div>
          <h2 className="text-3xl font-bold tracking-tight">{t.register}</h2>
          <p className="text-zinc-500">{t.alreadyHaveAccount}</p>
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">{t.name}</Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(event) => updateFormData({ name: event.target.value })}
              placeholder="John Doe"
              className="h-12 rounded-xl border-zinc-800 bg-zinc-900 focus:ring-white"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">{t.email}</Label>
            <Input
              id="email"
              type="email"
              value={formData.email}
              onChange={(event) => updateFormData({ email: event.target.value })}
              placeholder="name@example.com"
              className="h-12 rounded-xl border-zinc-800 bg-zinc-900 focus:ring-white"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">{t.password}</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                updateFormData({ password: event.target.value });
              }}
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
          {t.createAccount}
        </Button>
      </form>

      <div className="text-center lg:hidden">
        <p className="text-sm text-zinc-500">
          {t.alreadyHaveAccount}
          <button type="button" onClick={onToggleMode} className="ml-2 font-medium text-white hover:text-zinc-300">
            {t.login}
          </button>
        </p>
      </div>
    </motion.div>
  );
}




