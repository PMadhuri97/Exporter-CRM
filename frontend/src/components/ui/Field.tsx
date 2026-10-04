import {
  forwardRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';

import { cn } from '@/lib/cn';

/** A form field's label, control, hint and error, laid out once. */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  className,
  children,
}: {
  label: ReactNode;
  htmlFor: string;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="mb-1 block text-caption font-medium text-ink-2">
        {label}
        {required && (
          <span className="ml-0.5 text-ink-3" aria-hidden>
            *
          </span>
        )}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-caption text-ink-3">{hint}</p>}
      {error && (
        <p className="mt-1 text-caption text-negative" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cn('input', className)} {...rest} />;
  },
);

/** A native select — keyboard, screen-reader and test behaviour for free. */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, ...rest }, ref) {
    return <select ref={ref} className={cn('input pr-8', className)} {...rest} />;
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn('input', className)} {...rest} />;
});

/** A failed form submission's message, shown above the buttons. */
export function FormError({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border-l-2 border-negative bg-negative-tint px-3 py-2 text-secondary text-negative"
    >
      {children}
    </div>
  );
}
