import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ProgressStepper } from '@/src/components/ui/ProgressStepper';
import { Input } from '@/src/components/ui/Input';
import { Button } from '@/src/components/ui/Button';
import { Info, ArrowRight, Eye, EyeOff } from 'lucide-react';
import { motion } from 'motion/react';

export const RegisterStep1 = () => {
  const navigate = useNavigate();
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    navigate('/register/step2');
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full max-w-[640px] space-y-12 mx-auto"
    >
      <ProgressStepper currentStep={1} totalSteps={4} stepSubtitle="Shaxsiy ma'lumotlar" />

      <div className="space-y-2">
        <h1 className="text-[2.75rem] font-bold leading-tight tracking-tight text-on-surface">Sayohatni boshlang.</h1>
        <p className="text-lg text-on-surface/60 font-medium">Tahririyat profilingizni sozlash uchun asosiy ma'lumotlaringizni kiriting.</p>
      </div>

      <div className="bg-surface-container-low p-1 rounded-xl">
        <div className="bg-surface-container-lowest p-8 md:p-10 rounded-lg space-y-8">
          <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-8">
            <Input label="Ism" placeholder="Murod" required />
            <Input label="Familiya" placeholder="Xo'jayev" required />
            <Input label="Email manzili" type="email" placeholder="murod.xojayev@misol.uz" className="md:col-span-2" required />
            
            <div className="md:col-span-2 relative">
              <Input 
                label="Parol yaratish" 
                type={showPassword ? "text" : "password"} 
                placeholder="••••••••" 
                helperText="Kamida 8 ta belgi, bitta belgi bilan"
                required
              />
              <button 
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-4 top-[42px] text-on-surface/40 hover:text-primary-container transition-colors"
              >
                {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
              </button>
            </div>

            <div className="md:col-span-2 pt-4">
              <Button type="submit" className="w-full flex items-center justify-center gap-2">
                Davom etish <ArrowRight size={20} />
              </Button>
            </div>
          </form>
        </div>
      </div>

      <div className="flex items-start gap-4 p-6 bg-surface-container-low rounded-lg border-l-4 border-primary-container/30">
        <Info className="text-primary-container shrink-0" size={24} />
        <p className="text-sm text-on-surface-variant leading-relaxed">
          Biz ushbu ma'lumotlardan tahririyat tajribangizni shaxsiylashtirish va professional shaxsingizni tasdiqlash uchun foydalanamiz. Ma'lumotlaringiz shifrlangan va hech qachon roziliksiz baham ko'rilmaydi.
        </p>
      </div>
    </motion.div>
  );
};
