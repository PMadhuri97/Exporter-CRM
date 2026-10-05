import type { HTMLAttributes, ReactNode } from 'react';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { BADGE_DOT_CLASSES, BADGE_TONE_CLASSES, type BadgeTone } from './styles';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  /**
   * `tint` (default): the meaning's tint with its text colour and a leading dot.
   * `outline`: no fill, for something that has not happened yet ("Awaiting
   * approval"). `solid`: white on the negative solid with a warning icon — for
   * Critical risk only (PDF §3.3), so it is the one badge that looks different.
   */
  variant?: 'tint' | 'outline' | 'solid';
  /** The leading dot; on by default for `tint`. */
  dot?: boolean;
  icon?: ReactNode;
}

/**
 * A status in words (frontend-plan §6.4): 20px tall, 4px corners, never a pill.
 * The label always says the state; the colour and the dot only repeat it.
 */
export function Badge({
  tone = 'neutral',
  variant = 'tint',
  dot = variant === 'tint',
  icon,
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex h-5 max-w-full items-center gap-1.5 whitespace-nowrap rounded px-1.5 text-caption font-semibold',
        variant === 'tint' && BADGE_TONE_CLASSES[tone],
        variant === 'outline' && 'border border-line-strong bg-surface text-ink-2',
        variant === 'solid' && 'bg-negative-solid text-white',
        className,
      )}
      data-badge-tone={tone}
      {...rest}
    >
      {variant === 'solid' && !icon && <Icon.warning size={12} weight="fill" aria-hidden />}
      {dot && variant !== 'solid' && (
        <span aria-hidden className={cn('h-1.5 w-1.5 shrink-0 rounded-full', BADGE_DOT_CLASSES[tone])} />
      )}
      {icon}
      <span className="truncate">{children}</span>
    </span>
  );
}
