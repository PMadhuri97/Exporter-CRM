import type { ReactNode } from 'react';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { Button } from './Button';

/**
 * A load that failed, inline in the section that failed (§8.10): what happened,
 * in the server's words where there are some, and a way to try again. A
 * section's failure never blanks the page around it.
 */
export function ErrorState({
  title,
  children,
  onRetry,
  className,
}: {
  title: ReactNode;
  children?: ReactNode;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex items-start gap-3 rounded-md border-l-2 border-negative bg-negative-tint px-4 py-3',
        className,
      )}
    >
      <Icon.error size={18} className="mt-0.5 shrink-0 text-negative" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">{title}</p>
        {children && <div className="mt-0.5 text-secondary text-ink-2">{children}</div>}
        {onRetry && (
          <Button size="sm" variant="secondary" className="mt-3" onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}
