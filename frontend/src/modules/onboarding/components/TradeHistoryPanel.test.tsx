import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';

import { getTradeInvoice, getTradeRelationship, listTradeRelationships } from '../api';
import type {
  TradeInvoice,
  TradeInvoiceDetail,
  TradeOutcome,
  TradeRelationship,
  TradeRelationshipDetail,
  TradeRelationshipList,
} from '../types';

import { TradeHistoryPanel } from './TradeHistoryPanel';

vi.mock('../api', () => ({
  listTradeRelationships: vi.fn(),
  getTradeRelationship: vi.fn(),
  getTradeInvoice: vi.fn(),
  // `EvidenceList`, which the outcome chain renders, reaches for these two.
  getDocument: vi.fn(),
  fetchDocumentBlob: vi.fn(),
  createDownloadLink: vi.fn(),
}));

const SELLER = 'ssssssss-ssss-4sss-8sss-ssssssssssss';
const BUYER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const OTHER_BUYER = 'oooooooo-oooo-4ooo-8ooo-oooooooooooo';
const DEAL = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const RELATIONSHIP = 'rrrrrrrr-rrrr-4rrr-8rrr-rrrrrrrrrrrr';
const INVOICE = 'iiiiiiii-iiii-4iii-8iii-iiiiiiiiiiii';

function relationship(overrides: Partial<TradeRelationship> = {}): TradeRelationship {
  return {
    id: RELATIONSHIP,
    seller: {
      company_id: SELLER,
      name: 'Pune Textiles',
      country: 'IN',
      pipeline_status: 'IN_PIPELINE',
    },
    buyer: {
      company_id: BUYER,
      name: 'Rotterdam Trading BV',
      country: 'NL',
      pipeline_status: 'NOT_IN_PIPELINE',
    },
    source: 'deal_buyer_recorded',
    created_at: '2026-03-01T10:00:00Z',
    invoice_count: 1,
    ...overrides,
  };
}

function list(relationships: TradeRelationship[]): TradeRelationshipList {
  return { relationships, total: relationships.length };
}

function outcome(overrides: Partial<TradeOutcome> = {}): TradeOutcome {
  return {
    id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    invoice_id: INVOICE,
    payment_status: 'PAID',
    amount_paid: '18400.00',
    proof_status: 'PROVEN',
    evidence_note: 'Bank advice seen.',
    evidence_refs: null,
    recorded_by: 'rm-1',
    recorded_at: '2026-04-02T10:00:00Z',
    supersedes_outcome_id: null,
    is_current: true,
    ...overrides,
  };
}

function invoice(overrides: Partial<TradeInvoice> = {}): TradeInvoice {
  return {
    id: INVOICE,
    relationship_id: RELATIONSHIP,
    deal_id: DEAL,
    invoice_number: 'INV-2026-0041',
    invoice_date: '2026-03-10',
    amount: '18400.00',
    currency: 'USD',
    created_by: 'rm-1',
    created_at: '2026-03-10T10:00:00Z',
    current_outcome: outcome(),
    ...overrides,
  };
}

function detail(invoices: TradeInvoice[]): TradeRelationshipDetail {
  return { relationship: relationship({ invoice_count: invoices.length }), invoices };
}

function chain(outcomes: TradeOutcome[]): TradeInvoiceDetail {
  return { invoice: invoice(), outcomes };
}

function renderPanel({ dealId }: { dealId?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TradeHistoryPanel sellerId={SELLER} buyerId={BUYER} dealId={dealId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listTradeRelationships).mockResolvedValue(list([relationship()]));
  vi.mocked(getTradeRelationship).mockResolvedValue(detail([invoice()]));
  vi.mocked(getTradeInvoice).mockResolvedValue(chain([outcome()]));
});

it('reads as "seller → buyer" and links to both companies', async () => {
  renderPanel();

  expect(await screen.findByRole('link', { name: 'Pune Textiles' })).toHaveAttribute(
    'href',
    `/companies/${SELLER}`,
  );
  const buyerLinks = screen.getAllByRole('link', { name: /Rotterdam Trading BV/ });
  expect(buyerLinks[0]).toHaveAttribute('href', `/companies/${BUYER}`);
});

it('shows each invoice with its amount, its currency and its outcome', async () => {
  renderPanel();

  expect(await screen.findByText('INV-2026-0041')).toBeInTheDocument();
  // Amount and currency together, and the amount exactly as the server sent it:
  // money is Numeric server-side and a parsed number would round it.
  expect(screen.getByText('18400.00 USD')).toBeInTheDocument();
  expect(screen.getByText('Paid')).toBeInTheDocument();
});

it('totals nothing, because there is no reporting currency', async () => {
  vi.mocked(getTradeRelationship).mockResolvedValue(
    detail([
      invoice(),
      invoice({
        id: 'iiiiiiii-iiii-4iii-8iii-222222222222',
        invoice_number: 'INV-2026-0042',
        amount: '9000.00',
        currency: 'EUR',
      }),
    ]),
  );
  const { container } = renderPanel();

  await screen.findByText('INV-2026-0041');
  expect(screen.getByText('9000.00 EUR')).toBeInTheDocument();
  // 18400 + 9000 across two currencies is not a number anybody can write down.
  expect(container.textContent).not.toContain('27400');
  expect(container.textContent).not.toMatch(/total/i);
});

it('marks the deal being viewed, so a reader knows which invoice is this one', async () => {
  vi.mocked(getTradeRelationship).mockResolvedValue(
    detail([
      invoice(),
      invoice({
        id: 'iiiiiiii-iiii-4iii-8iii-333333333333',
        invoice_number: 'INV-2025-0100',
        deal_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      }),
    ]),
  );
  renderPanel({ dealId: DEAL });

  const marks = await screen.findAllByText('This deal');
  expect(marks).toHaveLength(1);
});

it('marks nothing on a company page, where there is no current deal', async () => {
  renderPanel();

  await screen.findByText('INV-2026-0041');
  expect(screen.queryByText('This deal')).not.toBeInTheDocument();
});

it('fetches an invoice’s outcome chain only when it is opened', async () => {
  renderPanel();
  await screen.findByText('INV-2026-0041');
  // Thirty invoices must not be thirty requests for something nobody opened.
  expect(getTradeInvoice).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Outcome history' }));
  await waitFor(() => expect(getTradeInvoice).toHaveBeenCalledWith(INVOICE));
});

it('shows a superseded outcome as well as the current one', async () => {
  vi.mocked(getTradeInvoice).mockResolvedValue(
    chain([
      outcome({
        id: 'cccccccc-cccc-4ccc-8ccc-111111111111',
        payment_status: 'UNPAID',
        amount_paid: null,
        proof_status: 'CLAIMED',
        evidence_note: null,
        is_current: false,
      }),
      outcome(),
    ]),
  );
  renderPanel();
  await screen.findByText('INV-2026-0041');
  fireEvent.click(screen.getByRole('button', { name: 'Outcome history' }));

  // An invoice corrected from Unpaid to Paid is not the same as one paid from the
  // start, and only the chain says which.
  expect(await screen.findByText('Superseded')).toBeInTheDocument();
  expect(screen.getByText('Unpaid')).toBeInTheDocument();
  expect(screen.getByText('Claimed')).toBeInTheDocument();
  expect(screen.getByText('Bank advice seen.')).toBeInTheDocument();
});

it('says an invoice nobody has followed up has no outcome, not "not known"', async () => {
  vi.mocked(getTradeRelationship).mockResolvedValue(
    detail([invoice({ current_outcome: null })]),
  );
  renderPanel();

  expect(await screen.findByText('No outcome recorded')).toBeInTheDocument();
  expect(screen.queryByText('Not known')).not.toBeInTheDocument();
  // Nothing to open: there is no chain behind an invoice with no outcome.
  expect(screen.queryByRole('button', { name: 'Outcome history' })).not.toBeInTheDocument();
});

it('says "not known" when somebody looked and could not say', async () => {
  vi.mocked(getTradeRelationship).mockResolvedValue(
    detail([invoice({ current_outcome: outcome({ payment_status: 'UNKNOWN', amount_paid: null }) })]),
  );
  renderPanel();

  expect(await screen.findByText('Not known')).toBeInTheDocument();
  expect(screen.queryByText('No outcome recorded')).not.toBeInTheDocument();
});

it('says a pair with no relationship is unlinked, not that they never traded', async () => {
  // The seller sells to somebody else, so the list is not empty — this buyer is
  // simply not in it, which is what a deal the buyer migration has not reached
  // looks like.
  vi.mocked(listTradeRelationships).mockResolvedValue(
    list([
      relationship({
        id: 'rrrrrrrr-rrrr-4rrr-8rrr-999999999999',
        buyer: {
          company_id: OTHER_BUYER,
          name: 'Hamburg Imports',
          country: 'DE',
          pipeline_status: 'NOT_IN_PIPELINE',
        },
      }),
    ]),
  );
  renderPanel();

  expect(await screen.findByText(/No trade relationship between these two/)).toBeInTheDocument();
  expect(screen.getByText(/buyer migration and the relationship backfill/)).toBeInTheDocument();
  // And it does not go on to ask for invoices it has no relationship for.
  expect(getTradeRelationship).not.toHaveBeenCalled();
});

it('separates "no invoices yet" from "no relationship"', async () => {
  vi.mocked(getTradeRelationship).mockResolvedValue(detail([]));
  renderPanel();

  expect(await screen.findByText(/no invoice has been recorded/i)).toBeInTheDocument();
  // The pair is still named: these two are on a deal together.
  expect(screen.getByRole('link', { name: 'Pune Textiles' })).toBeInTheDocument();
});

it('does not show a failed read as an empty history', async () => {
  vi.mocked(listTradeRelationships).mockRejectedValue(new Error('offline'));
  renderPanel();

  expect(await screen.findByText(/Couldn't load what these two have traded/)).toBeInTheDocument();
  expect(screen.queryByText(/No trade relationship/)).not.toBeInTheDocument();
});

it('serves no identifiers for the counterparty, whatever the role', async () => {
  const { container } = renderPanel();
  await screen.findByText('INV-2026-0041');

  // The response shape carries none, so there is nothing here to mask. This asserts
  // the component invents no identifier line of its own — the counterparty's PAN and
  // GSTIN live on its company page, where its masking governs them.
  expect(container.textContent).not.toMatch(/PAN|GSTIN|CIN|IEC/);
});
