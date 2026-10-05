/**
 * Which of the seller's GST registrations a deal is invoiced from, on the deal page.
 *
 * The handover guard asks for it (`deal-and-buyer.md` §6.1, conditions 6
 * and 7): a deal whose seller has an **active** GST registration but names none is
 * refused with "the invoicing branch is not recorded", and a deal invoiced through a
 * **flagged** branch is refused too. `PUT /deals/{id}/invoicing-branch` is the only
 * way to record one, so without this control such a deal could never be handed over
 * from the screen.
 *
 * What the control says, and why:
 *
 * * **Only active branches are offered.** A deactivated registration stays on record,
 *   but nothing new is invoiced from it and the server refuses it (422). If the
 *   recorded one was deactivated afterwards it is still shown, as what is recorded, and
 *   cannot be chosen again.
 * * **The GSTIN exactly as the server sent it**, beside the state: masked for
 *   OPERATIONS and DEVELOPER by `GET …/gst-registrations` itself. Nothing here builds,
 *   stores or unmasks one.
 * * **Changeable and clearable until the deal closes**, then
 *   read-only: `prevent_terminal_deal_change()` freezes it with a handed-over or
 *   withdrawn deal, and the route refuses a change (409).
 * * **The notes under it come from the facts the guard reads** — whether the seller
 *   has an active branch, whether the recorded one is flagged — and never from
 *   `handover_blocked_reason`, which is one joined sentence, shown whole beside the
 *   stage moves.
 */

import { toast } from 'sonner';

import {
  Button,
  Tag,
  DetailRow,
  EmptySection,
  ErrorState,
  Field,
  Select,
  Skeleton,
} from '@/components';
import { Icon } from '@/design/icons';

import { useGstRegistrations, useSetDealInvoicingBranch } from '../hooks';
import type { GstRegistration } from '../types';

export interface InvoicingBranchPickerProps {
  dealId: string;
  /** The deal's own company: the branches are its registrations. */
  sellerId: string;
  /** `deal.seller_gst_registration_id`. */
  recordedId: string | null;
  /** Whether this viewer may record one (OPERATIONS, COMPLIANCE, ADMIN). */
  canEdit: boolean;
  /** Handed over or withdrawn: the branch is frozen with the deal. */
  closed: boolean;
}

/** The state identifies a branch to a person; an unknown code says so. */
function stateName(registration: GstRegistration): string {
  return (
    registration.state_name ??
    (registration.state_code ? `State code ${registration.state_code}` : 'Unknown state')
  );
}

function optionLabel(registration: GstRegistration): string {
  return `${stateName(registration)} · ${registration.gstin}`;
}

function BranchStatus({ registration }: { registration: GstRegistration }) {
  return (
    <>
      {registration.flag_status === 'FLAGGED' && (
        <Tag tone="attention" icon={<Icon.flagged size={12} aria-hidden />}>
          Flagged
        </Tag>
      )}
      {!registration.active && <Tag>Deactivated</Tag>}
    </>
  );
}

export function InvoicingBranchPicker({
  dealId,
  sellerId,
  recordedId,
  canEdit,
  closed,
}: InvoicingBranchPickerProps) {
  const query = useGstRegistrations(sellerId);
  const mutation = useSetDealInvoicingBranch(dealId, sellerId);

  if (query.isLoading) return <Skeleton className="h-10 w-full max-w-md" />;
  if (query.isError) {
    return (
      <ErrorState
        title="Could not load the seller's GST registrations."
        onRetry={() => void query.refetch()}
      />
    );
  }

  const registrations = query.data?.registrations ?? [];
  const active = registrations.filter((registration) => registration.active);
  // While a write is in flight, show what was chosen rather than snapping back to the
  // old value until the response arrives.
  const shownId =
    mutation.isPending && mutation.variables
      ? (mutation.variables.gst_registration_id ?? null)
      : recordedId;
  const shown =
    shownId === null
      ? null
      : (registrations.find((registration) => registration.id === shownId) ?? null);
  const editable = canEdit && !closed;
  // Recorded, then deactivated: still what this deal names, but not a branch it can be
  // pointed at again.
  const shownIsInactive =
    shownId !== null && !active.some((registration) => registration.id === shownId);

  function record(id: string | null) {
    const chosen = registrations.find((registration) => registration.id === id);
    mutation.mutate(
      { gst_registration_id: id },
      {
        onSuccess: () =>
          toast.success(
            chosen ? `Invoiced from ${stateName(chosen)}` : 'Invoicing branch cleared',
          ),
        // The server words every refusal: a deactivated branch, another company's,
        // or a deal that has closed since the page loaded.
        onError: (error) =>
          toast.error(
            error instanceof Error ? error.message : 'Could not record the invoicing branch',
          ),
      },
    );
  }

  // Condition 6 is asked only of a seller with a branch to name, so with none there is
  // nothing to choose and nothing missing.
  if (shownId === null && active.length === 0) {
    return (
      <EmptySection>
        {closed
          ? 'No invoicing branch was recorded.'
          : 'The seller has no active GST registration, so a handover does not ask for one.'}
      </EmptySection>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {editable ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field
            label="Invoiced from"
            htmlFor={`invoicing-branch-${dealId}`}
            className="min-w-[16rem] flex-1"
          >
            <Select
              id={`invoicing-branch-${dealId}`}
              value={shownId ?? ''}
              disabled={mutation.isPending}
              onChange={(event) => {
                if (event.target.value) record(event.target.value);
              }}
            >
              {shownId === null && (
                <option value="" disabled>
                  Choose a branch…
                </option>
              )}
              {active.map((registration) => (
                <option key={registration.id} value={registration.id}>
                  {optionLabel(registration)}
                  {registration.flag_status === 'FLAGGED' ? ' — flagged' : ''}
                </option>
              ))}
              {shownId !== null && shownIsInactive && (
                <option value={shownId} disabled>
                  {shown ? `${optionLabel(shown)} — deactivated` : 'A registration no longer listed'}
                </option>
              )}
            </Select>
          </Field>
          {shownId !== null && (
            <Button
              size="sm"
              variant="quiet"
              disabled={mutation.isPending}
              onClick={() => record(null)}
            >
              Clear
            </Button>
          )}
        </div>
      ) : (
        <dl>
          <DetailRow label="Invoiced from">
            {shown ? (
              <span className="inline-flex flex-wrap items-center gap-2">
                <span className="font-medium text-ink">{stateName(shown)}</span>
                <span className="font-mono text-xs text-ink-2">{shown.gstin}</span>
                <BranchStatus registration={shown} />
              </span>
            ) : shownId !== null ? (
              'A registration no longer listed'
            ) : closed ? (
              'No invoicing branch was recorded.'
            ) : (
              'Not recorded yet.'
            )}
          </DetailRow>
        </dl>
      )}

      {editable && shown && (shown.flag_status === 'FLAGGED' || !shown.active) && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
          <BranchStatus registration={shown} />
        </p>
      )}

      {!closed && shownId === null && (
        <p
          role="status"
          className="rounded-lg border border-attention/30 bg-attention-tint px-3 py-2 text-sm text-ink"
        >
          <span className="font-medium">Not recorded.</span>{' '}
          <span className="text-ink-2">
            The seller has an active GST registration, so a handover asks which one this
            deal is invoiced from.
          </span>
        </p>
      )}

      {!closed && shown?.flag_status === 'FLAGGED' && (
        <p
          role="status"
          className="rounded-lg border border-attention/30 bg-attention-tint px-3 py-2 text-sm text-ink"
        >
          <span className="font-medium">This branch is flagged.</span>{' '}
          <span className="text-ink-2">
            A deal invoiced through it cannot be handed over: the flag is resolved on the
            seller's GST registrations, or the deal is invoiced from another branch.
          </span>
        </p>
      )}

      {closed && (
        <p className="text-xs text-ink-3">
          Frozen with the deal: a closed deal's invoicing branch no longer changes.
        </p>
      )}
    </div>
  );
}
