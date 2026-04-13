/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState } from "react";
import { AnimatePresence } from "motion/react";
import { AuthLayout } from "./components/AuthLayout";
import { ProgressBar } from "./components/ProgressBar";
import { LoginForm } from "./components/LoginForm";
import { RegisterForm } from "./components/RegisterForm";
import { VerificationStep } from "./components/VerificationStep";
import { ProfileStep } from "./components/ProfileStep";
import { SuccessStep } from "./components/SuccessStep";
import { InteractiveSpaceBackground } from "./components/InteractiveSpaceBackground";
import { MainFeed } from "./components/MainFeed";
import { AuthStep, AuthFormData } from "./types";
import { LanguageProvider, useLanguage } from "./context/LanguageContext";

function AppContent() {
  const [isRegistering, setIsRegistering] = useState(false);
  const [step, setStep] = useState<AuthStep>(1);
  const [direction, setDirection] = useState(1); // 1 for forward, -1 for backward
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const { t } = useLanguage();
  const [formData, setFormData] = useState<AuthFormData>({
    name: "",
    email: "",
    verificationCode: [],
    interests: [],
    profession: "",
    country: "",
    city: "",
  });

  const [isTransitioning, setIsTransitioning] = useState(false);

  const updateFormData = (data: Partial<AuthFormData>) => {
    setFormData((prev) => ({ ...prev, ...data }));
  };

  const handleToggleMode = () => {
    setIsRegistering(!isRegistering);
    setStep(1);
    setDirection(1);
    setIsTransitioning(false);
  };

  const nextStep = () => {
    if (step < 4) {
      setDirection(1);
      setIsTransitioning(true);
      // Give time for progress bar to animate before switching content
      setTimeout(() => {
        setStep((prev) => (prev + 1) as AuthStep);
        setIsTransitioning(false);
      }, 600);
    } else {
      // Final transition to feed
      setIsLoggedIn(true);
    }
  };

  const prevStep = () => {
    if (step > 1) {
      setDirection(-1);
      setIsTransitioning(true);
      setTimeout(() => {
        setStep((prev) => (prev - 1) as AuthStep);
        setIsTransitioning(false);
      }, 600);
    }
  };

  const showLeftPanel = step === 1 && !isTransitioning;
  const progressStep = isTransitioning && direction === 1 ? (step + 1) as AuthStep : step;

  if (isLoggedIn) {
    return <MainFeed />;
  }

  return (
    <div className="min-h-screen relative overflow-hidden">
      <InteractiveSpaceBackground />
      
      {isLoggedIn ? (
        <MainFeed />
      ) : (
        <AuthLayout 
          showLeftPanel={showLeftPanel} 
          isRegistering={isRegistering}
          onToggleMode={handleToggleMode}
          step={step}
        >
          {isRegistering && step < 4 && <ProgressBar currentStep={progressStep} />}
          
          <div className="flex-1 flex flex-col justify-center w-full max-w-md mx-auto">
            <AnimatePresence mode="wait" custom={direction}>
              {!isRegistering ? (
                <LoginForm key="login" onToggleMode={handleToggleMode} />
              ) : step === 1 ? (
                <RegisterForm 
                  key="step1" 
                  formData={formData}
                  updateFormData={updateFormData}
                  onNext={nextStep}
                  onToggleMode={handleToggleMode}
                  direction={direction}
                />
              ) : step === 2 ? (
                <VerificationStep 
                  key="step2" 
                  email={formData.email}
                  onNext={nextStep}
                  onBack={prevStep}
                  direction={direction}
                />
              ) : step === 3 ? (
                <ProfileStep 
                  key="step3" 
                  formData={formData}
                  updateFormData={updateFormData}
                  onNext={nextStep}
                  onBack={prevStep}
                  direction={direction}
                />
              ) : (
                <SuccessStep key="step4" onComplete={() => setIsLoggedIn(true)} />
              )}
            </AnimatePresence>
          </div>
        </AuthLayout>
      )}
    </div>
  );
}

export default function App() {
  return (
    <LanguageProvider>
      <AppContent />
    </LanguageProvider>
  );
}

