/**
 * A count on a navigation row — the v1 notification: computed by the server on read
 * (`GET /worklist/counts`), refetched on focus and every minute. Numbers only, never a
 * name, identifier or reason.
 *
 * - `compliance` (on Compliance work): reviews this user holds plus decisions waiting for
 *   their signature; red when a lead has overdue work.
 * - `infoRequested` (on My companies): checks waiting on information for companies this
 *   user is RM of.
 *
 * Nothing for a role that may not read compliance work (DEVELOPER), and nothing at 0.
 */

import { cn } from '@/lib/cn';
import { useCan } from '@/platform/access';

import { useWorklistCounts } from '../hooks/background-check';

export type WorklistBadgeKind = 'compliance' | 'infoRequested';

export function WorklistBadge({ kind, collapsed = false }: { kind: WorklistBadgeKind; collapsed?: boolean }) {
  const allowed = useCan('compliance.read');
  const counts = useWorklistCounts(allowed);
  if (!allowed || !counts.data) return null;
  const data = counts.data;
  const count =
    kind === 'compliance'
      ? (data.my_reviews ?? 0) + (data.awaiting_approval ?? 0)
      : data.info_requested;
  const urgent = kind === 'compliance' && (data.overdue ?? 0) > 0;
  if (count === 0 && !urgent) return null;
  const label =
    kind === 'compliance'
      ? `${data.my_reviews ?? 0} of your reviews, ${data.awaiting_approval ?? 0} awaiting your signature` +
        (urgent ? `, ${data.overdue} overdue` : '')
      : `${count} of your companies waiting on information`;
  return (
    <span
      title={label}
      aria-label={label}
      data-testid={`nav-badge-${kind}`}
      className={cn(
        'ml-auto inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-caption font-semibold tabular-nums',
        urgent ? 'bg-negative-tint text-negative' : 'bg-accent-tint text-accent',
        collapsed && 'absolute right-1 top-0.5 ml-0 min-w-4 px-1',
      )}
    >
      {count}
    </span>
  );
}
