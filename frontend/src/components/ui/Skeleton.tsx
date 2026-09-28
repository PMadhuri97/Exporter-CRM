import { cn } from '@/lib/cn';

/** A pulsing placeholder block — skeletons, not spinners, for content loads. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-pulse rounded bg-surface-sunken', className)} />;
}
