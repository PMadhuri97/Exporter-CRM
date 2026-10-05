/**
 * Class recipes shared by the UI primitives, and usable on their own where a
 * primitive cannot be — a router `<Link>` styled as a button, for instance.
 *
 * Kept apart from the components so each component file exports only
 * components (react-refresh's rule).
 */

import { cn } from '@/lib/cn';

/**
 * The four buttons of an enterprise app (frontend-plan §6.15). `primary` is the
 * brand blue — one per view. `secondary` is white with a grey border, `subtle`
 * text only, and `destructive` a solid negative fill for what cannot be undone.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'subtle' | 'destructive';
/** `md` is 32px, the default control height; `sm` is 28px, for inside a card. */
export type ButtonSize = 'sm' | 'md';

const BUTTON_BASE =
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded font-semibold ' +
  'transition-colors duration-quick ease-enter ' +
  'disabled:pointer-events-none disabled:opacity-45';

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-accent-solid text-white hover:bg-accent-solid-hover active:bg-accent-solid-hover',
  secondary: 'border border-line-strong bg-surface text-ink hover:bg-sunken active:bg-line',
  subtle: 'text-ink-2 hover:bg-sunken hover:text-ink active:bg-line',
  destructive: 'bg-negative-solid text-white hover:bg-negative-solid/90 active:bg-negative-solid/80',
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: 'h-7 px-2.5 text-secondary',
  md: 'h-8 px-3 text-body',
};

export function buttonClasses({
  variant = 'secondary',
  size = 'md',
  className,
}: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}): string {
  return cn(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className);
}

/**
 * A status badge's tone: one per meaning (frontend-plan §5.2, §6.4). `neutral` is a
 * state with nothing to say yet ("Not started"); the old `idle` name is kept as an
 * alias, and `ink` is an emphasis that is not a state (a primary contact,
 * "Required"), drawn as an outline.
 */
export type BadgeTone = 'neutral' | 'positive' | 'negative' | 'attention' | 'progress';
export type TagTone = BadgeTone | 'idle' | 'ink';

export const BADGE_TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: 'bg-idle-tint text-idle',
  positive: 'bg-positive-tint text-positive',
  negative: 'bg-negative-tint text-negative',
  attention: 'bg-attention-tint text-attention',
  progress: 'bg-progress-tint text-progress',
};

/** The 6px dot a badge leads with — the meaning's solid colour. */
export const BADGE_DOT_CLASSES: Record<BadgeTone, string> = {
  neutral: 'bg-idle-solid',
  positive: 'bg-positive-solid',
  negative: 'bg-negative-solid',
  attention: 'bg-attention-solid',
  progress: 'bg-progress-solid',
};

/** A text link: the brand blue, underlined on hover (§5.1 — blue marks what acts). */
export const LINK_CLASSES =
  'font-semibold text-accent underline-offset-2 transition-colors duration-quick hover:underline';

/** A dropdown menu's surface and its items (Radix dropdown-menu), shared by the
 * record header's *More*, the app header's *New* and the user menu. */
export const MENU_CONTENT =
  'z-50 min-w-48 rounded-xl border border-line bg-raised p-1 text-ink shadow-float outline-none animate-float-in';

export const MENU_ITEM =
  'flex h-8 cursor-default select-none items-center gap-2.5 rounded px-2.5 text-body text-ink outline-none data-[disabled]:opacity-45 data-[highlighted]:bg-sunken';
