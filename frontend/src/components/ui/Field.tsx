import {
  forwardRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';

import { cn } from '@/lib/cn';

/**
 * The mark after a required field's label. The one convention for "required" across the
 * CRM: a field without it is optional, so nothing says "(optional)" or "(required)" in
 * words. Hidden from screen readers, which hear the control's own `required`.
 */
export function RequiredMark() {
  return (
    <span className="ml-0.5 text-ink-3" aria-hidden>
      *
    </span>
  );
}

/**
 * The one line that explains the mark, at the top of a form that has required fields.
 * Hidden from screen readers like the mark itself: they hear each control's `required`.
 */
export function RequiredNote({ className }: { className?: string }) {
  return (
    <p className={cn('text-caption text-ink-3', className)} aria-hidden>
      * required
    </p>
  );
}

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
        {required && <RequiredMark />}
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
