import React from 'react';
import { cn } from '@/src/lib/utils';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, helperText, ...props }, ref) => {
    return (
      <div className="flex flex-col space-y-2 w-full">
        {label && (
          <label className="text-sm font-bold text-on-surface" htmlFor={props.id}>
            {label}
          </label>
        )}
        <div className="relative">
          <input
            ref={ref}
            className={cn(
              "w-full px-4 py-3 bg-surface-container-lowest ghost-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-container focus:border-primary-container transition-all duration-200 text-on-surface placeholder:text-on-surface/30",
              error && "border-error focus:ring-error focus:border-error",
              className
            )}
            {...props}
          />
        </div>
        {error && <p className="text-xs text-error font-medium">{error}</p>}
        {helperText && !error && (
          <p className="text-[0.6875rem] uppercase tracking-[0.05em] font-medium text-on-surface/40 pt-1">
            {helperText}
          </p>
        )}
      </div>
    );
  }
);
