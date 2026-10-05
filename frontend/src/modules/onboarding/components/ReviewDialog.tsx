/**
 * A verification result's review chain, and the dialog that adds to it
 * (verification-and-screening.md §1, §9).
 *
 * Reviews are append-only. A verdict never changes by editing: a later review
 * *supersedes* the current one by naming it (`supersedes_review_id =
 * latest_review_id`) and says why. If someone else reviewed while this screen was
 * open, the server answers 409 `VERIFICATION_REVIEW_STALE`; the list is refetched and
 * the reviewer is told, so nobody overrules a verdict they have not seen.
 *
 * Shared by the company workspace (`VerificationSection`) and `BuyerChecks`. Whether
 * the viewer may review is the server's `capabilities.can_review`, passed in.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { formatDateTime, humanize } from '@/lib/format';

import { useReviewVerification } from '../hooks';
import type {
  VerificationEntityType,
  VerificationResult,
  VerificationReview,
  VerificationReviewStatus,
} from '../types';

import { formatReviewer, REVIEW_OUTCOMES } from './verification-labels';
import { VerificationStatusChip } from './VerificationStatusChip';

const FIELD =
  'mt-1 w-full rounded-md border border-line bg-surface px-2 py-1.5 text-caption text-ink outline-none focus:border-accent disabled:opacity-60';
const SECONDARY_BUTTON =
  'rounded-lg border border-line px-2.5 py-1.5 text-caption font-medium text-ink-2 hover:bg-paper disabled:opacity-50';
const PRIMARY_BUTTON =
  'rounded-md bg-accent-solid px-2.5 py-1.5 text-caption font-medium text-white disabled:opacity-50';

/** Every review, first to current. Superseded reviews stay visible, as recorded. */
export function ReviewChain({ reviews }: { reviews: VerificationReview[] }) {
  if (reviews.length === 0) return null;
  return (
    <div data-testid="review-chain" className="mt-3 text-caption">
      <p className="flex items-center gap-1 text-ink-3">
        <Icon.history size={12} /> Reviews
      </p>
      <ol className="mt-1 space-y-1.5">
        {reviews.map((review, index) => {
          const current = index === reviews.length - 1;
          return (
            <li
              key={review.id}
              data-testid="review-chain-entry"
              className={current ? 'text-ink' : 'text-ink-3'}
            >
              <div className="flex flex-wrap items-center gap-2">
                <VerificationStatusChip value={review.review_status} />
                <span>{review.reviewed_by_name ?? formatReviewer(review.reviewed_by)}</span>
                <span>· {formatDateTime(review.reviewed_at)}</span>
                <span className="font-medium">{current ? 'Current' : 'Superseded'}</span>
              </div>
              {review.note && <p className="mt-0.5">{review.note}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ReviewDialog({
  result,
  entityType,
  entityReference,
  canReview,
  onStale,
}: {
  result: VerificationResult;
  entityType: VerificationEntityType;
  entityReference: string;
  canReview: boolean;
  onStale: () => void;
}) {
  const mutation = useReviewVerification(entityType, entityReference);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<VerificationReviewStatus | ''>('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);

  if (!canReview) return null;

  // A PENDING result has no finding to accept or reject; the server refuses (422).
  if (result.status === 'PENDING') {
    return (
      <p className="mt-3 flex items-start gap-2 text-caption text-ink-3">
        <Icon.info size={14} className="mt-0.5 shrink-0" />
        {result.is_placeholder
          ? 'Placeholder record — no provider ran this check, so it cannot be reviewed.'
          : 'This check has no outcome yet, so it cannot be reviewed.'}
      </p>
    );
  }

  // The review this one would supersede: the chain head. None means a first review.
  const supersedes = result.latest_review_id;

  if (!open) {
    return (
      <div className="mt-3">
        <button type="button" className={SECONDARY_BUTTON} onClick={() => setOpen(true)}>
          {supersedes ? 'Change the verdict' : 'Review'}
        </button>
      </div>
    );
  }

  async function submit() {
    setError(null);
    if (!status) {
      setError('Choose a verdict.');
      return;
    }
    const trimmed = note.trim();
    if (supersedes && !trimmed) {
      setError('Say why the verdict changes.');
      return;
    }
    try {
      await mutation.mutateAsync({
        verificationResultId: result.id,
        payload: {
          review_status: status,
          note: trimmed || null,
          supersedes_review_id: supersedes ?? null,
        },
      });
      toast.success(`Review recorded: ${humanize(status).toLowerCase()}`);
      setOpen(false);
      setStatus('');
      setNote('');
    } catch (caught) {
      if (caught instanceof ApiError && caught.errorCode === 'VERIFICATION_REVIEW_STALE') {
        setError(
          'Someone else reviewed this check first. The list has been refreshed — look at the current verdict and try again.',
        );
        onStale();
        return;
      }
      // Anything else (e.g. VERIFICATION_LEGACY_REVIEW_UNCHAINED) as the server words it.
      setError(caught instanceof ApiError ? caught.message : 'Could not record the review.');
    }
  }

  return (
    <div data-testid="review-form" className="mt-3 rounded-lg border border-line p-3 text-caption">
      <label className="block text-ink-3">
        Verdict
        <select
          aria-label="Verdict"
          className={FIELD}
          value={status}
          disabled={mutation.isPending}
          onChange={(event) => setStatus(event.target.value as VerificationReviewStatus | '')}
        >
          <option value="">Choose…</option>
          {REVIEW_OUTCOMES.map((outcome) => (
            <option key={outcome} value={outcome}>
              {humanize(outcome)}
            </option>
          ))}
        </select>
      </label>
      <label className="mt-2 block text-ink-3">
        {supersedes ? 'Why the verdict changes' : 'Note (optional)'}
        <textarea
          aria-label="Review note"
          className={`${FIELD} min-h-16 resize-y`}
          value={note}
          disabled={mutation.isPending}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      {error && (
        <p role="alert" className="mt-2 text-negative">
          {error}
        </p>
      )}
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" className={SECONDARY_BUTTON} onClick={() => setOpen(false)}>
          Cancel
        </button>
        <button
          type="button"
          className={PRIMARY_BUTTON}
          disabled={mutation.isPending}
          onClick={() => void submit()}
        >
          Record review
        </button>
      </div>
    </div>
  );
}
