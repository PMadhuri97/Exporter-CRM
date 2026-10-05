/**
 * One relationship's invoices and what became of them.
 *
 * Shared by both places trade history appears: the deal page's `TradeHistoryPanel`,
 * which is about one pair, and the company page's `CompanyTradePanel`, which lists
 * every pair the company is part of and opens one at a time. The two screens ask
 * different questions and this is the answer they share, so it lives here rather than
 * being written twice and drifting.
 *
 * Distinctions the list has to keep, because it is the only place they are visible:
 *
 * - **No outcome is not `UNKNOWN`.** Nobody has followed this invoice up, versus
 *   somebody did and could not say. `TradeOutcomeChip` holds the line.
 * - **Nothing is totalled**. Amounts are stored in their own currency
 *   and never converted, so a sum would need a rate that does not exist. Each row
 *   carries its own currency instead.
 * - **Superseded outcomes stay visible.** An invoice corrected from "Paid" to
 *   "Disputed" is a different thing from one disputed from the start.
 */

import { useState } from 'react';

import { EmptySection, ErrorState, Skeleton, Tag } from '@/components';
import { formatDate } from '@/lib/format';

import { useTradeInvoice, useTradeRelationship } from '../hooks';
import type { TradeInvoice, TradeOutcome } from '../types';

import { EvidenceList } from './EvidenceList';
import { NoOutcomeChip, TradeOutcomeChip } from './TradeOutcomeChip';

export interface TradeInvoiceListProps {
  /** The relationship whose invoices these are. */
  relationshipId: string;
  /** The deal being viewed, when there is one — its invoices are marked. */
  dealId?: string;
  /** Shown when the relationship exists but carries no invoice. */
  emptyMessage?: string;
}

/**
 * Every outcome ever recorded for one invoice, oldest first.
 *
 * `is_current` comes from the server — the live outcome is the one nothing supersedes,
 * not the newest timestamp, because two rows written in one transaction share a
 * timestamp. Picking "newest" here would show the wrong one exactly when a correction
 * was made in the same breath as the thing it corrects.
 */
function OutcomeChain({ outcomes }: { outcomes: TradeOutcome[] }) {
  return (
    <ol className="flex flex-col gap-3">
      {outcomes.map((outcome) => (
        <li key={outcome.id} className={outcome.is_current ? undefined : 'opacity-60'}>
          <div className="flex flex-wrap items-center gap-2">
            <TradeOutcomeChip
              paymentStatus={outcome.payment_status}
              proofStatus={outcome.proof_status}
            />
            {outcome.amount_paid && (
              <span className="text-caption tabular-nums text-ink-2">
                {outcome.amount_paid} paid
              </span>
            )}
            {!outcome.is_current && <span className="text-caption text-ink-3">Superseded</span>}
          </div>
          <p className="mt-0.5 text-caption text-ink-3">
            {`${outcome.recorded_by ?? 'Unknown'} · ${formatDate(outcome.recorded_at)}`}
          </p>
          {/* The design asks for `EvidenceList` here. An outcome's references are stored
              in verification's `{type, ref}` shape, which is what this list reads. */}
          <EvidenceList note={outcome.evidence_note} refs={outcome.evidence_refs ?? []} />
        </li>
      ))}
    </ol>
  );
}

/**
 * One invoice, its current outcome, and its chain on demand.
 *
 * The chain is fetched only once opened (the id is withheld from `useTradeInvoice`
 * until then): a relationship with thirty invoices would otherwise make thirty
 * requests for something nobody asked to see. The current outcome is already on the
 * row, so the closed state needs nothing.
 */
function InvoiceRow({ invoice, isThisDeal }: { invoice: TradeInvoice; isThisDeal: boolean }) {
  const [open, setOpen] = useState(false);
  const chain = useTradeInvoice(open ? invoice.id : undefined);
  const outcome = invoice.current_outcome ?? null;

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink">{invoice.invoice_number}</span>
            {isThisDeal && (
              <Tag tone="progress" title="Raised on the deal you are looking at">
                This deal
              </Tag>
            )}
          </p>
          <p className="mt-0.5 text-caption text-ink-2">
            {/* Amount and currency together, never converted. The amount is a
                string because the server sends `Numeric` as one; it is shown as sent
                and never parsed. */}
            <span className="font-medium tabular-nums text-ink">
              {invoice.amount} {invoice.currency}
            </span>
            {` · invoiced ${formatDate(invoice.invoice_date)}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {outcome ? (
            <TradeOutcomeChip
              paymentStatus={outcome.payment_status}
              proofStatus={outcome.proof_status}
            />
          ) : (
            <NoOutcomeChip />
          )}
          {/* Only an invoice with an outcome has a chain worth opening. */}
          {outcome && (
            <button
              type="button"
              onClick={() => setOpen((was) => !was)}
              className="text-caption font-medium text-ink hover:underline"
              aria-expanded={open}
            >
              {open ? 'Hide history' : 'Outcome history'}
            </button>
          )}
        </div>
      </div>

      {open && (
        <div className="mt-3 border-l-2 border-line pl-3">
          {chain.isLoading && <Skeleton className="h-12 rounded" />}
          {chain.isError && (
            <ErrorState
              title="Couldn't load this invoice's outcomes."
              onRetry={() => void chain.refetch()}
            />
          )}
          {chain.data && <OutcomeChain outcomes={chain.data.outcomes} />}
        </div>
      )}
    </li>
  );
}

export function TradeInvoiceList({
  relationshipId,
  dealId,
  emptyMessage,
}: TradeInvoiceListProps) {
  const detail = useTradeRelationship(relationshipId);

  if (detail.isLoading) return <Skeleton className="h-16 rounded-lg" />;
  // A failed read is not "no invoices": the two must not look the same.
  if (detail.isError) {
    return (
      <ErrorState
        title="Couldn't load this relationship's invoices."
        onRetry={() => void detail.refetch()}
      />
    );
  }

  const invoices = detail.data?.invoices ?? [];
  if (invoices.length === 0) {
    return (
      <EmptySection>
        {emptyMessage ??
          // The normal state of a deal not settled yet, and of a withdrawn one that
          // never will be.
          'No invoice has been recorded against these two companies yet.'}
      </EmptySection>
    );
  }

  return (
    <ul className="divide-y divide-line rounded-lg border border-line">
      {invoices.map((invoice) => (
        <InvoiceRow
          key={invoice.id}
          invoice={invoice}
          isThisDeal={Boolean(dealId) && invoice.deal_id === dealId}
        />
      ))}
    </ul>
  );
}
