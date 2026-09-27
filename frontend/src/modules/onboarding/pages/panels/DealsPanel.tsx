/**
 * Deals — **owner: Developer 3B** (architecture §9.3, L3-05, L3-06, L3-11b).
 *
 * Was a seam that rendered `null` because deals did not exist. They do now
 * (migration 0018), so this is the company's deal list, the control that opens one,
 * and the way through to a deal and to the company's paperwork.
 *
 * **The shell is unchanged.** It already mounts this panel with
 * `{ customerId, isStaff }` — the one-file change its previous docstring promised.
 * `ExporterDetailPage.tsx` is Developer 2's and is not touched.
 *
 * **The stage is shown, never chosen here.** A deal moves through
 * `DealDetailPage`, which asks the server which moves it may offer
 * (`allowed_stage_moves`). A list is a place to see and to navigate.
 */

import { Handshake, Plus } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { EmptySection, FormPanel } from '@/components';

import { useCompanyDeals, useOpenDeal } from '../../hooks';
import type { DealListItem, DealStage } from '../../types';

/** The semantic status language, applied to a deal's stage. Neutral while it is
 * live, green once it has been handed over, muted once it is withdrawn — the same
 * grammar the lifecycle and verification chips use, so a reader learns it once. */
const STAGE_LOOK: Record<DealStage, { label: string; className: string }> = {
  OPEN: { label: 'Open', className: 'bg-surface-sunken text-ink-muted' },
  GATHERING_PAPERWORK: {
    label: 'Gathering paperwork',
    className: 'bg-stage-onboarding/10 text-stage-onboarding',
  },
  HANDED_OVER: {
    label: 'Handed over',
    className: 'bg-status-passed/10 text-status-passed',
  },
  WITHDRAWN: { label: 'Withdrawn', className: 'bg-surface-sunken text-ink-faint' },
};

export function DealStageChip({ stage }: { stage: DealStage }) {
  const look = STAGE_LOOK[stage];
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${look.className}`}
    >
      {look.label}
    </span>
  );
}

function OpenDealForm({
  customerId,
  onClose,
}: {
  customerId: string;
  onClose: () => void;
}) {
  const [reference, setReference] = useState('');
  const mutation = useOpenDeal(customerId);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await mutation.mutateAsync({ reference: reference.trim() });
      // Opening a deal also moves the conversation gauge, server-side (seam S1) —
      // `useOpenDeal` invalidates 3A's keys, so their panel re-reads it.
      toast.success('Deal opened — the conversation is now Ready now');
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not open the deal');
    }
  }

  return (
    <FormPanel title="Open a deal" onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div>
          <label
            htmlFor="deal-reference"
            className="mb-1 block text-xs font-medium text-ink-muted"
          >
            Reference
          </label>
          <input
            id="deal-reference"
            type="text"
            value={reference}
            required
            placeholder="Rotterdam shipment, March"
            onChange={(event) => setReference(event.target.value)}
            className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
          <p className="mt-1 text-xs text-ink-faint">
            A short label, so this deal is recognisable in a list. The buyer and the
            paperwork are added on the deal itself.
          </p>
        </div>
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={reference.trim() === '' || mutation.isPending}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {mutation.isPending ? 'Opening…' : 'Open deal'}
          </button>
        </div>
      </form>
    </FormPanel>
  );
}

function DealRow({ deal }: { deal: DealListItem }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <Link
          to={`/exporters/deals/${deal.id}`}
          className="font-medium text-ink hover:text-brand-600 hover:underline"
        >
          {deal.reference}
        </Link>
        <p className="mt-0.5 text-xs text-ink-muted">
          {deal.buyer_name ?? 'No buyer recorded yet'}
        </p>
      </div>
      <DealStageChip stage={deal.stage} />
    </li>
  );
}

export function DealsPanel({
  customerId,
  isStaff,
}: {
  customerId: string;
  isStaff: boolean;
}) {
  const [opening, setOpening] = useState(false);
  const { data, isLoading, isError } = useCompanyDeals(customerId);
  const deals = data?.deals ?? [];

  return (
    <section className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
            <Handshake size={15} className="text-ink-faint" />
            Deals
          </h2>
          <p className="text-xs text-ink-muted">
            What this exporter wants financed. A company may have any number, over
            time and at once.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to={`/exporters/${customerId}/documents`}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
          >
            Company documents
          </Link>
          {/* DEVELOPER reads the CRM and writes nothing, so it gets no action. */}
          {isStaff && !opening && (
            <button
              type="button"
              onClick={() => setOpening(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
            >
              <Plus size={13} /> Open a deal
            </button>
          )}
        </div>
      </div>

      {opening && (
        <OpenDealForm customerId={customerId} onClose={() => setOpening(false)} />
      )}

      {isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 2 }).map((_, index) => (
            <div
              key={index}
              className="h-12 animate-pulse rounded-lg bg-surface-sunken"
            />
          ))}
        </div>
      )}

      {isError && (
        <p className="text-sm text-status-failed">Could not load this company's deals.</p>
      )}

      {!isLoading && !isError && deals.length === 0 && (
        <EmptySection>
          No deals yet.
          {isStaff ? ' Open one when this exporter has something to finance.' : ''}
        </EmptySection>
      )}

      {deals.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {deals.map((deal) => (
            <DealRow key={deal.id} deal={deal} />
          ))}
        </ul>
      )}
    </section>
  );
}
