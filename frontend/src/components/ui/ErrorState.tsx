import { AlertCircle } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { Button } from './Button';

/** A load that failed: what happened, and a way to try again when there is one. */
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
        'flex flex-col items-center rounded-lg border border-status-failed/30 bg-status-failed/5 px-4 py-8 text-center',
        className,
      )}
    >
      <AlertCircle size={20} className="text-status-failed" aria-hidden />
      <p className="mt-2 font-medium text-ink">{title}</p>
      {children && <div className="mt-1 text-sm text-ink-muted">{children}</div>}
      {onRetry && (
        <Button size="sm" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
