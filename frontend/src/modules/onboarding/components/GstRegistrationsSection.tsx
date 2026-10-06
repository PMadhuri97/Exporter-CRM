/**
 * A company's GST registrations — its branches.
 *
 * Replaces the comma-separated "GSTINs" field that used to sit in `CompanyPanel`.
 * That field edited a list of strings and a save replaced the whole list, which
 * deleted the row of every GSTIN dropped — and a GST registration is a branch the
 * company really traded through, named by any deal that invoiced from it. So this is
 * a list of records with three deliberate actions, not a text box.
 *
 * What it shows, and why each part is there:
 *
 * * **The state, not just the GSTIN.** The state is what identifies a branch to a
 *   person ("Maharashtra"), and it is derived from the GSTIN rather than typed, so it
 *   cannot contradict it.
 * * **Deactivated branches, greyed out.** They are how a deal handed over through
 *   them is explained; hiding them would make that deal's invoicing branch look as
 *   though it came from nowhere.
 * * **"Also on another company"** when a GSTIN is shared. Allowed, so
 *   it is a warning. It matters most beside a flag: flagging this company's row does
 *   **not** flag theirs, and somebody who did not know that would believe they had
 *   stopped trade that is still running.
 * * **A "verify on the GST portal" link**, only when the server sent one — it
 *   contains the GSTIN, so a role that sees the value masked does not get the link.
 *   The component does not build the URL itself for exactly that reason:
 *   the decision about who may see a GSTIN belongs on the server.
 * * **Flag and unflag only for a role that may.** A flag stops trade through the
 *   branch, so it is COMPLIANCE's decision; `canFlag` comes from the caller's role.
 *   A reason is required both ways, and the form says why.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { Button, EmptySection, Input, LINK_CLASSES, Panel, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import {
  useAddGstRegistration,
  useDeactivateGstRegistration,
  useGstRegistrations,
  useSetGstRegistrationFlag,
} from '../hooks';
import { paths } from '../paths';
import type { GstRegistration } from '../types';

export interface GstRegistrationsSectionProps {
  customerId: string;
  /** Whether this viewer may record and deactivate a branch (OPERATIONS and up). */
  canEdit: boolean;
  /** Whether this viewer may flag one (COMPLIANCE, ADMIN). */
  canFlag: boolean;
}

/** What the GST portal says about a registration, in words rather than an enum. */
const STATUS_LABEL: Record<GstRegistration['status'], string> = {
  // Not "Active": nobody has checked it, and saying so is the point of the value.
  UNVERIFIED: 'Not verified',
  ACTIVE: 'Active at the portal',
  CANCELLED: 'Cancelled at the portal',
  SUSPENDED: 'Suspended at the portal',
};

export function GstRegistrationsSection({
  customerId,
  canEdit,
  canFlag,
}: GstRegistrationsSectionProps) {
  const query = useGstRegistrations(customerId);
  const [adding, setAdding] = useState(false);
  const [gstin, setGstin] = useState('');
  const [address, setAddress] = useState('');

  const add = useAddGstRegistration(customerId);
  const deactivate = useDeactivateGstRegistration(customerId);
  const setFlag = useSetGstRegistrationFlag(customerId);

  const registrations = query.data?.registrations ?? [];
  const flaggedCount = query.data?.flagged_count ?? 0;

  function submit() {
    const value = gstin.trim();
    if (!value) return;
    add.mutate(
      // `UNVERIFIED` is the server's default, sent because the generated request type
      // requires every defaulted field: nobody has checked this GSTIN at the portal
      // yet, and recording it as `ACTIVE` would be a claim.
      { gstin: value, address: address.trim() || null, status: 'UNVERIFIED' },
      {
        onSuccess: (created) => {
          setAdding(false);
          setGstin('');
          setAddress('');
          toast.success(
            created.state_name
              ? `GST registration added for ${created.state_name}`
              : 'GST registration added',
          );
          if ((created.also_held_by ?? []).length > 0) {
            // Allowed, so not an error — but the person should know now rather than
            // discover it when a flag does not do what they expected.
            toast.warning('Another company also holds this GSTIN');
          }
        },
        // The server words every refusal: a GSTIN that does not carry the company's
        // PAN, or one this company already has.
        onError: (error) =>
          toast.error(
            error instanceof Error ? error.message : 'Could not add that registration',
          ),
      },
    );
  }

  return (
    <Panel
      title="GST registrations"
      actions={
        canEdit &&
        !adding && (
          <Button size="sm" onClick={() => setAdding(true)}>
            <Icon.add size={14} /> Add registration
          </Button>
        )
      }
    >
      {/* Not the Panel's `description`: the card header wraps, and a line this long
          pushed "Add registration" onto a row of its own below it. In the body the text
          reads the same and the button keeps the top-right corner. */}
      {/* <p className="mb-3 text-secondary text-ink-3">
        One per state the company is registered in. A registration is kept even after it stops
        being used, because a handed-over deal may have been invoiced through it.
      </p> */}

      {flaggedCount > 0 && (
        <div
          role="alert"
          className="mb-3 flex items-center gap-2 rounded-lg border border-attention/40 bg-attention-tint p-3 text-body text-ink"
        >
          <Icon.warning size={15} className="shrink-0 text-attention" />
          <span className="font-medium">
            {flaggedCount === 1 ? '1 branch flagged' : `${flaggedCount} branches flagged`}
          </span>
          <span className="text-ink-2">
            Deals invoiced through a flagged branch cannot be handed over.
          </span>
        </div>
      )}

      {adding && (
        <div className="mb-4 flex flex-col gap-2 rounded-lg border border-line p-4">
          <label className="flex flex-col gap-1 text-body">
            <span className="font-medium text-ink">GSTIN</span>
            <Input
              value={gstin}
              placeholder="e.g. 27ABCDE1234F1Z5"
              onChange={(event) => setGstin(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-body">
            <span className="font-medium text-ink">Registered address (optional)</span>
            <Input value={address} onChange={(event) => setAddress(event.target.value)} />
          </label>
          <p className="text-caption text-ink-3">
            The state comes from the GSTIN, so there is nothing to choose. It must carry
            this company&apos;s PAN.
          </p>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="subtle" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button size="sm" variant="primary" onClick={submit} disabled={add.isPending}>
              Add
            </Button>
          </div>
        </div>
      )}

      {query.isLoading ? (
        <Skeleton className="h-20 rounded-lg" />
      ) : registrations.length === 0 ? (
        <EmptySection>
          No GST registrations recorded. A deal cannot name an invoicing branch until
          there is one.
        </EmptySection>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
          {registrations.map((registration) => (
            <Row
              key={registration.id}
              registration={registration}
              canEdit={canEdit}
              canFlag={canFlag}
              busy={deactivate.isPending || setFlag.isPending}
              onDeactivate={() =>
                deactivate.mutate(
                  { registrationId: registration.id },
                  { onSuccess: () => toast.success('Registration deactivated') },
                )
              }
              onSetFlag={(reason, flagged) =>
                setFlag.mutate(
                  { registrationId: registration.id, reason, flagged },
                  {
                    onSuccess: () =>
                      toast.success(flagged ? 'Branch flagged' : 'Flag lifted'),
                    onError: (error) =>
                      toast.error(
                        error instanceof Error ? error.message : 'Could not change the flag',
                      ),
                  },
                )
              }
            />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Row({
  registration,
  canEdit,
  canFlag,
  busy,
  onDeactivate,
  onSetFlag,
}: {
  registration: GstRegistration;
  canEdit: boolean;
  canFlag: boolean;
  busy: boolean;
  onDeactivate(): void;
  onSetFlag(reason: string, flagged: boolean): void;
}) {
  const [reasoning, setReasoning] = useState(false);
  const [reason, setReason] = useState('');
  const flagged = registration.flag_status === 'FLAGGED';
  // Optional in the generated type: the server always sends it, defaulting to `[]`.
  const alsoHeldBy = registration.also_held_by ?? [];

  return (
    <li className={`px-4 py-3 ${registration.active ? '' : 'bg-paper'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink">
              {/* The state identifies the branch; an unknown code says so rather than
                  showing nothing. */}
              {registration.state_name ??
                (registration.state_code
                  ? `State code ${registration.state_code}`
                  : 'Unknown state')}
            </span>
            {flagged && (
              <span className="inline-flex items-center gap-1 rounded-sm border border-attention/40 bg-attention-tint px-2 py-0.5 text-caption font-medium text-ink">
                <Icon.flagged size={12} className="text-attention" /> Flagged
              </span>
            )}
            {!registration.active && (
              <span className="rounded-sm border border-line-strong px-2 py-0.5 text-caption text-ink-2">
                Deactivated
                {registration.deactivated_at
                  ? ` ${formatDate(registration.deactivated_at)}`
                  : ''}
              </span>
            )}
          </p>
          <p className="mt-0.5 text-caption text-ink-2">{registration.gstin}</p>
          <p className="mt-0.5 text-caption text-ink-3">
            {STATUS_LABEL[registration.status]}
            {registration.address ? ` · ${registration.address}` : ''}
          </p>
          {flagged && registration.flag_reason && (
            <p className="mt-1 text-caption text-ink">
              <span className="font-medium">Why: </span>
              {registration.flag_reason}
            </p>
          )}
          {alsoHeldBy.length > 0 && (
            <p className="mt-1 text-caption text-ink-2">
              Also held by{' '}
              {alsoHeldBy.map((companyId, index) => (
                <span key={companyId}>
                  {index > 0 && ', '}
                  <Link to={paths.company(companyId)} className={LINK_CLASSES}>
                    another company
                  </Link>
                </span>
              ))}
              {flagged ? ' — flagging this branch does not flag theirs.' : '.'}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {/* Only when the server sent one: the link contains the GSTIN, so a role
              that sees it masked does not get it. */}
          {registration.verify_url && (
            <a
              href={registration.verify_url}
              target="_blank"
              rel="noreferrer"
              className={`inline-flex items-center gap-1 text-caption ${LINK_CLASSES}`}
            >
              Verify on the GST portal <Icon.external size={12} />
            </a>
          )}
          {canFlag && registration.active && !reasoning && (
            <Button size="sm" variant="subtle" onClick={() => setReasoning(true)}>
              {flagged ? (
                <>
                  <Icon.backgroundCheck size={14} /> Lift flag
                </>
              ) : (
                <>
                  <Icon.flagged size={14} /> Flag
                </>
              )}
            </Button>
          )}
          {canEdit && registration.active && (
            <Button size="sm" variant="subtle" onClick={onDeactivate} disabled={busy}>
              Deactivate
            </Button>
          )}
        </div>
      </div>

      {reasoning && (
        <div className="mt-3 flex flex-col gap-2 rounded-lg border border-line p-3">
          <label className="flex flex-col gap-1 text-body">
            <span className="font-medium text-ink">
              {flagged ? 'Why is the problem resolved?' : 'Why is this branch flagged?'}
            </span>
            <Input value={reason} onChange={(event) => setReason(event.target.value)} />
          </label>
          <p className="text-caption text-ink-3">
            {flagged
              ? 'Required: the flag’s own reason stops being readable on the row, and both stay in the company’s history.'
              : 'Required: this is what a blocked handover will say.'}
          </p>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="subtle" onClick={() => setReasoning(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={!reason.trim() || busy}
              onClick={() => {
                onSetFlag(reason.trim(), !flagged);
                setReasoning(false);
                setReason('');
              }}
            >
              {flagged ? 'Lift flag' : 'Flag branch'}
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}
