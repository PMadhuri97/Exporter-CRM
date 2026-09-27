import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { CHIP_TONE_CLASSES, type ChipTone } from './styles';

export interface ChipProps extends HTMLAttributes<HTMLSpanElement> {
  /** A semantic tone from the status language. Ignored when `className`
   * supplies its own colours (the journey and marker chips do). */
  tone?: ChipTone;
  /** A small leading dot in the chip's colour — for lists where the chip sits
   * beside other text and needs a stronger cue than its tint. */
  dot?: boolean;
  icon?: ReactNode;
}

/** The one chip every status in the app renders through. */
export function Chip({ tone = 'neutral', dot, icon, className, children, ...rest }: ChipProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium',
        CHIP_TONE_CLASSES[tone],
        className,
      )}
      {...rest}
    >
      {dot && <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />}
      {icon}
      {children}
    </span>
  );
}
