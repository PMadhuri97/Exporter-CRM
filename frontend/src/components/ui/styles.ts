/**
 * Class recipes shared by the UI primitives, and usable on their own where a
 * primitive cannot be — a router `<Link>` styled as a button, for instance.
 *
 * Kept apart from the components so each component file exports only
 * components (react-refresh's rule).
 */

import { cn } from '@/lib/cn';

/**
 * `primary` is ink — the one filled button on a surface. `secondary` is a
 * hairline outline, `quiet` text only. `destructive` is an outline in the
 * negative colour: something that cannot be undone asks to be read, not hit.
 * There is no brand variant: the chrome has no hue (frontend-plan §5.1).
 */
export type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'destructive';
export type ButtonSize = 'sm' | 'md';

const BUTTON_BASE =
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium ' +
  'transition-colors duration-quick ease-enter ' +
  'disabled:pointer-events-none disabled:opacity-45';

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  // `ink` inverts with the theme, so its text is `paper`, never `white`.
  primary: 'bg-ink text-paper hover:bg-ink/85 active:bg-ink/75',
  secondary: 'border border-line-strong bg-surface text-ink hover:border-ink-3 hover:bg-sunken',
  quiet: 'text-ink-2 hover:bg-sunken hover:text-ink',
  destructive:
    'border border-negative/40 bg-surface text-negative hover:border-negative hover:bg-negative-tint',
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-secondary',
  md: 'h-9 px-4 text-body',
};

export function buttonClasses({
  variant = 'secondary',
  size = 'md',
  className,
}: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}): string {
  return cn(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className);
}

/**
 * The tones a tag can take: one per meaning (frontend-plan §5.2), plus `ink`
 * for an emphasis that is not a state (a primary contact, "Required").
 */
export type TagTone = 'idle' | 'positive' | 'negative' | 'attention' | 'progress' | 'ink';

export const TAG_TONE_CLASSES: Record<TagTone, string> = {
  idle: 'bg-sunken text-ink-2',
  positive: 'bg-positive-tint text-positive',
  negative: 'bg-negative-tint text-negative',
  attention: 'bg-attention-tint text-attention',
  progress: 'bg-progress-tint text-progress',
  ink: 'border border-line-strong text-ink',
};

/** The dot a `Tag` may lead with — the meaning's solid, so it reads at a glance. */
export const TAG_DOT_CLASSES: Record<TagTone, string> = {
  idle: 'bg-idle-solid',
  positive: 'bg-positive-solid',
  negative: 'bg-negative-solid',
  attention: 'bg-attention-solid',
  progress: 'bg-progress-solid',
  ink: 'bg-ink',
};

/** A text link in body copy: ink with a quiet underline that firms on hover. */
export const LINK_CLASSES =
  'font-medium text-ink underline decoration-line-strong underline-offset-[3px] transition-colors duration-quick hover:decoration-ink';
