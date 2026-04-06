import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ProgressStepper } from '@/src/components/ui/ProgressStepper';
import { Button } from '@/src/components/ui/Button';
import { ChevronLeft, ArrowRight, X, UserCheck } from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '@/src/lib/utils';

const RECOMMENDED_TAGS = ["Sport", "San'at", "Siyosat", "Fan", "Salomatlik", "Ta'lim", "Texno", "Biznes"];

export const RegisterStep3 = () => {
  const navigate = useNavigate();
  const [selectedTags, setSelectedTags] = useState(["Biznes", "Texno"]);
  const [inputValue, setInputValue] = useState('');

  const toggleTag = (tag: string) => {
    if (selectedTags.includes(tag)) {
      setSelectedTags(selectedTags.filter(t => t !== tag));
    } else {
      setSelectedTags([...selectedTags, tag]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && inputValue.trim()) {
      e.preventDefault();
      if (!selectedTags.includes(inputValue.trim())) {
        setSelectedTags([...selectedTags, inputValue.trim()]);
      }
      setInputValue('');
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    navigate('/register/success');
  };

  return (
    <motion.div 
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      className="w-full max-w-[640px] space-y-12 mx-auto"
    >
      <ProgressStepper currentStep={3} totalSteps={4} stepSubtitle="Afzalliklar va joylashuv" />

      <div className="mb-12">
        <h1 className="text-[2.75rem] font-black leading-tight tracking-tighter text-on-surface mb-4">
          Qiziqishlaringizni <br/><span className="text-primary-container">aniqlang.</span>
        </h1>
        <p className="text-[1.125rem] text-on-surface-variant leading-relaxed font-medium">
          Biz yangiliklarni sizning joylashuvingiz va qiziqishlaringiz asosida saralaymiz. Joylashuvingizni kiriting va sizga qiziq bo'lgan mavzularni tanlang.
        </p>
      </div>

      <div className="bg-surface-container-low rounded-xl p-1">
        <div className="bg-surface-container-lowest rounded-lg p-8 shadow-sm space-y-12">
          <section className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="space-y-2">
              <label className="block text-sm font-bold text-on-surface tracking-tight">
                Mamlakatni tanlang <span className="text-primary text-[10px] uppercase align-top ml-1">(majburiy)</span>
              </label>
              <select className="w-full bg-surface border border-outline-variant/30 rounded-lg px-4 py-3 text-on-surface font-medium focus:ring-2 focus:ring-primary-container focus:border-primary-container transition-all cursor-pointer outline-none">
                <option value="uz">O'zbekiston</option>
                <option value="us">AQSH</option>
                <option value="uk">Buyuk Britaniya</option>
              </select>
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-bold text-on-surface tracking-tight">
                Shaharni tanlang <span className="text-on-surface-variant/60 text-[10px] uppercase align-top ml-1 font-medium">(ixtiyoriy)</span>
              </label>
              <select className="w-full bg-surface border border-outline-variant/30 rounded-lg px-4 py-3 text-on-surface font-medium focus:ring-2 focus:ring-primary-container focus:border-primary-container transition-all cursor-pointer outline-none">
                <option value="tashkent">Toshkent</option>
                <option value="london">London</option>
                <option value="ny">Nyu-York</option>
              </select>
            </div>
          </section>

          <section className="space-y-4">
            <label className="block text-sm font-bold text-on-surface tracking-tight">Qiziqishlaringizni tanlang yoki kiriting</label>
            <div className="min-h-[56px] border border-outline-variant/30 bg-surface rounded-lg p-3 flex flex-wrap gap-2 items-center focus-within:ring-2 focus-within:ring-primary-container transition-all">
              {selectedTags.map(tag => (
                <div key={tag} className="flex items-center gap-1 bg-primary-container text-white text-[10px] font-bold shadow-sm rounded-lg px-2 py-1">
                  <span>{tag}</span>
                  <button onClick={() => toggleTag(tag)} className="hover:text-primary-fixed-dim transition-colors flex items-center ml-1">
                    <X size={12} />
                  </button>
                </div>
              ))}
              <input 
                className="flex-grow min-w-[150px] bg-transparent border-none focus:ring-0 text-sm font-medium py-1 px-0 placeholder:text-on-surface-variant/40" 
                placeholder="Yana qiziqishlar qo'shing..." 
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
              />
            </div>

            <div>
              <p className="text-[0.6875rem] text-on-surface-variant font-bold tracking-wider uppercase mb-3">Tavsiya etilgan teglar</p>
              <div className="flex flex-wrap gap-2">
                {RECOMMENDED_TAGS.map(tag => (
                  <button 
                    key={tag}
                    onClick={() => toggleTag(tag)}
                    className={cn(
                      "font-bold transition-all border border-outline-variant/10 active:scale-95 rounded-lg px-2 py-1 text-[10px]",
                      selectedTags.includes(tag) 
                        ? "bg-primary-container text-white" 
                        : "bg-surface-container-low text-on-surface hover:bg-primary-container hover:text-white"
                    )}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            </div>
          </section>
        </div>
      </div>

      <div className="mt-12 flex items-center justify-between gap-6">
        <button 
          onClick={() => navigate('/register/step2')}
          className="flex items-center gap-2 text-primary font-bold text-sm hover:underline transition-all"
        >
          <ChevronLeft size={16} /> Oldingi qadam
        </button>
        <Button onClick={handleSubmit} className="flex items-center gap-3">
          Tugatish <ArrowRight size={20} />
        </Button>
      </div>

      <div className="mt-20 flex gap-8 items-start">
        <div className="flex-shrink-0 w-16 h-16 rounded-lg bg-surface-container-low flex items-center justify-center">
          <UserCheck className="text-primary-container" size={32} />
        </div>
        <div>
          <h3 className="text-lg font-black tracking-tight mb-2">Maxfiylik va shaxsiylashtirish</h3>
          <p className="text-sm text-on-surface-variant leading-relaxed">
            Sizning qiziqishlaringiz profili shifrlangan va faqat tasmangizni ustuvorlashtirish uchun ishlatiladi. Ushbu afzalliklarni istalgan vaqtda hisob sozlamalarida o'zgartirishingiz mumkin.
          </p>
        </div>
      </div>
    </motion.div>
  );
};
