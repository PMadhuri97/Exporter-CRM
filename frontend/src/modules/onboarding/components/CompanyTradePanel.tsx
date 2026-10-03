/**
 * Who this company has traded with — **owner: Developer 3** (task 3.22, plan P5-7).
 *
 * The company-page half of trade history. `TradeHistoryPanel` answers "what have
 * *these two* traded", which is the deal page's question; this one answers "who does
 * this company trade with, and how did it go", which is what you ask when the company
 * is the subject and no deal is.
 *
 * **Two sides, two lists**, as everywhere else in this module (task 2.7, and the trade
 * routes' own `as` parameter): who the company sells to, and who it buys from. One
 * list mixing them would read differently row by row — the same counterparty can be on
 * both sides, and "we invoiced them" and "they invoiced us" carry opposite risk.
 *
 * **One relationship opens at a time.** The invoices are a request per relationship,
 * and a company with twenty counterparties would otherwise make twenty on load for
 * rows nobody has looked at. `invoice_count` is on every row already, so the closed
 * state still says whether there is anything under it — which is the thing a reader
 * scans for.
 *
 * Counterparty identifiers are **not served here for any role** (IQ-19): a row is a
 * name, a country and a pipeline status, and the rest is on that company's own page
 * where D8's masking governs it. So there is nothing to mask in this component, which
 * is the point of the response carrying no identifiers in the first place.
 */

import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Chip, EmptySection, ErrorState, Skeleton } from '@/components';
import { formatDate } from '@/lib/format';

import { useTradeRelationships } from '../hooks';
import { paths } from '../paths';
import type { DealSide, TradeRelationship } from '../types';

import { TradeInvoiceList } from './TradeInvoiceList';

export interface CompanyTradePanelProps {
  /** `exporter_profile.customer_id`. */
  companyId: string;
  /** Which side of the trade this company is on, in these relationships. */
  as: DealSide;
}

/** The other party, never this company: repeating the company whose page you are on
 * in every row would say nothing, and the counterparty is what tells rows apart. */
function counterparty(relationship: TradeRelationship, as: DealSide) {
  return as === 'seller' ? relationship.buyer : relationship.seller;
}

function Row({ relationship, as }: { relationship: TradeRelationship; as: DealSide }) {
  const [open, setOpen] = useState(false);
  const other = counterparty(relationship, as);
  const count = relationship.invoice_count;

  return (
    <li>
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <Link
              to={paths.company(other.company_id)}
              className="font-medium text-ink hover:text-brand-600 hover:underline"
            >
              {other.name ?? 'Unnamed company'}
            </Link>
            {/* A counterparty that is not in the sales pipeline is usually a company
                created from a deal's buyer. Worth saying: its page has no
                qualification or conversation, and that is by design, not a gap. */}
            {other.pipeline_status === 'NOT_IN_PIPELINE' && (
              <Chip tone="neutral" className="text-ink-faint">
                Not in the pipeline
              </Chip>
            )}
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">
            {`${other.country ?? 'Country not recorded'} · ${
              count === 0
                ? 'No invoices recorded'
                : `${count} invoice${count === 1 ? '' : 's'}`
            } · since ${formatDate(relationship.created_at)}`}
          </p>
        </div>
        {/* Nothing to open when there are no invoices: the row already says so, and a
            control that reveals an empty state is a control that wasted a click. */}
        {count > 0 ? (
          <button
            type="button"
            onClick={() => setOpen((was) => !was)}
            className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
            aria-expanded={open}
          >
            {open ? 'Hide invoices' : 'Invoices'}
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : (
          <Link
            to={paths.company(other.company_id)}
            className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
          >
            Open company
            <ChevronRight size={13} />
          </Link>
        )}
      </div>

      {open && (
        <div className="px-4 pb-4">
          <TradeInvoiceList relationshipId={relationship.id} />
        </div>
      )}
    </li>
  );
}

export function CompanyTradePanel({ companyId, as }: CompanyTradePanelProps) {
  const query = useTradeRelationships(companyId, as);

  if (query.isLoading) return <Skeleton className="h-20 rounded-lg" />;
  // A failed read is not "no relationships": the two must not look the same.
  if (query.isError) {
    return (
      <ErrorState
        title="Couldn't load this company's trade history."
        onRetry={() => void query.refetch()}
      />
    );
  }

  const relationships = query.data?.relationships ?? [];
  if (relationships.length === 0) {
    return (
      <EmptySection>
        {as === 'seller'
          ? // Not "has never sold anything": a relationship appears when a deal
            // records its buyer company, so a company whose deals predate the buyer
            // migration (P4-6) and the relationship backfill (P5-5) has none yet.
            'Nobody recorded as a buyer from this company yet. Deals recorded before trade history are linked by the buyer migration and the relationship backfill.'
          : 'Nobody recorded as a seller to this company yet.'}
      </EmptySection>
    );
  }

  return (
    <ul className="divide-y divide-border">
      {relationships.map((relationship) => (
        <Row key={relationship.id} relationship={relationship} as={as} />
      ))}
    </ul>
  );
}
