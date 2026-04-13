import { useState, useRef, useEffect, useMemo } from "react";
import { motion, useAnimation, AnimatePresence } from "motion/react";
import { Search, Plus, X, MapPin, Briefcase, Globe, ChevronDown, ChevronLeft } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AuthFormData, INTERESTS_LIST } from "@/src/types";
import { Country, City } from "country-state-city";
import { useLanguage } from "../context/LanguageContext";

interface ProfileStepProps {
  formData: AuthFormData;
  updateFormData: (data: Partial<AuthFormData>) => void;
  onSubmitProfile: () => Promise<void> | void;
  onBack?: () => void;
  direction?: number;
  isLoading?: boolean;
  error?: string | null;
}

export function ProfileStep({ formData, updateFormData, onSubmitProfile, onBack, direction = 1, isLoading = false, error = null }: ProfileStepProps) {
  const { t } = useLanguage();
  const [search, setSearch] = useState("");
  const [countrySearch, setCountrySearch] = useState("");
  const [citySearch, setCitySearch] = useState("");
  const [showCountryList, setShowCountryList] = useState(false);
  const [showCityList, setShowCityList] = useState(false);
  const [showCountryError, setShowCountryError] = useState(false);
  const [showCityError, setShowCityError] = useState(false);
  const countryControls = useAnimation();
  
  const countryRef = useRef<HTMLDivElement>(null);
  const cityRef = useRef<HTMLDivElement>(null);

  const allCountries = useMemo(() => Country.getAllCountries(), []);
  
  const filteredCountries = useMemo(() => {
    if (!countrySearch) return allCountries.slice(0, 50); // Show first 50 by default
    return allCountries.filter(c => 
      c.name.toLowerCase().includes(countrySearch.toLowerCase())
    ).slice(0, 50);
  }, [allCountries, countrySearch]);

  const citiesOfSelectedCountry = useMemo(() => {
    if (!formData.country) return [];
    return City.getCitiesOfCountry(formData.country) || [];
  }, [formData.country]);

  const filteredCities = useMemo(() => {
    if (!citySearch) return citiesOfSelectedCountry.slice(0, 50);
    return citiesOfSelectedCountry.filter(city => 
      city.name.toLowerCase().includes(citySearch.toLowerCase())
    ).slice(0, 50);
  }, [citiesOfSelectedCountry, citySearch]);

  const filteredInterests = INTERESTS_LIST.filter(i => 
    i.toLowerCase().includes(search.toLowerCase()) && !formData.interests.includes(i)
  );

  const addInterest = (interest: string) => {
    const nextInterests = [...formData.interests, interest];
    const nextCustomInterests = INTERESTS_LIST.includes(interest)
      ? formData.customInterests
      : [...formData.customInterests, interest];
    updateFormData({ interests: nextInterests, customInterests: nextCustomInterests });
    setSearch("");
  };

  const removeInterest = (interest: string) => {
    updateFormData({
      interests: formData.interests.filter(i => i !== interest),
      customInterests: formData.customInterests.filter(i => i !== interest),
    });
  };

  const handleNext = async () => {
    if (!formData.country) {
      setShowCountryError(true);
      await countryControls.start({
        x: [0, -10, 10, -10, 10, 0],
        transition: { duration: 0.4 }
      });
      return;
    }
    if (!formData.city.trim()) {
      setShowCityError(true);
      return;
    }
    await onSubmitProfile();
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (countryRef.current && !countryRef.current.contains(event.target as Node)) {
        setShowCountryList(false);
      }
      if (cityRef.current && !cityRef.current.contains(event.target as Node)) {
        setShowCityList(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const selectedCountryName = useMemo(() => {
    if (!formData.country) return "";
    return Country.getCountryByCode(formData.country)?.name || "";
  }, [formData.country]);

  return (
    <motion.div
      initial={{ opacity: 0, x: direction > 0 ? 50 : -50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: direction > 0 ? -50 : 50 }}
      className="space-y-8 relative"
    >
      <div className="space-y-2">
        <h2 className="text-3xl font-bold tracking-tight">{t.profile}</h2>
        <p className="text-zinc-500">{t.alreadyHaveAccount}</p>
      </div>

      <div className="space-y-6">
        {/* Interests Multi-select */}
        <div className="space-y-3">
          <Label>{t.interests}</Label>
          <div className="relative">
            <div className="flex flex-wrap gap-2 p-2 min-h-[48px] bg-zinc-900 border border-zinc-800 rounded-xl focus-within:border-white transition-all">
              <AnimatePresence>
                {formData.interests.map(interest => (
                  <motion.div
                    key={interest}
                    initial={{ scale: 0.8, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.8, opacity: 0 }}
                  >
                    <Badge variant="secondary" className="bg-white/10 text-white border-white/20 py-1 px-2 flex items-center gap-1">
                      {interest}
                      <button onClick={() => removeInterest(interest)} className="hover:text-zinc-300">
                        <X className="w-3 h-3" />
                      </button>
                    </Badge>
                  </motion.div>
                ))}
              </AnimatePresence>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={formData.interests.length === 0 ? t.searchPlaceholder : ""}
                className="flex-1 bg-transparent border-none outline-none text-sm min-w-[120px] py-1"
              />
            </div>

            {search && (
              <div className="absolute top-full left-0 w-full mt-2 bg-zinc-900 border border-zinc-800 rounded-xl shadow-2xl z-20 overflow-hidden">
                {filteredInterests.map(interest => (
                  <button
                    key={interest}
                    onClick={() => addInterest(interest)}
                    className="w-full text-left px-4 py-2 hover:bg-zinc-800 text-sm transition-colors"
                  >
                    {interest}
                  </button>
                ))}
                {search && !INTERESTS_LIST.includes(search) && (
                  <button
                    onClick={() => addInterest(search)}
                    className="w-full text-left px-4 py-2 hover:bg-zinc-800 text-sm text-white flex items-center gap-2"
                  >
                    <Plus className="w-4 h-4" />
                    Add "{search}"
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Profession */}
        <div className="space-y-2">
          <Label htmlFor="profession">{t.profession}</Label>
          <div className="relative">
            <Briefcase className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
            <Input 
              id="profession"
              value={formData.profession}
              onChange={(e) => updateFormData({ profession: e.target.value })}
              placeholder="e.g. Software Engineer"
              className="bg-zinc-900 border-zinc-800 h-12 pl-10 rounded-xl focus:ring-white"
            />
          </div>
        </div>

        {/* Country & City Searchable */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2" ref={countryRef}>
            <Label className={showCountryError ? "text-red-500" : ""}>{t.country}</Label>
            <motion.div animate={countryControls} className="relative">
              <Globe className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 z-10" />
              <Input
                value={countrySearch || selectedCountryName}
                onChange={(e) => {
                  setCountrySearch(e.target.value);
                  setShowCountryList(true);
                  if (!e.target.value) updateFormData({ country: "" });
                }}
                onFocus={() => setShowCountryList(true)}
                placeholder={t.searchPlaceholder}
                className={`bg-zinc-900 h-12 pl-10 pr-10 rounded-xl transition-colors ${showCountryError ? "border-red-500" : "border-zinc-800"}`}
              />
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 pointer-events-none" />
              
              <AnimatePresence>
                {showCountryList && (
                  <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="absolute top-full left-0 w-full mt-2 bg-zinc-900 border border-zinc-800 rounded-xl shadow-2xl z-20 max-h-48 overflow-y-auto"
                  >
                    {filteredCountries.map(c => (
                      <button
                        key={c.isoCode}
                        onClick={() => {
                          updateFormData({
                            country: c.isoCode,
                            countryCode: c.isoCode,
                            countryName: c.name,
                            city: "",
                            regionCode: "",
                          });
                          setCountrySearch(c.name);
                          setCitySearch("");
                          setShowCountryList(false);
                          setShowCountryError(false);
                        }}
                        className="w-full text-left px-4 py-2 hover:bg-zinc-800 text-sm transition-colors"
                      >
                        {c.flag} {c.name}
                      </button>
                    ))}
                    {filteredCountries.length === 0 && (
                      <div className="px-4 py-2 text-sm text-zinc-500 italic">No countries found</div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          </div>

          <div className="space-y-2" ref={cityRef}>
            <Label htmlFor="city">{t.city}</Label>
            <div className="relative">
              <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 z-10" />
              <Input 
                id="city"
                value={citySearch || formData.city}
                onChange={(e) => {
                  setCitySearch(e.target.value);
                  setShowCityList(true);
                  updateFormData({ city: e.target.value });
                }}
                onFocus={() => setShowCityList(true)}
                disabled={!formData.country}
                placeholder={formData.country ? t.searchPlaceholder : t.country}
                className="bg-zinc-900 border-zinc-800 h-12 pl-10 rounded-xl focus:ring-white disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <AnimatePresence>
                {showCityList && formData.country && (
                  <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="absolute top-full left-0 w-full mt-2 bg-zinc-900 border border-zinc-800 rounded-xl shadow-2xl z-20 max-h-48 overflow-y-auto"
                  >
                    {filteredCities.map(city => (
                      <button
                        key={`${city.name}-${city.latitude}-${city.longitude}`}
                        onClick={() => {
                          updateFormData({ city: city.name, regionCode: city.stateCode || "" });
                          setCitySearch(city.name);
                          setShowCityList(false);
                          setShowCityError(false);
                        }}
                        className="w-full text-left px-4 py-2 hover:bg-zinc-800 text-sm transition-colors"
                      >
                        {city.name}
                      </button>
                    ))}
                    {filteredCities.length === 0 && (
                      <div className="px-4 py-2 text-sm text-zinc-500 italic">No cities found</div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </div>

      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <Button 
        type="button"
        onClick={handleNext}
        isLoading={isLoading}
        className="w-full h-12 rounded-xl bg-white hover:bg-zinc-200 text-zinc-950 font-semibold shadow-lg shadow-white/5"
      >
        {t.completeProfile}
      </Button>
    </motion.div>
  );
}
