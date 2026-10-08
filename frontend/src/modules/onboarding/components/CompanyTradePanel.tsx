/**
 * Who this company has traded with.
 *
 * The company-page half of trade history. `TradeHistoryPanel` answers "what have
 * *these two* traded", which is the deal page's question; this one answers "who does
 * this company trade with, and how did it go", which is what you ask when the company
 * is the subject and no deal is.
 *
 * **Two sides, two lists**, as everywhere else in this module (and the trade
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
 * Counterparty identifiers are **not served here for any role**: a row is a
 * name, a country and a pipeline status, and the rest is on that company's own page
 * where its masking governs it. So there is nothing to mask in this component, which
 * is the point of the response carrying no identifiers in the first place.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';

import { EmptySection, ErrorState, Skeleton, Tag } from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import { useTradeRelationships } from '../hooks';
import { paths } from '../paths';
import type { DealSide, TradeRelationship } from '../types';

import { RecordPastTradeForm } from './RecordPastTradeForm';
import { TradeInvoiceList } from './TradeInvoiceList';

export interface CompanyTradePanelProps {
  /** `exporter_profile.customer_id`. */
  companyId: string;
  /** Which side of the trade this company is on, in these relationships. */
  as: DealSide;
  /**
   * Whether this viewer may record trade (OPERATIONS, COMPLIANCE, ADMIN).
   * DEVELOPER reads trade history and writes nothing, so it gets no control.
   */
  canRecord?: boolean;
}

/** The other party, never this company: repeating the company whose page you are on
 * in every row would say nothing, and the counterparty is what tells rows apart. */
function counterparty(relationship: TradeRelationship, as: DealSide) {
  return as === 'seller' ? relationship.buyer : relationship.seller;
}

function Row({
  relationship,
  as,
  canRecord,
}: {
  relationship: TradeRelationship;
  as: DealSide;
  canRecord: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const other = counterparty(relationship, as);
  const count = relationship.invoice_count;

  return (
    <li>
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <Link
              to={paths.company(other.company_id)}
              className="font-medium text-ink hover:text-ink hover:underline"
            >
              {other.name ?? 'Unnamed company'}
            </Link>
            {/* A counterparty that is not in the sales pipeline is usually a company
                created from a deal's buyer. Worth saying: its page has no
                qualification or conversation, and that is by design, not a gap. */}
            {other.pipeline_status === 'NOT_IN_PIPELINE' && (
              <Tag tone="idle" className="text-ink-3">
                Not in the pipeline
              </Tag>
            )}
          </p>
          <p className="mt-0.5 text-caption text-ink-2">
            {`${other.country ?? 'Country not recorded'} · ${
              count === 0
                ? 'No invoices recorded'
                : `${count} invoice${count === 1 ? '' : 's'}`
            } · since ${formatDate(relationship.created_at)}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {/* Past trade: an invoice with no deal, recorded against this
              pair. Staff only; the relationship is this row. */}
          {canRecord && !recording ? (
            <button
              type="button"
              onClick={() => setRecording(true)}
              className="text-caption font-medium text-ink hover:underline"
            >
              Record past invoice
            </button>
          ) : null}
          {/* Nothing to open when there are no invoices: the row already says so, and a
              control that reveals an empty state is a control that wasted a click. The
              counterparty's name is already its link, so there is no second one. */}
          {count > 0 && (
            <button
              type="button"
              onClick={() => setOpen((was) => !was)}
              className="flex items-center gap-1 text-caption font-medium text-ink hover:underline"
              aria-expanded={open}
            >
              {open ? 'Hide invoices' : 'Invoices'}
              {open ? <Icon.caretDown size={13} /> : <Icon.caretRight size={13} />}
            </button>
          )}
        </div>
      </div>

      {recording && (
        <div className="px-4 pb-4">
          <RecordPastTradeForm
            relationshipId={relationship.id}
            counterpartyName={other.name ?? 'this company'}
            onCancel={() => setRecording(false)}
            onDone={() => {
              setRecording(false);
              setOpen(true);
            }}
          />
        </div>
      )}

      {open && (
        <div className="px-4 pb-4">
          <TradeInvoiceList relationshipId={relationship.id} />
        </div>
      )}
    </li>
  );
}

export function CompanyTradePanel({ companyId, as, canRecord = false }: CompanyTradePanelProps) {
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
        {/* A relationship appears when a deal records its buyer company, so past trade
            can be added once a deal names the other company. */}
        {as === 'seller'
          ? 'Nobody recorded as a buyer from this company yet.'
          : 'Nobody recorded as a seller to this company yet.'}
      </EmptySection>
    );
  }

  return (
    <ul className="divide-y divide-line">
      {relationships.map((relationship) => (
        <Row key={relationship.id} relationship={relationship} as={as} canRecord={canRecord} />
      ))}
    </ul>
  );
}
