/**
 * Deals — **owner: Developer 3B** (architecture §9.3, L3-05, L3-06, L3-11b).
 *
 * The company's deal list, the control that opens one, and the way through to
 * a deal. Shown on the company page's Deals tab.
 *
 * **The stage is shown, never chosen here.** A deal moves on `DealDetailPage`,
 * which asks the server which moves it may offer (`allowed_stage_moves`). A list
 * is a place to see and to navigate.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Button, buttonClasses, EmptySection, Panel, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import { OpenDealForm, StageRoute } from '../../components';
import { useCompanyDeals } from '../../hooks';
import { paths } from '../../paths';
import type { DealListItem } from '../../types';

function DealRow({ deal }: { deal: DealListItem }) {
  return (
    <li>
      <Link
        to={paths.deal(deal.id)}
        className="group flex flex-wrap items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-paper"
      >
        <div className="min-w-0">
          <span className="font-medium text-ink group-hover:text-ink">{deal.reference}</span>
          <p className="mt-0.5 text-xs text-ink-2">
            {deal.buyer_name ?? 'No buyer recorded yet'} · opened {formatDate(deal.created_at)}
          </p>
        </div>
        <span className="flex items-center gap-2">
          <StageRoute stage={deal.stage} compact />
          <Icon.caretRight size={15} className="text-ink-3" />
        </span>
      </Link>
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
  // The server says whether this viewer may open a deal here (§7.5): a staff role,
  // and a company that is a PROSPECT or CUSTOMER — a LEAD is refused.
  const canOpen = data?.can_open_deal ?? false;

  return (
    <Panel
      title="Deals"
      description="What this company wants financed. A company may have any number, over time and at once."
      actions={
        <>
          <Link to={paths.company(customerId, 'documents')} className={buttonClasses({ size: 'sm' })}>
            <Icon.document size={14} />
            Company documents
          </Link>
          {/* Offered only where the server would accept it: never to DEVELOPER, and
              never on a LEAD. */}
          {canOpen && !opening && (
            <Button size="sm" variant="primary" onClick={() => setOpening(true)}>
              <Icon.add size={14} /> Open a deal
            </Button>
          )}
        </>
      }
    >
      {opening && <OpenDealForm customerId={customerId} onClose={() => setOpening(false)} />}

      {isLoading && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-12 rounded-lg" />
          <Skeleton className="h-12 rounded-lg" />
        </div>
      )}

      {isError && <p className="text-sm text-negative">Could not load this company's deals.</p>}

      {!isLoading && !isError && deals.length === 0 && (
        <EmptySection>
          No deals yet.
          {canOpen ? ' Open one when this company has something to finance.' : ''}
          {isStaff && !canOpen ? ' A deal can be opened once the company has been qualified.' : ''}
        </EmptySection>
      )}

      {deals.length > 0 && (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
          {deals.map((deal) => (
            <DealRow key={deal.id} deal={deal} />
          ))}
        </ul>
      )}
    </Panel>
  );
}
