import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ProgressStepper } from '@/src/components/ui/ProgressStepper';
import { Button } from '@/src/components/ui/Button';
import { ShieldCheck, MailCheck, ArrowRight } from 'lucide-react';
import { motion } from 'motion/react';

export const RegisterStep2 = () => {
  const navigate = useNavigate();
  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [timer, setTimer] = useState(59);

  useEffect(() => {
    const interval = setInterval(() => {
      setTimer((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleChange = (index: number, value: string) => {
    if (value.length > 1) return;
    const newOtp = [...otp];
    newOtp[index] = value;
    setOtp(newOtp);
    
    // Auto focus next input
    if (value && index < 5) {
      const nextInput = document.getElementById(`otp-${index + 1}`);
      nextInput?.focus();
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    navigate('/register/step3');
  };

  return (
    <motion.div 
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      className="w-full max-w-[640px] space-y-12 mx-auto"
    >
      <ProgressStepper currentStep={2} totalSteps={4} stepSubtitle="Shaxsni tasdiqlash" />

      <section className="bg-surface-container-low p-1 rounded-xl">
        <div className="bg-surface-container-lowest rounded-lg p-8 md:p-12 shadow-sm space-y-8">
          <header className="space-y-3">
            <h1 className="text-[2.75rem] leading-[1.1] font-bold tracking-tight text-on-surface">Emailingizni tasdiqlang</h1>
            <p className="text-on-surface-variant text-lg">
              Biz <span className="font-semibold text-primary-container">murod.xojayev@misol.uz</span> manziliga 6 xonali kod yubordik. Davom etish uchun uni pastga kiriting.
            </p>
          </header>

          <form onSubmit={handleSubmit} className="space-y-8">
            <div className="flex justify-between gap-3 md:gap-4">
              {otp.map((digit, i) => (
                <input
                  key={i}
                  id={`otp-${i}`}
                  type="text"
                  maxLength={1}
                  value={digit}
                  onChange={(e) => handleChange(i, e.target.value)}
                  className="w-full h-16 md:h-20 text-center text-2xl font-bold rounded-lg bg-surface-container-lowest border-[1px] border-outline-variant/20 focus:border-primary-container focus:ring-0 transition-all outline-none"
                  placeholder="·"
                />
              ))}
            </div>

            <Button type="submit" className="w-full flex items-center justify-center gap-2">
              Tasdiqlash <ArrowRight size={20} />
            </Button>
          </form>

          <div className="pt-6 text-center space-y-4">
            <p className="text-on-surface-variant text-sm">
              Kod kelmadimi? 
              <button className="text-primary-container font-bold hover:underline underline-offset-4 ml-1 disabled:opacity-50" disabled={timer > 0}>
                Qayta yuborish 0:{timer.toString().padStart(2, '0')}
              </button>
            </p>
            <button 
              onClick={() => navigate('/register/step1')}
              className="text-on-surface-variant/60 text-[0.6875rem] font-bold uppercase tracking-[0.05em] hover:text-on-surface transition-colors"
            >
              Email manzilini o'zgartirish
            </button>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 pt-8 opacity-60">
        <div className="flex gap-4">
          <ShieldCheck className="text-primary-container" size={24} />
          <div className="space-y-1">
            <p className="text-sm font-bold text-on-surface">Xavfsiz tasdiqlash</p>
            <p className="text-xs text-on-surface-variant">Ma'lumotlaringiz korporativ darajadagi standartlar bilan shifrlangan.</p>
          </div>
        </div>
        <div className="flex gap-4">
          <MailCheck className="text-primary-container" size={24} />
          <div className="space-y-1">
            <p className="text-sm font-bold text-on-surface">Spamdan himoya</p>
            <p className="text-xs text-on-surface-variant">Agar emailni ko'rmasangiz, spam jildini tekshirib ko'ring.</p>
          </div>
        </div>
      </div>
    </motion.div>
  );
};
