/**
 * A company's deals, in either role.
 *
 * Both sides are live: `as="seller"` lists the deals this company sells
 * on, `as="buyer"` the ones it buys on, each from
 * `GET /exporters/{id}/deals?as=...`.
 *
 * **Each row names the other party, never this company.** On the seller side that
 * is the buyer; on the buyer side it is the seller, which the server puts in the
 * same `buyer_name` field — "the other party on this deal". Repeating the company
 * whose page you are on in every row would say nothing, and the counterparty is
 * the only thing that tells the rows apart.
 *
 * **An empty buyer-side list is not the same as "no record yet".** A deal whose
 * buyer is still a legacy `deal_buyer` row does not appear here, because nothing
 * in the database yet says that buyer *is* this company — the buyer migration
 * is what makes it appear. So the empty state says that, rather than
 * implying the company has never bought anything. "No deals" and "we cannot see
 * them yet" must not look the same, which is the same reason
 * `handover_blocked_reason` exists.
 *
 * Deliberately **not** `DealsPanel`: that panel is the company page's Deals tab,
 * owns the "open a deal" control. This is a plain list
 * that renders wherever a company's deals in one role belong, panel or not.
 */

import { Link } from 'react-router-dom';

import { EmptySection, ErrorState, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import { useCompanyDeals } from '../hooks';
import { paths } from '../paths';
import type { DealListItem, DealSide } from '../types';

export interface CompanyDealsListProps {
  /** `exporter_profile.customer_id`. */
  companyId: string;
  /** Which side of the trade this company is on, in these deals. */
  as: DealSide;
}

function Row({ deal, as }: { deal: DealListItem; as: DealSide }) {
  return (
    <li>
      <Link
        to={paths.deal(deal.id)}
        className="group flex flex-wrap items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-paper"
      >
        <div className="min-w-0">
          <span className="font-medium text-ink group-hover:text-ink">
            {deal.reference}
          </span>
          <p className="mt-0.5 text-caption text-ink-2">
            {/* The other party, whichever side this company is on: the server puts
                it in `buyer_name` both ways. The fallback differs because
                the two gaps mean different things — a seller's deal may genuinely
                have no buyer recorded yet, while a deal reached through
                `buyer_company_id` always has a seller. */}
            {`${deal.buyer_name ?? (as === 'seller' ? 'No buyer recorded yet' : 'Seller unknown')} · opened ${formatDate(deal.created_at)}`}
          </p>
        </div>
        <Icon.caretRight size={15} className="text-ink-3" />
      </Link>
    </li>
  );
}

export function CompanyDealsList({ companyId, as }: CompanyDealsListProps) {
  // `as` goes to the server, which keeps the two sides as two queries — a company
  // can be the seller on one deal and the buyer on another, and one list mixing
  // them would read differently row by row.
  const query = useCompanyDeals(companyId, { as });

  if (query.isLoading) return <Skeleton className="h-20 rounded-lg" />;
  // A failed read is not "no deals": the two must not look the same.
  if (query.isError) {
    return (
      <ErrorState title="Couldn't load this company's deals." onRetry={() => void query.refetch()} />
    );
  }

  const deals = query.data?.deals ?? [];
  if (deals.length === 0) {
    return (
      <EmptySection>
        {as === 'seller'
          ? 'No deals where this company is the seller.'
          : 'No deals where this company is the buyer.'}
      </EmptySection>
    );
  }

  return (
    <ul className="divide-y divide-line">
      {deals.map((deal) => (
        <Row key={deal.id} deal={deal} as={as} />
      ))}
    </ul>
  );
}
