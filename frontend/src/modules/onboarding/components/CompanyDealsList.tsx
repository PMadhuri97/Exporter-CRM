/**
 * A company's deals, in either role — **owner: Developer 2** (allocation F2,
 * plan P4-8).
 *
 * **This is the F2 stub.** Its props are final, so Developer 3 can mount it on
 * the company page now (`as="seller"` and `as="buyer"`), and task 2.7 fills the
 * body against `GET /exporters/{id}/deals?as=buyer`. Nothing about the mounting
 * changes when it does.
 *
 * `as="seller"` already works, because `GET /exporters/{id}/deals` is the list
 * that exists today. `as="buyer"` has no endpoint yet, so it says so rather than
 * showing an empty list — "this company has no deals as a buyer" and "we cannot
 * answer that yet" must not look the same, which is the same reason
 * `handover_blocked_reason` exists.
 *
 * Deliberately **not** `DealsPanel`: that panel is the company page's Deals tab,
 * owns the "open a deal" control, and is Developer 3B's. This is a plain list
 * that renders wherever a company's deals in one role belong, panel or not.
 */

import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';

import { EmptySection, Skeleton } from '@/components';
import { formatDate } from '@/lib/format';

import { useCompanyDeals } from '../hooks';
import { paths } from '../paths';
import type { DealListItem } from '../types';

export interface CompanyDealsListProps {
  /** `exporter_profile.customer_id`. */
  companyId: string;
  /** Which side of the trade this company is on, in these deals. */
  as: 'seller' | 'buyer';
}

function Row({ deal, as }: { deal: DealListItem; as: 'seller' | 'buyer' }) {
  return (
    <li>
      <Link
        to={paths.deal(deal.id)}
        className="group flex flex-wrap items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-surface-subtle"
      >
        <div className="min-w-0">
          <span className="font-medium text-ink group-hover:text-brand-600">
            {deal.reference}
          </span>
          <p className="mt-0.5 text-xs text-ink-muted">
            {/* As the seller, the counterparty worth naming is the buyer. As the
                buyer it is the seller, which task 2.7's response carries; until
                then the row says only when it was opened. */}
            {as === 'seller'
              ? `${deal.buyer_name ?? 'No buyer recorded yet'} · opened ${formatDate(deal.created_at)}`
              : `Opened ${formatDate(deal.created_at)}`}
          </p>
        </div>
        <ChevronRight size={15} className="text-ink-faint" />
      </Link>
    </li>
  );
}

export function CompanyDealsList({ companyId, as }: CompanyDealsListProps) {
  // The buyer-side read is task 2.7; asking for it now would silently return the
  // seller's deals, which is worse than saying nothing.
  const query = useCompanyDeals(as === 'seller' ? companyId : undefined);

  if (as === 'buyer') {
    return (
      <EmptySection>
        Deals where this company is the buyer are not listed yet. They arrive with the
        buyer migration.
      </EmptySection>
    );
  }
  if (query.isLoading) return <Skeleton className="h-20 rounded-lg" />;

  const deals = query.data?.deals ?? [];
  if (deals.length === 0) {
    return <EmptySection>No deals where this company is the seller.</EmptySection>;
  }

  return (
    <ul className="divide-y divide-border">
      {deals.map((deal) => (
        <Row key={deal.id} deal={deal} as={as} />
      ))}
    </ul>
  );
}
