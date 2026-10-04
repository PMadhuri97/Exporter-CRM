/**
 * What these two companies have traded before — **owner: Developer 3**
 * (allocation F3 and task 3.22, plan P5-7).
 *
 * The F3 stub's props are unchanged, so task 2.11's mounting on the deal page did not
 * have to move: `{ sellerId, buyerId, dealId }` still, and `dealId` still optional for
 * the company page.
 *
 * What this panel adds over the list of invoices it renders:
 *
 * - **"A → B", the way the target diagram reads it.** Ordered, not symmetric: this is
 *   what the seller invoiced the buyer, and the other direction is a different
 *   relationship with different invoices and different risk. The arrow is the point.
 * - **No relationship is a real answer**, and a different one from no invoices. Every
 *   deal recorded since task 3.18 has a relationship, so a pair without one is a deal
 *   the buyer migration has not reached (P4-6) or whose relationship backfill has not
 *   run (P5-5) — not two companies that have never traded. The empty state says which.
 *
 * It asks for the pair through `useTradeRelationshipForPair`, which filters the
 * seller's list rather than calling a route per pair: the list is the request the
 * seller's own company page makes anyway, so the two share one cache entry.
 *
 * It renders **no heading of its own**: both mount sites wrap it in a `Panel` titled
 * "Trade history", the grammar every other section on those pages uses, and the stub's
 * own heading would have read twice. The props are untouched — what the F3 stub fixed
 * was the mounting, not the markup.
 */

import { Link } from 'react-router-dom';

import { EmptySection, ErrorState, Skeleton } from '@/components';
import { Icon } from '@/design/icons';

import { useTradeRelationshipForPair } from '../hooks';
import { paths } from '../paths';
import type { TradeCounterparty } from '../types';

import { TradeInvoiceList } from './TradeInvoiceList';

export interface TradeHistoryPanelProps {
  /** The selling company's `customer_id`. */
  sellerId: string;
  /** The buying company's `customer_id`. */
  buyerId: string;
  /** The deal being viewed, when this is mounted on one — its invoices are marked. */
  dealId?: string;
}

/** "A → B". A counterparty with no name is a company with no name rather than a bug:
 * a buyer the migration created from a `deal_buyer` row may have had only a tax id. */
function Pair({ seller, buyer }: { seller: TradeCounterparty; buyer: TradeCounterparty }) {
  return (
    <p className="text-sm text-ink-2">
      <Link
        to={paths.company(seller.company_id)}
        className="font-medium text-ink hover:underline"
      >
        {seller.name ?? 'Unnamed company'}
      </Link>
      <span aria-hidden className="mx-2 text-ink-3">
        →
      </span>
      <Link to={paths.company(buyer.company_id)} className="font-medium text-ink hover:underline">
        {buyer.name ?? 'Unnamed company'}
      </Link>
    </p>
  );
}

export function TradeHistoryPanel({ sellerId, buyerId, dealId }: TradeHistoryPanelProps) {
  const pair = useTradeRelationshipForPair(sellerId, buyerId);

  if (pair.isLoading) return <Skeleton className="h-20 rounded-lg" />;
  // A failed read is not an empty history, and the two never look the same here.
  if (pair.isError) {
    return (
      <ErrorState
        title="Couldn't load what these two have traded."
        onRetry={() => void pair.refetch()}
      />
    );
  }

  // `null` is "these two have no relationship"; `undefined` would still be loading,
  // which the check above has already handled.
  if (!pair.data) {
    return (
      <div data-testid="trade-history-panel">
        <EmptySection>
          No trade relationship between these two companies yet. Deals recorded before
          trade history are linked by the buyer migration and the relationship backfill.
        </EmptySection>
      </div>
    );
  }

  const relationship = pair.data;

  return (
    <div className="flex flex-col gap-3" data-testid="trade-history-panel">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <Pair seller={relationship.seller} buyer={relationship.buyer} />
        <Link
          to={paths.company(relationship.buyer.company_id)}
          className="flex items-center gap-1 text-xs font-medium text-ink hover:underline"
        >
          {relationship.buyer.name ?? 'The buyer'}
          <Icon.caretRight size={13} />
        </Link>
      </div>

      <TradeInvoiceList
        relationshipId={relationship.id}
        dealId={dealId}
        emptyMessage="These two are on a deal together, but no invoice has been recorded against them yet."
      />
    </div>
  );
}
