/**
 * What these two companies have traded before — **owner: Developer 3**
 * (allocation F3, plan P5-7).
 *
 * **This is the F3 stub.** Its props are final, so Developer 2 can mount it on the
 * deal page now (task 2.11) and Developer 3 can mount it on the company page, and
 * task 3.22 fills the body in without either mounting changing.
 *
 * It shows an honest empty state rather than fake rows: the trade relationship
 * (3.18), the invoices and their outcomes (3.19) and the read routes (3.20) do not
 * exist yet, so there is nothing to show and nothing to ask for. A panel that
 * rendered invented invoices would be worse than one that says so.
 *
 * `dealId` is optional because the panel appears in two places: on a deal, where the
 * current deal is one row among the pair's history and worth marking as "this deal";
 * and on a company page, where there is no current deal.
 */

import { History } from 'lucide-react';

import { EmptySection } from '@/components';

export interface TradeHistoryPanelProps {
  /** The selling company's `customer_id`. */
  sellerId: string;
  /** The buying company's `customer_id`. */
  buyerId: string;
  /** The deal being viewed, when this is mounted on one — highlighted in the list. */
  dealId?: string;
}

export function TradeHistoryPanel(props: TradeHistoryPanelProps) {
  // `props` is deliberately unread: there is nothing to look up with the ids until
  // task 3.22, and rendering them would read as a half-built screen rather than one
  // waiting on a feature. They are in the type because the mounting is what F3 fixes.
  void props;
  return (
    <div className="flex flex-col gap-2" data-testid="trade-history-panel">
      <p className="flex items-center gap-2 text-sm font-medium text-ink">
        <History size={15} className="text-ink-faint" />
        Trade history
      </p>
      <EmptySection>
        What these two companies have invoiced and settled before is not recorded yet.
        It arrives with trade history.
      </EmptySection>
    </div>
  );
}
