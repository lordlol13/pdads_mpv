import React from 'react';
import { cn } from '@/src/lib/utils';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', isLoading, children, ...props }, ref) => {
    const variants = {
      primary: "editorial-gradient text-white shadow-xl shadow-primary-container/10 hover:opacity-90 active:scale-[0.98]",
      secondary: "bg-surface-container-low text-on-surface hover:bg-surface-container-high",
      ghost: "bg-transparent text-primary hover:underline",
    };

    const sizes = {
      sm: "px-3 py-1.5 text-xs font-bold",
      md: "px-8 py-4 text-lg font-bold",
      lg: "px-10 py-5 text-xl font-bold",
    };

    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center rounded-lg transition-all duration-200 disabled:opacity-50 disabled:pointer-events-none",
          variants[variant],
          sizes[size],
          className
        )}
        disabled={isLoading}
        {...props}
      >
        {isLoading ? (
          <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : null}
        {children}
      </button>
    );
  }
);
