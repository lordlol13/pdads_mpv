import { cn } from '@/src/lib/utils';

interface ProgressStepperProps {
  currentStep: number;
  totalSteps: number;
  stepTitle?: string;
  stepSubtitle?: string;
}

export const ProgressStepper = ({ currentStep, totalSteps, stepTitle, stepSubtitle }: ProgressStepperProps) => {
  return (
    <div className="space-y-6 w-full">
      <div className="flex gap-3 h-2 w-full">
        {Array.from({ length: totalSteps }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "flex-1 rounded-full transition-all duration-500",
              i < currentStep ? "bg-primary-container" : "bg-surface-container-highest"
            )}
          />
        ))}
      </div>
      <div className="flex justify-between items-end">
        <div>
          <p className="text-[0.6875rem] uppercase tracking-[0.1em] font-bold text-primary-container">
            Step {currentStep} of {totalSteps}
          </p>
          {stepSubtitle && <p className="text-xs font-semibold text-on-surface/40">{stepSubtitle}</p>}
        </div>
        <span className="text-lg font-black tracking-tighter text-on-surface opacity-20">
          The Editorial Flow
        </span>
      </div>
    </div>
  );
};
