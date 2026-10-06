import { forwardRef, type ButtonHTMLAttributes } from 'react';

import { Icon } from '@/design/icons';

import { buttonClasses, type ButtonSize, type ButtonVariant } from './styles';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows its own pending state and disables the button while a request is in
   * flight — "allowed, but not right now", the one use of disabled (§4.3). */
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading = false, className, disabled, type, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, className })}
      {...rest}
    >
      {loading && <Icon.spinner size={16} className="animate-spin" aria-hidden />}
      {children}
    </button>
  );
});
