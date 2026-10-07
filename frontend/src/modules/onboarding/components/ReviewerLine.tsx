/**
 * Who holds the review: "Reviewer: Priya, since 7 Oct 14:02", or *Unassigned*, and what
 * this user may do about it — exactly the server's `review_actions`:
 *
 * - **Assign to me** (`CLAIM`) on an unassigned review;
 * - **Release** back to Awaiting review, with an optional note — the reviewer, or a lead;
 * - **Reassign** (`ASSIGN`, ADMIN or `compliance:assign`) to an active compliance user,
 *   with a reason when taking it from someone.
 *
 * Shown only while the check is under review (IN_REVIEW or MORE_INFO). A reviewer whose
 * account was deactivated is flagged so a lead can move the review on.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Button, Field, FormError, Select, Tag, Textarea } from '@/components';
import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

import { useChangeReviewer, useStaff } from '../hooks';
import type { BackgroundCheck } from '../types';

type Mode = 'ASSIGN' | 'RELEASE';

export function ReviewerLine({ customerId, standing }: { customerId: string; standing: BackgroundCheck }) {
  const change = useChangeReviewer(customerId);
  const [mode, setMode] = useState<Mode | null>(null);
  const [target, setTarget] = useState('');
  const [text, setText] = useState('');
  const staff = useStaff(['COMPLIANCE', 'ADMIN'], mode === 'ASSIGN');

  if (standing.value !== 'IN_REVIEW' && standing.value !== 'MORE_INFO') return null;
  const actions = standing.review_actions ?? [];
  const holder = standing.reviewer_id ?? null;
  const replacing = mode === 'ASSIGN' && holder !== null;

  const done = (message: string) => () => {
    toast.success(message);
    setMode(null);
    setTarget('');
    setText('');
  };

  return (
    <div data-testid="reviewer-line" className="mt-3 border-t border-line pt-3">
      <div className="flex flex-wrap items-center gap-2 text-body">
        <span className="text-caption text-ink-3">Reviewer</span>
        {holder ? (
          <>
            <span className="font-medium text-ink">{standing.reviewer_name ?? 'Unknown user'}</span>
            {standing.reviewer_assigned_at && (
              <span className="text-caption text-ink-3">
                since {formatDateTime(standing.reviewer_assigned_at)}
              </span>
            )}
            {standing.reviewer_inactive && (
              <Tag tone="negative" icon={<Icon.warning size={11} aria-hidden />}>
                Deactivated
              </Tag>
            )}
          </>
        ) : (
          <span className="text-ink-3">Unassigned — awaiting review</span>
        )}
        {mode === null && (
          <span className="ml-auto flex gap-2">
            {actions.includes('CLAIM') && (
              <Button
                size="sm"
                variant="primary"
                loading={change.isPending}
                onClick={() => change.mutate({ kind: 'CLAIM' }, { onSuccess: done('You are now the reviewer') })}
              >
                Assign to me
              </Button>
            )}
            {actions.includes('RELEASE') && (
              <Button size="sm" variant="subtle" onClick={() => setMode('RELEASE')}>
                Release
              </Button>
            )}
            {actions.includes('ASSIGN') && (
              <Button size="sm" variant="subtle" onClick={() => setMode('ASSIGN')}>
                {holder ? 'Reassign' : 'Assign'}
              </Button>
            )}
          </span>
        )}
      </div>
      {mode === null && change.isError && (
        <p role="alert" className="mt-1 text-caption text-negative">
          {change.error instanceof ApiError ? change.error.message : 'Could not change the reviewer.'}
        </p>
      )}

      {mode !== null && (
        <div
          role="dialog"
          aria-label={mode === 'RELEASE' ? 'Release the review' : 'Assign the review'}
          className="mt-2 max-w-md space-y-3 rounded-lg border border-line bg-surface p-3"
        >
          {mode === 'ASSIGN' && (
            <Field label="Reviewer" htmlFor="reviewer-picker" required>
              <Select
                id="reviewer-picker"
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                disabled={staff.isLoading}
              >
                <option value="">{staff.isLoading ? 'Loading…' : 'Choose a reviewer'}</option>
                {(staff.data?.staff ?? [])
                  .filter((member) => member.id !== holder)
                  .map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.name} ({member.open_reviews} open)
                    </option>
                  ))}
              </Select>
            </Field>
          )}
          {(mode === 'RELEASE' || replacing) && (
            <Field
              label={mode === 'RELEASE' ? 'Note (optional)' : 'Reason'}
              htmlFor="reviewer-text"
              required={replacing}
            >
              <Textarea id="reviewer-text" rows={2} value={text} onChange={(event) => setText(event.target.value)} />
            </Field>
          )}
          <FormError>
            {change.isError &&
              (change.error instanceof ApiError ? change.error.message : 'Could not change the reviewer.')}
          </FormError>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="primary"
              loading={change.isPending}
              disabled={mode === 'ASSIGN' && (target === '' || (replacing && text.trim() === ''))}
              onClick={() =>
                mode === 'RELEASE'
                  ? change.mutate({ kind: 'RELEASE', note: text.trim() || null }, { onSuccess: done('Review released') })
                  : change.mutate(
                      { kind: 'ASSIGN', userId: target, reason: text.trim() || null },
                      { onSuccess: done('Reviewer assigned') },
                    )
              }
            >
              {mode === 'RELEASE' ? 'Release' : 'Assign'}
            </Button>
            <Button size="sm" variant="subtle" onClick={() => setMode(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
