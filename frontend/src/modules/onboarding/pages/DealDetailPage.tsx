/**
 * One deal: its stage, its buyer, and its paperwork — **owner: Developer 3B**
 * (L3-11b).
 *
 * **The stage moves this page offers come from the server.** `allowed_stage_moves`
 * is what *this* deal may do next for *this* user (§7.5, deal contract §4.1), so
 * there is no copy of the stage graph in here and an illegal move is not offerable
 * rather than rejected after a click.
 *
 * **A blocked handover is explained, not offered.** When the A5 guard is unmet the
 * move is absent from that list and `handover_blocked_reason` says why — today,
 * always, that Developer 4's background check does not exist yet. Showing the reason
 * beats a button that returns 409.
 */

import { ArrowLeft, Handshake } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { DetailRow, EmptySection, FormPanel } from '@/components';
import { useCurrentUser } from '@/platform/auth';

import { DocumentList, DocumentUpload } from '../components';
import {
  useDeal,
  useDealDocuments,
  useSetDealBuyer,
  useTransitionDealStage,
  useUploadDealDocument,
} from '../hooks';
import type { DealStage, SetDealBuyerRequest } from '../types';

import { DealStageChip } from './panels/DealsPanel';

const STAGE_ACTION_LABEL: Record<DealStage, string> = {
  OPEN: 'Reopen',
  GATHERING_PAPERWORK: 'Start gathering paperwork',
  HANDED_OVER: 'Hand over to lending',
  WITHDRAWN: 'Withdraw',
};

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

function BuyerForm({
  dealId,
  customerId,
  initial,
  onClose,
}: {
  dealId: string;
  customerId?: string;
  initial: SetDealBuyerRequest | null;
  onClose: () => void;
}) {
  const mutation = useSetDealBuyer(dealId, customerId);
  const [form, setForm] = useState<SetDealBuyerRequest>(
    initial ?? { name: '', country: '' },
  );

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await mutation.mutateAsync({
        ...form,
        name: form.name.trim(),
        country: form.country.trim().toUpperCase(),
      });
      toast.success('Buyer saved');
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save the buyer');
    }
  }

  const field = (
    key: keyof SetDealBuyerRequest,
    label: string,
    required = false,
  ) => (
    <div>
      <label
        htmlFor={`buyer-${key}`}
        className="mb-1 block text-xs font-medium text-ink-muted"
      >
        {label}
      </label>
      <input
        id={`buyer-${key}`}
        type="text"
        required={required}
        value={(form[key] as string | null) ?? ''}
        onChange={(event) => setForm({ ...form, [key]: event.target.value })}
        className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
      />
    </div>
  );

  return (
    <FormPanel title={initial ? 'Edit buyer' : 'Add buyer'} onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          {field('name', 'Buyer name', true)}
          {field('country', 'Country (ISO code)', true)}
          {field('registration_number', 'Registration number')}
          {field('tax_id', 'Tax identifier')}
          {field('contact_email', 'Contact email')}
          {field('contact_phone', 'Contact phone')}
        </div>
        <p className="text-xs text-ink-faint">
          One buyer per deal. Saving replaces the details rather than adding a second
          buyer — a handover names one buyer, so two would be ambiguous.
        </p>
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={
              form.name.trim() === '' ||
              form.country.trim().length !== 2 ||
              mutation.isPending
            }
            className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {mutation.isPending ? 'Saving…' : 'Save buyer'}
          </button>
        </div>
      </form>
    </FormPanel>
  );
}

function StageMoves({
  dealId,
  customerId,
  moves,
  blockedReason,
}: {
  dealId: string;
  customerId?: string;
  moves: { to_stage: DealStage; reason_required: boolean }[];
  blockedReason: string | null;
}) {
  const mutation = useTransitionDealStage(dealId, customerId);
  const [pending, setPending] = useState<DealStage | null>(null);
  const [reason, setReason] = useState('');

  async function move(toStage: DealStage, withReason?: string) {
    // `HANDED_OVER` is terminal and announces the deal to the lending team, so it
    // is the one move worth a confirmation. A withdrawal already asks for a reason,
    // which is its own deliberate step.
    if (
      toStage === 'HANDED_OVER' &&
      !window.confirm(
        'Hand this deal to the lending team? This cannot be undone, and the deal ' +
          'and its documents are announced to them as they stand now.',
      )
    ) {
      return;
    }
    try {
      await mutation.mutateAsync({
        to_stage: toStage,
        ...(withReason ? { reason: withReason } : {}),
      });
      toast.success(`Deal moved to ${toStage.replaceAll('_', ' ').toLowerCase()}`);
      setPending(null);
      setReason('');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not move the deal');
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {moves.map((entry) => (
          <button
            key={entry.to_stage}
            type="button"
            onClick={() =>
              entry.reason_required ? setPending(entry.to_stage) : void move(entry.to_stage)
            }
            disabled={mutation.isPending}
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:text-ink disabled:opacity-40"
          >
            {STAGE_ACTION_LABEL[entry.to_stage]}
          </button>
        ))}
      </div>

      {/* A move that needs a reason asks for it before submitting, rather than
          showing a 422 afterwards. */}
      {pending !== null && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void move(pending, reason.trim());
          }}
          className="flex flex-col gap-2 rounded-lg border border-border bg-surface-subtle p-3"
        >
          <label
            htmlFor="stage-reason"
            className="text-xs font-medium text-ink-muted"
          >
            Why is this deal being withdrawn?
          </label>
          <textarea
            id="stage-reason"
            value={reason}
            rows={2}
            required
            onChange={(event) => setReason(event.target.value)}
            className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setPending(null)}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-ink-muted"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={reason.trim() === '' || mutation.isPending}
              className="rounded-lg bg-ink px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
            >
              Withdraw deal
            </button>
          </div>
        </form>
      )}

      {blockedReason !== null && (
        <p className="rounded-lg border border-border bg-surface-subtle px-3 py-2 text-xs text-ink-muted">
          <span className="font-medium text-ink">Not ready to hand over:</span>{' '}
          {blockedReason}
        </p>
      )}
    </div>
  );
}

export function DealDetailPage() {
  const { dealId } = useParams<{ dealId: string }>();
  const user = useCurrentUser();
  const isStaff = ['OPERATIONS', 'COMPLIANCE', 'ADMIN'].includes(user.role);

  const { data: deal, isLoading, isError } = useDeal(dealId);
  // A handed-over deal's paperwork is what the lending team was given, and a
  // withdrawn deal's is history: the server refuses both an upload and a buyer edit
  // on a terminal deal, so neither control is offered.
  const isClosed = deal?.stage === 'HANDED_OVER' || deal?.stage === 'WITHDRAWN';
  const documents = useDealDocuments(dealId);
  const upload = useUploadDealDocument(dealId ?? '');
  const [editingBuyer, setEditingBuyer] = useState(false);
  const [uploading, setUploading] = useState(false);

  if (isLoading) {
    return <div className="h-40 animate-pulse rounded-xl bg-surface-sunken" />;
  }
  if (isError || deal === undefined) {
    return (
      <p className="rounded-xl border border-border bg-surface p-6 text-sm text-status-failed">
        Could not load that deal.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link
          to={`/exporters/${deal.company_id}`}
          className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink"
        >
          <ArrowLeft size={14} /> Back to the company
        </Link>
      </div>

      <section className="rounded-xl border border-border bg-surface p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-semibold text-ink">
              <Handshake size={17} className="text-ink-faint" />
              {deal.reference}
            </h1>
            <p className="mt-1 flex items-center gap-2 text-sm text-ink-muted">
              <DealStageChip stage={deal.stage} />
              opened {formatDateTime(deal.created_at)}
            </p>
          </div>
        </div>

        <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2">
          {deal.handed_over_at && (
            <DetailRow label="Handed over at">{formatDateTime(deal.handed_over_at)}</DetailRow>
          )}
          {deal.withdrawal_reason && (
            <DetailRow label="Withdrawn because">{deal.withdrawal_reason}</DetailRow>
          )}
        </div>

        {isStaff && (
          <div className="mt-4 border-t border-border pt-4">
            <StageMoves
              dealId={deal.id}
              customerId={deal.company_id}
              moves={deal.allowed_stage_moves}
              blockedReason={deal.handover_blocked_reason}
            />
          </div>
        )}
      </section>

      <section className="rounded-xl border border-border bg-surface p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-ink">Buyer</h2>
            <p className="text-xs text-ink-muted">
              Who this exporter is selling to. Checks about a buyer are recorded
              against the buyer, never against the company.
            </p>
          </div>
          {isStaff && !editingBuyer && !isClosed && (
            <button
              type="button"
              onClick={() => setEditingBuyer(true)}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
            >
              {deal.buyer ? 'Edit buyer' : 'Add buyer'}
            </button>
          )}
        </div>

        {editingBuyer && (
          <BuyerForm
            dealId={deal.id}
            customerId={deal.company_id}
            initial={
              deal.buyer
                ? {
                    name: deal.buyer.name,
                    country: deal.buyer.country,
                    registration_number: deal.buyer.registration_number,
                    tax_id: deal.buyer.tax_id,
                    contact_email: deal.buyer.contact_email,
                    contact_phone: deal.buyer.contact_phone,
                  }
                : null
            }
            onClose={() => setEditingBuyer(false)}
          />
        )}

        {deal.buyer ? (
          <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2">
            <DetailRow label="Name">{deal.buyer.name}</DetailRow>
            <DetailRow label="Country">{deal.buyer.country}</DetailRow>
            <DetailRow label="Registration number">{deal.buyer.registration_number ?? '—'}</DetailRow>
            <DetailRow label="Tax identifier">{deal.buyer.tax_id ?? '—'}</DetailRow>
            <DetailRow label="Contact email">{deal.buyer.contact_email ?? '—'}</DetailRow>
            <DetailRow label="Contact phone">{deal.buyer.contact_phone ?? '—'}</DetailRow>
          </div>
        ) : (
          !editingBuyer && (
            <EmptySection>
              No buyer recorded yet. A deal cannot be handed over without one.
            </EmptySection>
          )
        )}
      </section>

      <section className="rounded-xl border border-border bg-surface p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-ink">Paperwork</h2>
            <p className="text-xs text-ink-muted">
              Documents for this deal. These are the ones a handover tells the lending
              team about.
            </p>
          </div>
          {isStaff && !isClosed && !uploading && (
            <button
              type="button"
              onClick={() => setUploading(true)}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
            >
              Upload a document
            </button>
          )}
        </div>

        {uploading && (
          <FormPanel title="Upload a document" onClose={() => setUploading(false)}>
            <DocumentUpload
              owner="DEAL"
              isUploading={upload.isPending}
              onUpload={(input) => upload.mutateAsync(input)}
              onDone={() => setUploading(false)}
            />
          </FormPanel>
        )}

        {isClosed && (
          <p className="mb-3 rounded-lg border border-border bg-surface-subtle px-3 py-2 text-xs text-ink-muted">
            {deal.stage === 'HANDED_OVER'
              ? 'This deal has been handed over. Its paperwork is what the lending team was given, so nothing more can be added.'
              : 'This deal was withdrawn. Its paperwork is kept as a record and nothing more can be added.'}
          </p>
        )}
        <DocumentList
          documents={documents.data?.documents ?? []}
          isLoading={documents.isLoading}
          emptyMessage="No documents on this deal yet."
        />
      </section>
    </div>
  );
}
