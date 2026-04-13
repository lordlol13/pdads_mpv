/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useEffect, useState } from "react";
import { AnimatePresence } from "motion/react";
import { authService } from "./api/services";
import { AuthLayout } from "./components/AuthLayout";
import { ProgressBar } from "./components/ProgressBar";
import { LoginForm } from "./components/LoginForm";
import { RegisterForm } from "./components/RegisterForm";
import { VerificationStep } from "./components/VerificationStep";
import { ProfileStep } from "./components/ProfileStep";
import { SuccessStep } from "./components/SuccessStep";
import { InteractiveSpaceBackground } from "./components/InteractiveSpaceBackground";
import { BackendMainFeed } from "./components/BackendMainFeed";
import { AuthFormData, AuthStep, UserPublic } from "./types";
import { LanguageProvider, useLanguage } from "./context/LanguageContext";
import { clearAuthToken, getAuthToken, setAuthToken } from "./api/client";

const PENDING_VERIFICATION_KEY = "pending_verification";

const INITIAL_FORM_DATA: AuthFormData = {
  name: "",
  email: "",
  password: "",
  verificationCode: [],
  interests: [],
  customInterests: [],
  profession: "",
  country: "",
  countryCode: "",
  countryName: "",
  city: "",
  regionCode: "",
  verificationId: "",
};

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
}

function AppContent() {
  const [isRegistering, setIsRegistering] = useState(false);
  const [step, setStep] = useState<AuthStep>(1);
  const [direction, setDirection] = useState(1); // 1 for forward, -1 for backward
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [currentUser, setCurrentUser] = useState<UserPublic | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [verificationError, setVerificationError] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const { t } = useLanguage();

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
      const oauthToken = hashParams.get("access_token");
      const oauthError = hashParams.get("oauth_error");

      if (oauthToken) {
        setAuthToken(oauthToken);
      }
      if (oauthError && !cancelled) {
        setLoginError(decodeURIComponent(oauthError));
      }
      if (oauthToken || oauthError) {
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
      }

      const token = getAuthToken();
      if (!token) {
        setIsBootstrapping(false);
        return;
      }

      try {
        const me = await authService.getMe();
        if (!cancelled) {
          setCurrentUser(me);
          setIsLoggedIn(true);
        }
      } catch {
        clearAuthToken();
      } finally {
        if (!cancelled) {
          setIsBootstrapping(false);
        }
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
    };
  }, []);

  const [formData, setFormData] = useState<AuthFormData>(INITIAL_FORM_DATA);

  useEffect(() => {
    if (isLoggedIn) {
      return;
    }

    const raw = localStorage.getItem(PENDING_VERIFICATION_KEY);
    if (!raw) {
      return;
    }

    try {
      const pending = JSON.parse(raw) as {
        verificationId?: string;
        email?: string;
        name?: string;
        password?: string;
      };

      if (!pending.verificationId) {
        return;
      }

      setFormData((prev) => ({
        ...prev,
        verificationId: pending.verificationId ?? "",
        email: pending.email ?? "",
        name: pending.name ?? "",
        password: pending.password ?? "",
      }));
      setIsRegistering(true);
      setStep(2);
      setDirection(1);
    } catch {
      localStorage.removeItem(PENDING_VERIFICATION_KEY);
    }
  }, [isLoggedIn]);

  const updateFormData = (data: Partial<AuthFormData>) => {
    setFormData((prev) => ({ ...prev, ...data }));
  };

  const handleToggleMode = () => {
    setIsRegistering(!isRegistering);
    setStep(1);
    setDirection(1);
    setLoginError(null);
    setRegisterError(null);
    setVerificationError(null);
    setProfileError(null);
    localStorage.removeItem(PENDING_VERIFICATION_KEY);
  };

  const nextStep = () => {
    if (step < 4) {
      setDirection(1);
      setStep((prev) => (prev + 1) as AuthStep);
    }
  };

  const prevStep = () => {
    if (step > 1) {
      setDirection(-1);
      setStep((prev) => (prev - 1) as AuthStep);
    }
  };

  const showLeftPanel = step === 1;
  const progressStep = step;

  const handleLogin = async ({ identifier, password }: { identifier: string; password: string }) => {
    setIsSubmitting(true);
    setLoginError(null);
    try {
      await authService.login({ identifier, password });
      const me = await authService.getMe();
      setCurrentUser(me);
      setIsLoggedIn(true);
    } catch (error) {
      setLoginError(getErrorMessage(error, "Unable to sign in"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRegisterStart = async ({ name, email, password }: { name: string; email: string; password: string }) => {
    setIsSubmitting(true);
    setRegisterError(null);
    try {
      updateFormData({ name, email, password });
      const result = await authService.registerStart({ username: name, email, password });
      updateFormData({ verificationId: result.verification_id });
      localStorage.setItem(
        PENDING_VERIFICATION_KEY,
        JSON.stringify({
          verificationId: result.verification_id,
          email,
          name,
          password,
        })
      );
      setIsRegistering(true);
      setDirection(1);
      setStep(2);
    } catch (error) {
      setRegisterError(getErrorMessage(error, "Unable to start registration"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleVerifyCode = async (code: string) => {
    setIsSubmitting(true);
    setVerificationError(null);
    try {
      const verificationId = formData.verificationId || (() => {
        const raw = localStorage.getItem(PENDING_VERIFICATION_KEY);
        if (!raw) return "";
        try {
          return (JSON.parse(raw) as { verificationId?: string }).verificationId ?? "";
        } catch {
          return "";
        }
      })();

      if (!verificationId) {
        setStep(1);
        throw new Error("Verification session not found. Please register again.");
      }

      await authService.verifyCode({ verification_id: verificationId, code });
      setFormData((prev) => ({ ...prev, verificationId }));
      setDirection(1);
      setStep(3);
    } catch (error) {
      const message = getErrorMessage(error, "Unable to verify code");
      if (message.toLowerCase().includes("verification session not found")) {
        localStorage.removeItem(PENDING_VERIFICATION_KEY);
        setFormData((prev) => ({ ...prev, verificationId: "" }));
        setDirection(-1);
        setStep(1);
        setVerificationError("Сессия верификации истекла. Начните регистрацию заново.");
      } else {
        setVerificationError(message);
      }
      throw error;
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCompleteProfile = async () => {
    setIsSubmitting(true);
    setProfileError(null);
    try {
      await authService.registerComplete({
        verification_id: formData.verificationId,
        interests: formData.interests,
        custom_interests: formData.customInterests,
        profession: formData.profession || null,
        country_code: formData.countryCode || null,
        country_name: formData.countryName || null,
        city: formData.city || null,
        region_code: formData.regionCode || null,
      });

      await authService.login({ identifier: formData.email, password: formData.password });
      const me = await authService.getMe();
      localStorage.removeItem(PENDING_VERIFICATION_KEY);
      setCurrentUser(me);
      setDirection(1);
      setStep(4);
    } catch (error) {
      setProfileError(getErrorMessage(error, "Unable to complete profile"));
      throw error;
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSuccessComplete = () => {
    setIsLoggedIn(true);
    setIsRegistering(false);
  };

  const handleLogout = () => {
    authService.logout();
    setCurrentUser(null);
    setIsLoggedIn(false);
    setIsRegistering(false);
    setStep(1);
    setDirection(1);
    setFormData(INITIAL_FORM_DATA);
    setLoginError(null);
    setRegisterError(null);
    setVerificationError(null);
    setProfileError(null);
    localStorage.removeItem(PENDING_VERIFICATION_KEY);
  };

  if (isBootstrapping) {
    return (
      <div className="min-h-screen relative overflow-hidden bg-black text-white">
        <InteractiveSpaceBackground />
        <div className="relative z-10 flex min-h-screen items-center justify-center px-4">
          <div className="rounded-3xl border border-white/10 bg-white/5 px-6 py-4 text-sm text-white/80 backdrop-blur">
            {t.loading}
          </div>
        </div>
      </div>
    );
  }

  if (isLoggedIn) {
    return <BackendMainFeed currentUser={currentUser} onLogout={handleLogout} />;
  }

  return (
    <div className="min-h-screen relative overflow-hidden">
      <InteractiveSpaceBackground />

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
              <LoginForm
                key="login"
                onToggleMode={handleToggleMode}
                onSubmit={handleLogin}
                isLoading={isSubmitting}
                error={loginError}
                defaultEmail={formData.email}
              />
            ) : step === 1 ? (
              <RegisterForm
                key="step1"
                formData={formData}
                updateFormData={updateFormData}
                onSubmit={handleRegisterStart}
                onToggleMode={handleToggleMode}
                direction={direction}
                isLoading={isSubmitting}
                error={registerError}
              />
            ) : step === 2 ? (
              <VerificationStep
                key="step2"
                email={formData.email}
                verificationId={formData.verificationId}
                onVerify={handleVerifyCode}
                onBack={prevStep}
                direction={direction}
                isLoading={isSubmitting}
                error={verificationError}
              />
            ) : step === 3 ? (
              <ProfileStep
                key="step3"
                formData={formData}
                updateFormData={updateFormData}
                onSubmitProfile={handleCompleteProfile}
                onBack={prevStep}
                direction={direction}
                isLoading={isSubmitting}
                error={profileError}
              />
            ) : (
              <SuccessStep key="step4" onComplete={handleSuccessComplete} />
            )}
          </AnimatePresence>
        </div>
      </AuthLayout>
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

