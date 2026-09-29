/**
 * The eight-item compliance screening checklist — **owner: Developer 4B**
 * (4b-task.md §5.5, §5.6, §5.10; 4B-7).
 *
 * Rendered from the server: the items, their labels, sections and order come from
 * `catalogue` (the one backend catalogue, `SCREENING_CATALOGUE_ITEMS`), and whether
 * the viewer may record a decision from `capabilities.can_record_decision`. This file
 * keeps no copy of either. Each item's full history opens beneath it.
 *
 * Screening is a compliance list inside the background check. It is not
 * qualification, and not a gauge (architecture §5.5).
 */

import { AlertTriangle } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

import { useScreeningReview, useUpdateScreeningReviewItem } from '../hooks';
import type { ScreeningCatalogueItem, ScreeningChecklistStatus } from '../types';

import { ScreeningItemHistory } from './ScreeningItemHistory';
import { VerificationStatusChip } from './VerificationStatusChip';

export function ScreeningChecklist({ customerId }: { customerId: string }) {
  const query = useScreeningReview(customerId);
  const mutation = useUpdateScreeningReviewItem(customerId);
  const catalogue = query.data?.catalogue ?? [];
  const canRecord = query.data?.capabilities.can_record_decision ?? false;
  const serverItems = query.data?.items ?? [];
  const byKey = new Map(serverItems.map((item) => [item.item_key, item]));
  const completed = catalogue.filter(
    (item) => (byKey.get(item.key)?.status ?? 'NEEDS_REVIEW') !== 'NEEDS_REVIEW',
  ).length;
  // Sections in the order the catalogue first uses them.
  const sections = [...new Set(catalogue.map((item) => item.section))];
  // Rows persisted under a key the catalogue no longer (or not yet) defines — an
  // older checklist revision, or a key written before keys were validated. Listing
  // only the catalogue would fetch these and silently drop them, hiding a decision
  // that exists in the database. Read-only: nothing here knows what they mean.
  const knownKeys = new Set(catalogue.map((item) => item.key));
  const unrecognised = serverItems.filter((item) => !knownKeys.has(item.item_key));

  async function save(itemKey: string, status: ScreeningChecklistStatus, comment: string | null) {
    try {
      await mutation.mutateAsync({ itemKey, status, comment });
      toast.success('Review item saved');
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Could not save review item');
    }
  }

  return (
    <aside
      data-testid="screening-checklist"
      className="rounded-lg border border-border bg-surface shadow-card"
    >
      <div className="border-b border-border px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-ink">Review checklist</h3>
            {!query.isLoading && !query.isError && (
              <p className="mt-0.5 text-xs text-ink-muted">
                {completed}/{catalogue.length} items reviewed
                {unrecognised.length > 0 && ` · ${unrecognised.length} unrecognised`}
              </p>
            )}
          </div>
        </div>
        <p className="mt-3 rounded-md bg-surface-subtle px-3 py-2 text-xs leading-5 text-ink-faint">
          Decisions and comments are stored with reviewer and timestamp; every earlier
          decision stays in each item&apos;s history.
        </p>
      </div>

      <div className="max-h-[720px] space-y-4 overflow-y-auto p-4">
        {query.isLoading ? (
          <div className="h-32 animate-pulse rounded bg-surface-sunken" />
        ) : query.isError ? (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">
            Could not load checklist.{' '}
            <button type="button" className="underline" onClick={() => void query.refetch()}>
              Retry
            </button>
          </div>
        ) : (
          sections.map((section) => (
            <div key={section} data-testid="screening-section">
              <p className="mb-2 text-xs font-semibold text-ink">{section}</p>
              <div className="space-y-2">
                {catalogue
                  .filter((item) => item.section === section)
                  .map((item) => {
                    const saved = byKey.get(item.key);
                    return (
                      <ChecklistCard
                        // Stable: keying on the saved values remounted every card
                        // whenever any one of them saved, throwing away unsaved text
                        // in the others. The card reconciles server changes itself.
                        key={item.key}
                        customerId={customerId}
                        item={item}
                        initialStatus={saved?.status ?? 'NEEDS_REVIEW'}
                        initialComment={saved?.comment ?? ''}
                        canRecord={canRecord}
                        busy={mutation.isPending}
                        onSave={save}
                      />
                    );
                  })}
              </div>
            </div>
          ))
        )}

        {!query.isLoading && !query.isError && unrecognised.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-amber-700">
              <AlertTriangle size={13} /> Unrecognised items
            </p>
            <p className="mb-2 text-[11px] leading-5 text-ink-muted">
              Stored against this exporter under a key the checklist does not define. Shown
              read-only so a persisted decision is never hidden.
            </p>
            <div className="space-y-2">
              {unrecognised.map((item) => (
                <div
                  key={item.id}
                  data-testid="unrecognised-item"
                  className="rounded-lg border border-dashed border-amber-300 bg-amber-50/40 px-3 py-2.5"
                >
                  <p className="break-all font-mono text-[11px] text-ink">{item.item_key}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <VerificationStatusChip value={item.status} />
                    <span className="text-[11px] text-ink-faint">
                      {formatDateTime(item.reviewed_at)}
                    </span>
                  </div>
                  {item.comment && (
                    <p className="mt-1.5 text-xs leading-5 text-ink-muted">{item.comment}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

function ChecklistCard({
  customerId,
  item,
  initialStatus,
  initialComment,
  canRecord,
  busy,
  onSave,
}: {
  customerId: string;
  item: ScreeningCatalogueItem;
  initialStatus: ScreeningChecklistStatus;
  initialComment: string;
  canRecord: boolean;
  busy: boolean;
  onSave: (itemKey: string, status: ScreeningChecklistStatus, comment: string | null) => Promise<void>;
}) {
  const [status, setStatus] = useState(initialStatus);
  const [comment, setComment] = useState(initialComment);

  // With a stable key, adopting a newly saved value has to be explicit: when the
  // server values this card was last synced from change — its own save landing, or a
  // refetch — take them. Adjusting state during render is the documented pattern;
  // no other card is touched.
  const [syncedFrom, setSyncedFrom] = useState({
    status: initialStatus,
    comment: initialComment,
  });
  if (syncedFrom.status !== initialStatus || syncedFrom.comment !== initialComment) {
    setSyncedFrom({ status: initialStatus, comment: initialComment });
    setStatus(initialStatus);
    setComment(initialComment);
  }

  const disabled = !canRecord || busy;
  const dirty = status !== initialStatus || comment !== initialComment;

  return (
    <div
      data-testid="screening-item"
      data-item-key={item.key}
      className="rounded-lg border border-border bg-surface-subtle px-3 py-2.5"
    >
      <p className="text-xs leading-5 text-ink-muted">{item.label}</p>
      <select
        aria-label={`${item.label} status`}
        className="mt-2 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink outline-none focus:border-brand-500 disabled:opacity-60"
        value={status}
        disabled={disabled}
        onChange={(event) => setStatus(event.target.value as ScreeningChecklistStatus)}
      >
        <option value="NEEDS_REVIEW">Needs review</option>
        <option value="PASSED">Passed</option>
        <option value="FAILED">Failed</option>
        <option value="EXEMPT">Exempt</option>
      </select>
      <textarea
        aria-label={`${item.label} comment`}
        className="mt-2 min-h-16 w-full resize-y rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink outline-none focus:border-brand-500 disabled:opacity-60"
        placeholder={canRecord ? 'Add review comment (optional)' : undefined}
        value={comment}
        disabled={disabled}
        onChange={(event) => setComment(event.target.value)}
      />
      {dirty && !disabled && (
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() => void onSave(item.key, status, comment.trim() || null)}
            className="rounded-md bg-ink px-2.5 py-1.5 text-xs font-medium text-white"
          >
            Save
          </button>
        </div>
      )}
      <ScreeningItemHistory customerId={customerId} itemKey={item.key} label={item.label} />
    </div>
  );
}
