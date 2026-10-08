/**
 * A company's Deals tab, as two views instead of four stacked lists:
 *
 * - **Deals** — the deals this company sells on (where a deal is opened), and, only if
 *   it has any, the deals it buys on. A company can be a seller on one deal and a buyer
 *   on another, so the two stay apart; the second list does not appear just to say it
 *   is empty.
 * - **Trade** — what came of it, by counterparty: who this company has invoiced, and,
 *   only if anyone has, who has invoiced it. Invoice by invoice, never totalled.
 *
 * Each counterparty appears once per view. Before, a buyer showed in the deal list and
 * again in the trade list right below it, which read as a duplicate. The view is kept
 * in the URL (`?deals=trade`), so a link can open either.
 */

import { Panel, Segmented, Skeleton, useSearchParamState } from '@/components';

import { CompanyDealsList, CompanyTradePanel } from '../../components';
import { useCompanyDeals, useTradeRelationships } from '../../hooks';

import { DealsPanel } from './DealsPanel';

type View = 'deals' | 'trade';
const VIEWS: readonly View[] = ['deals', 'trade'];

/** The deals this company buys on — rendered only when there are some. */
function BuyingDeals({ customerId }: { customerId: string }) {
  const query = useCompanyDeals(customerId, { as: 'buyer' });
  if (query.isLoading) return <Skeleton className="h-16 rounded-lg" />;
  if (!query.isError && (query.data?.deals ?? []).length === 0) return null;
  return (
    <Panel title="Deals it buys on">
      <CompanyDealsList companyId={customerId} as="buyer" />
    </Panel>
  );
}

/** Who has invoiced this company — rendered only when anyone has. */
function BoughtFrom({ customerId, canRecord }: { customerId: string; canRecord: boolean }) {
  const query = useTradeRelationships(customerId, 'buyer');
  if (query.isLoading) return <Skeleton className="h-16 rounded-lg" />;
  if (!query.isError && (query.data?.relationships ?? []).length === 0) return null;
  return (
    <Panel title="Bought from">
      <CompanyTradePanel companyId={customerId} as="buyer" canRecord={canRecord} />
    </Panel>
  );
}

export function CompanyDealsTab({ customerId, isStaff }: { customerId: string; isStaff: boolean }) {
  const [view, setView] = useSearchParamState<View>('deals', VIEWS, 'deals');

  return (
    <div className="flex flex-col gap-6">
      <Segmented
        label="Deals or trade"
        value={view}
        onValueChange={setView}
        options={[
          { value: 'deals', label: 'Deals' },
          { value: 'trade', label: 'Trade' },
        ]}
        className="self-start"
      />
      {view === 'deals' ? (
        <>
          <DealsPanel customerId={customerId} isStaff={isStaff} />
          <BuyingDeals customerId={customerId} />
        </>
      ) : (
        <>
          <Panel title="Sold to">
            <CompanyTradePanel companyId={customerId} as="seller" canRecord={isStaff} />
          </Panel>
          <BoughtFrom customerId={customerId} canRecord={isStaff} />
        </>
      )}
    </div>
  );
}
