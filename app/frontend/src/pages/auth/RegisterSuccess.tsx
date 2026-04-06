import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/src/components/ui/Button';
import { CheckCircle, ShieldCheck, Star } from 'lucide-react';
import { motion } from 'motion/react';

export const RegisterSuccess = () => {
  const navigate = useNavigate();

  useEffect(() => {
    const timeout = setTimeout(() => {
      navigate('/feed');
    }, 5000);
    return () => clearTimeout(timeout);
  }, [navigate]);

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="w-full max-w-[640px] space-y-12 mx-auto text-center"
    >
      <div className="space-y-6">
        <div className="flex gap-2 h-1.5 w-full">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="flex-1 bg-primary-container rounded-full" />
          ))}
        </div>
        <div className="text-left">
          <p className="text-[0.6875rem] uppercase tracking-widest font-bold text-primary-container">Ro'yxatdan o'tish tugallandi</p>
          <p className="text-xs font-semibold text-on-surface/40">Barcha bosqichlar yakunlandi</p>
        </div>
      </div>

      <div className="relative inline-flex items-center justify-center">
        <div className="absolute inset-0 bg-primary-container/10 blur-2xl rounded-full" />
        <div className="relative bg-surface-container-lowest h-32 w-32 rounded-full flex items-center justify-center shadow-xl">
          <CheckCircle className="text-primary-container" size={64} fill="currentColor" fillOpacity={0.1} />
        </div>
      </div>

      <div className="space-y-4">
        <h1 className="text-[3.5rem] font-black leading-none tracking-tighter text-on-surface">
          Tabriklaymiz!
        </h1>
        <p className="text-lg text-on-surface-variant font-medium max-w-md mx-auto">
          Ro'yxatdan o'tish muvaffaqiyatli yakunlandi. Raqamli tahririyat tajribasining kelajagiga xush kelibsiz.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-left">
        <div className="bg-surface-container-low p-1 rounded-xl">
          <div className="bg-surface-container-lowest p-6 rounded-lg h-full flex flex-col justify-between shadow-sm">
            <div className="flex justify-between items-start">
              <ShieldCheck className="text-primary-container" size={24} />
              <span className="bg-green-100 text-green-700 text-[10px] font-bold px-2 py-0.5 rounded-full uppercase">Faol</span>
            </div>
            <div className="mt-4">
              <p className="text-[0.6875rem] font-bold uppercase tracking-widest text-on-surface-variant mb-1">Profil holati</p>
              <p className="text-on-surface font-bold text-lg">Tasdiqlangan</p>
            </div>
          </div>
        </div>
        <div className="bg-surface-container-low p-1 rounded-xl">
          <div className="bg-surface-container-lowest p-6 rounded-lg h-full flex flex-col justify-between shadow-sm">
            <div className="flex justify-between items-start">
              <Star className="text-primary-container" size={24} />
              <div className="h-6 w-6 bg-primary-container rounded flex items-center justify-center text-white text-[10px] font-black">P</div>
            </div>
            <div className="mt-4">
              <p className="text-[0.6875rem] font-bold uppercase tracking-widest text-on-surface-variant mb-1">Kirish darajasi</p>
              <p className="text-on-surface font-bold text-lg">Premium tahririyat</p>
            </div>
          </div>
        </div>
      </div>

      <div className="pt-8 space-y-8">
        <p className="text-lg font-semibold text-on-surface">Tasmangizga yo'naltirilmoqda...</p>
        <p className="text-[0.6875rem] font-bold uppercase tracking-[0.2em] text-on-surface-variant animate-pulse">
          5 soniyadan so'ng avtomatik yo'naltirish...
        </p>
        <Button onClick={() => navigate('/feed')} variant="secondary">Hozir tasmaga o'tish</Button>
      </div>
    </motion.div>
  );
};
