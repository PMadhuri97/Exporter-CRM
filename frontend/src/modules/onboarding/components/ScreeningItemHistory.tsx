/**
 * One checklist item's full decision history — **owner: Developer 4B** (verification-and-screening.md
 * §5; architecture §3.3, "whose full history is shown"; 4B-7).
 *
 * The checklist table is append-only, so the server's history route *is* the item's
 * complete record: newest first, paged. Fetched only when opened, and shown exactly
 * as the server returns it.
 */

import { useState } from 'react';

import { Icon } from '@/design/icons';
import { formatDateTime } from '@/lib/format';

import { useScreeningItemHistory } from '../hooks';

import { formatReviewer } from './verification-labels';
import { VerificationStatusChip } from './VerificationStatusChip';

const HISTORY_PAGE_SIZE = 5;

export function ScreeningItemHistory({
  customerId,
  itemKey,
  label,
}: {
  customerId: string;
  itemKey: string;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const query = useScreeningItemHistory(customerId, itemKey, {
    limit: HISTORY_PAGE_SIZE,
    offset,
    enabled: open,
  });
  const page = query.data;

  return (
    <div className="mt-2">
      <button
        type="button"
        aria-expanded={open}
        aria-label={`${open ? 'Hide' : 'Show'} history for ${label}`}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1 text-[11px] font-medium text-ink-2 hover:text-ink"
      >
        {open ? <Icon.caretUp size={12} /> : <Icon.caretDown size={12} />}
        {open ? 'Hide history' : 'History'}
      </button>

      {open && (
        <div data-testid={`screening-history-${itemKey}`} className="mt-2 text-[11px]">
          {query.isLoading ? (
            <p className="text-ink-3">Loading history…</p>
          ) : query.isError || !page ? (
            <p role="alert" className="text-negative">
              The history could not be loaded.{' '}
              <button type="button" className="underline" onClick={() => void query.refetch()}>
                Retry
              </button>
            </p>
          ) : page.total === 0 ? (
            <p className="text-ink-3">No decision has been recorded on this item yet.</p>
          ) : (
            <>
              <ol className="space-y-1.5">
                {page.items.map((entry) => (
                  <li
                    key={entry.id}
                    data-testid="screening-history-entry"
                    className="rounded border border-line bg-surface px-2 py-1.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <VerificationStatusChip value={entry.status} />
                      <span className="text-ink-2">{entry.reviewed_by_name ?? formatReviewer(entry.reviewed_by)}</span>
                      <span className="text-ink-3">
                        {formatDateTime(entry.reviewed_at ?? entry.created_at)}
                      </span>
                    </div>
                    {entry.comment && <p className="mt-1 text-ink-2">{entry.comment}</p>}
                  </li>
                ))}
              </ol>
              <div className="mt-2 flex items-center justify-between gap-2 text-ink-3">
                <span>
                  {page.offset + 1}–{page.offset + page.items.length} of {page.total}
                </span>
                <span className="flex gap-2">
                  <button
                    type="button"
                    className="underline disabled:no-underline disabled:opacity-50"
                    disabled={page.offset === 0}
                    onClick={() => setOffset(Math.max(0, page.offset - HISTORY_PAGE_SIZE))}
                  >
                    Newer
                  </button>
                  <button
                    type="button"
                    className="underline disabled:no-underline disabled:opacity-50"
                    disabled={page.offset + page.items.length >= page.total}
                    onClick={() => setOffset(page.offset + HISTORY_PAGE_SIZE)}
                  >
                    Older
                  </button>
                </span>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
