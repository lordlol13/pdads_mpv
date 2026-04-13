import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { motion } from "motion/react";
import { useLanguage } from "../context/LanguageContext";

interface LoginFormProps {
  onToggleMode: () => void;
  key?: string;
}

export function LoginForm({ onToggleMode }: LoginFormProps) {
  const { t } = useLanguage();
  return (
    <motion.div
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="space-y-8"
    >
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
            placeholder="name@example.com" 
            className="bg-zinc-900 border-zinc-800 h-12 rounded-xl focus:ring-white"
          />
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">{t.password}</Label>
            <button className="text-sm text-white hover:text-zinc-300">{t.forgotPassword}</button>
          </div>
          <Input 
            id="password" 
            type="password" 
            placeholder="••••••••" 
            className="bg-zinc-900 border-zinc-800 h-12 rounded-xl focus:ring-white"
          />
        </div>
      </div>

      <Button className="w-full h-12 rounded-xl bg-white hover:bg-zinc-200 text-zinc-950 font-semibold shadow-lg shadow-white/5">
        {t.login}
      </Button>

      <div className="text-center lg:hidden">
        <p className="text-zinc-500 text-sm">
          {t.dontHaveAccount}
          <button 
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
