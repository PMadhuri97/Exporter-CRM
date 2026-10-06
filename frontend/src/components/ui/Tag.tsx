import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { Badge } from './Badge';
import type { BadgeTone, TagTone } from './styles';

export interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  /** A meaning from the status language (frontend-plan §5.2). `ink` is an
   * emphasis that is not a state ("Primary", "Required"), drawn as an outline. */
  tone?: TagTone;
  /** A leading dot in the meaning's solid colour. */
  dot?: boolean;
  icon?: ReactNode;
}

const TONE: Record<TagTone, BadgeTone> = {
  neutral: 'neutral',
  idle: 'neutral',
  ink: 'neutral',
  positive: 'positive',
  negative: 'negative',
  attention: 'attention',
  progress: 'progress',
};

/**
 * The older name for `Badge`, kept while screens move over: the same 20px worded
 * label, with no dot unless asked for (a tag sits among other text).
 */
export function Tag({ tone = 'idle', dot = false, icon, className, children, ...rest }: TagProps) {
  return (
    <Badge
      tone={TONE[tone]}
      variant={tone === 'ink' ? 'outline' : 'tint'}
      dot={dot}
      icon={icon}
      className={cn(tone === 'ink' && 'text-ink', className)}
      {...rest}
    >
      {children}
    </Badge>
  );
}
