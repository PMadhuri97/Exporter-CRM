import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { TAG_DOT_CLASSES, TAG_TONE_CLASSES, type TagTone } from './styles';

export interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  /** A meaning from the status language (frontend-plan §5.2). Domain tags that
   * draw their own look (the journey, the marker) pass `className` instead. */
  tone?: TagTone;
  /** A leading dot in the meaning's solid colour — for a list where the tag sits
   * beside other text and needs a stronger cue than its tint. */
  dot?: boolean;
  icon?: ReactNode;
}

/**
 * The one small label every state in the app renders through: 4px corners, a
 * tint and its text colour, never a pill (§5.4). Colour is never the only cue —
 * the words say the state, and the dot or icon only repeats it.
 */
export function Tag({ tone = 'idle', dot, icon, className, children, ...rest }: TagProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-caption font-medium',
        TAG_TONE_CLASSES[tone],
        className,
      )}
      {...rest}
    >
      {dot && (
        <span aria-hidden className={cn('h-1.5 w-1.5 shrink-0 rounded-full', TAG_DOT_CLASSES[tone])} />
      )}
      {icon}
      {children}
    </span>
  );
}
