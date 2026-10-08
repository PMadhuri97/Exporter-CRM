/**
 * Move one relationship manager's companies to another — when someone leaves, or to
 * split a book. ADMIN and holders of `exporters:assign_rm` only; the server checks again.
 *
 * Choose who from (an active RM, or one whose companies are listed — a deactivated RM
 * is found through the "RM deactivated" owner filter), who to (an active RM), whether to
 * move only the companies shown, and a reason. Without "only the companies shown" the
 * list's journey lens still applies — on Prospects, all of their prospects move — and
 * the panel says so. **Check** asks the server for a dry run
 * and shows how many would move; **Reassign** does it. Companies whose RM changed in the
 * meantime are skipped by the server, never overwritten.
 */

import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button, Field, FormError, Select, Textarea, RequiredNote } from '@/components';
import { ApiError } from '@/lib/api/errors';

import { JOURNEY_LABEL } from '../constants';
import { useReassignRelationshipManagers, useStaff } from '../hooks';
import type { BulkReassignResult, ExporterJourney, ExporterProfileListItem } from '../types';

export function BulkReassignPanel({
  shown,
  journey,
  onClose,
}: {
  /** The companies the list shows now. */
  shown: readonly ExporterProfileListItem[];
  /** The list's journey lens, applied to "all of their companies" too. */
  journey: ExporterJourney | undefined;
  onClose: () => void;
}) {
  const staff = useStaff(['OPERATIONS']);
  const reassign = useReassignRelationshipManagers();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [reason, setReason] = useState('');
  const [onlyShown, setOnlyShown] = useState(false);
  const [preview, setPreview] = useState<BulkReassignResult | null>(null);

  // Who the companies can come from: every active RM, and any RM on the rows shown
  // (which is how a deactivated RM's book is reached).
  const fromOptions = useMemo(() => {
    const options = new Map<string, string>();
    for (const member of staff.data?.staff ?? []) options.set(member.id, member.name);
    for (const row of shown) {
      if (row.relationship_manager_user_id && !options.has(row.relationship_manager_user_id)) {
        options.set(
          row.relationship_manager_user_id,
          `${row.relationship_manager_name ?? 'Unknown'}${row.relationship_manager_inactive ? ' (deactivated)' : ''}`,
        );
      }
    }
    return [...options.entries()];
  }, [staff.data, shown]);

  const shownIds = shown
    .filter((row) => row.relationship_manager_user_id === from)
    .map((row) => row.customer_id);

  const body = (dryRun: boolean) => ({
    from_user_id: from,
    to_user_id: to,
    company_ids: onlyShown ? shownIds : null,
    journey: onlyShown ? null : journey ?? null,
    reason: reason.trim(),
    dry_run: dryRun,
  });

  // What "all of their companies" means under the list's lens, said in the panel.
  const lensNoun = journey ? `${JOURNEY_LABEL[journey].toLowerCase()}s` : 'companies';

  const ready = from !== '' && to !== '' && from !== to && reason.trim().length > 0;
  const changed = () => setPreview(null);

  return (
    <div
      role="dialog"
      aria-label="Reassign companies"
      className="space-y-3 border-b border-line bg-sunken px-4 py-3"
    >
      <h3 className="text-body font-semibold text-ink">Reassign companies</h3>
      <RequiredNote />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="From" htmlFor="bulk-from" required>
          <Select
            id="bulk-from"
            value={from}
            onChange={(event) => {
              setFrom(event.target.value);
              changed();
            }}
          >
            <option value="">Choose an RM</option>
            {fromOptions.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="To" htmlFor="bulk-to" required>
          <Select
            id="bulk-to"
            value={to}
            onChange={(event) => {
              setTo(event.target.value);
              changed();
            }}
          >
            <option value="">Choose an RM</option>
            {(staff.data?.staff ?? [])
              .filter((member) => member.id !== from)
              .map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name} ({member.companies})
                </option>
              ))}
          </Select>
        </Field>
      </div>
      <label className="flex items-center gap-2 text-body text-ink-2">
        <input
          type="checkbox"
          checked={onlyShown}
          onChange={(event) => {
            setOnlyShown(event.target.checked);
            changed();
          }}
        />
        Only the companies shown below ({from ? shownIds.length : 0})
      </label>
      <p className="text-caption text-ink-3">
        {onlyShown
          ? 'Moves only the companies listed below.'
          : `Moves all of their ${lensNoun}, including those not on this page.`}
      </p>
      <Field label="Reason" htmlFor="bulk-reason" required>
        <Textarea
          id="bulk-reason"
          rows={2}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
            changed();
          }}
        />
      </Field>
      <FormError>
        {reassign.isError &&
          (reassign.error instanceof ApiError ? reassign.error.message : 'Could not reassign.')}
      </FormError>
      {preview && (
        <p className="text-body text-ink" role="status">
          {preview.matched === 0
            ? 'No companies would move.'
            : `${preview.matched} compan${preview.matched === 1 ? 'y' : 'ies'} would move${
                !onlyShown && journey ? ` (${lensNoun} only)` : ''
              }.`}
          {preview.skipped > 0 && ` ${preview.skipped} are not theirs and would be skipped.`}
        </p>
      )}
      <div className="flex gap-2">
        {preview && preview.matched > 0 ? (
          <Button
            variant="primary"
            size="sm"
            loading={reassign.isPending}
            disabled={!ready}
            onClick={() =>
              reassign.mutate(body(false), {
                onSuccess: (result) => {
                  toast.success(
                    `${result.moved} compan${result.moved === 1 ? 'y' : 'ies'} reassigned` +
                      (result.skipped ? `; ${result.skipped} skipped` : ''),
                  );
                  onClose();
                },
              })
            }
          >
            Reassign {preview.matched}
          </Button>
        ) : (
          <Button
            size="sm"
            loading={reassign.isPending}
            disabled={!ready || (onlyShown && shownIds.length === 0)}
            onClick={() => reassign.mutate(body(true), { onSuccess: setPreview })}
          >
            Check
          </Button>
        )}
        <Button size="sm" variant="subtle" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
