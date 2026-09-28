/**
 * Class recipes shared by the UI primitives, and usable on their own where a
 * primitive cannot be — a router `<Link>` styled as a button, for instance.
 *
 * Kept apart from the components so each component file exports only
 * components (react-refresh's rule).
 */

import { cn } from '@/lib/cn';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'brand';
export type ButtonSize = 'sm' | 'md';

const BUTTON_BASE =
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors ' +
  'disabled:pointer-events-none disabled:opacity-50';

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  // `ink` inverts with the theme, so its text colour is `surface`, never `white`.
  primary: 'bg-ink text-surface hover:bg-ink/85',
  secondary: 'border border-border bg-surface text-ink hover:bg-surface-sunken',
  ghost: 'text-ink-muted hover:bg-surface-sunken hover:text-ink',
  danger: 'bg-status-failed text-white hover:bg-status-failed/90',
  brand: 'bg-brand-600 text-white hover:bg-brand-700 dark:text-surface',
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-9 px-4 text-sm',
};

export function buttonClasses({
  variant = 'secondary',
  size = 'md',
  className,
}: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}): string {
  return cn(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className);
}

/**
 * The semantic tones a chip can take. Each maps to one entry of the status
 * language in `tailwind.config.ts`; domain chips (journey, marker) pass their
 * own classes instead of a tone.
 */
export type ChipTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'brand';

export const CHIP_TONE_CLASSES: Record<ChipTone, string> = {
  neutral: 'bg-surface-sunken text-ink-muted',
  info: 'bg-status-info/10 text-status-info',
  success: 'bg-status-passed/10 text-status-passed',
  warning: 'bg-status-review/10 text-status-review',
  danger: 'bg-status-failed/10 text-status-failed',
  brand: 'bg-brand-50 text-brand-700',
};

/** A text link in body copy. */
export const LINK_CLASSES = 'font-medium text-brand-600 hover:underline';
