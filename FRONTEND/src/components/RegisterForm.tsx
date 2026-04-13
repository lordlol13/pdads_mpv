import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { motion } from "motion/react";
import { AuthFormData } from "@/src/types";
import { useLanguage } from "../context/LanguageContext";

interface RegisterFormProps {
  formData: AuthFormData;
  updateFormData: (data: Partial<AuthFormData>) => void;
  onNext: () => void;
  onToggleMode: () => void;
  direction?: number;
  key?: string;
}

export function RegisterForm({ formData, updateFormData, onNext, onToggleMode, direction = 1 }: RegisterFormProps) {
  const { t } = useLanguage();
  return (
    <motion.div
      initial={{ opacity: 0, x: direction > 0 ? 50 : -50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: direction > 0 ? -50 : 50 }}
      className="space-y-8"
    >
      <div className="space-y-2">
        <h2 className="text-3xl font-bold tracking-tight">{t.register}</h2>
        <p className="text-zinc-500">{t.alreadyHaveAccount}</p>
      </div>

      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name">{t.name}</Label>
          <Input 
            id="name" 
            value={formData.name}
            onChange={(e) => updateFormData({ name: e.target.value })}
            placeholder="John Doe" 
            className="bg-zinc-900 border-zinc-800 h-12 rounded-xl focus:ring-white"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="email">{t.email}</Label>
          <Input 
            id="email" 
            type="email" 
            value={formData.email}
            onChange={(e) => updateFormData({ email: e.target.value })}
            placeholder="name@example.com" 
            className="bg-zinc-900 border-zinc-800 h-12 rounded-xl focus:ring-white"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">{t.password}</Label>
          <Input 
            id="password" 
            type="password" 
            placeholder="••••••••" 
            className="bg-zinc-900 border-zinc-800 h-12 rounded-xl focus:ring-white"
          />
        </div>
      </div>

      <Button 
        onClick={onNext}
        className="w-full h-12 rounded-xl bg-white hover:bg-zinc-200 text-zinc-950 font-semibold shadow-lg shadow-white/5"
      >
        {t.createAccount}
      </Button>

      <div className="text-center lg:hidden">
        <p className="text-zinc-500 text-sm">
          {t.alreadyHaveAccount}
          <button 
            onClick={onToggleMode}
            className="ml-2 text-white hover:text-zinc-300 font-medium"
          >
            {t.login}
          </button>
        </p>
      </div>
    </motion.div>
  );
}
