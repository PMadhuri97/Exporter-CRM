import type { ReactNode } from 'react';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { Button } from './Button';

/**
 * An empty state is one sentence and, if the role may act, one verb (§5.6) —
 * not a centred box with an icon in a circle.
 */
export function EmptyLine({
  children,
  action,
  className,
}: {
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <p className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-body text-ink-3', className)}>
      <span>{children}</span>
      {action}
    </p>
  );
}

/**
 * A refusal or a failed load, inline where it happened: what the person tried,
 * then the server's own words (§5.6), and a retry when one makes sense.
 */
export function InlineError({
  children,
  onRetry,
  className,
}: {
  children: ReactNode;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div role="alert" className={cn('flex items-start gap-2 text-secondary text-negative', className)}>
      <Icon.error size={15} className="mt-px shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">{children}</span>
      {onRetry && (
        <Button size="sm" variant="quiet" className="-my-1.5 h-7" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/** A key, as a shortcut sheet or a button hint shows it. */
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        'inline-flex h-5 min-w-5 items-center justify-center rounded border border-line-strong bg-surface px-1 font-mono text-[11px] leading-none text-ink-2',
        className,
      )}
    >
      {children}
    </kbd>
  );
}

/**
 * A big serif numeral (§6.11). Honest about a cap: when the server only says
 * "at least `cap`", it reads "200+", never a guess.
 */
export function Count({
  value,
  cap,
  size = 'xl',
  className,
  ...rest
}: {
  value: number;
  /** The most the request could return; a value at the cap shows as `cap+`. */
  cap?: number;
  size?: 'md' | 'lg' | 'xl';
  className?: string;
  'data-testid'?: string;
}) {
  const capped = cap !== undefined && value >= cap;
  return (
    <span
      className={cn(
        'font-display tabular-nums leading-none text-ink',
        size === 'xl' && 'text-display-xl',
        size === 'lg' && 'text-display-lg',
        size === 'md' && 'text-display-md',
        className,
      )}
      {...rest}
    >
      {capped ? `${cap}+` : value}
    </span>
  );
}
