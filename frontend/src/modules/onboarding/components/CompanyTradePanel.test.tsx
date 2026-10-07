import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getTradeRelationship, listTradeRelationships, recordTradeInvoice } from '../api';
import type {
  TradeInvoice,
  TradeRelationship,
  TradeRelationshipDetail,
  TradeRelationshipList,
} from '../types';

import { CompanyTradePanel } from './CompanyTradePanel';

vi.mock('../api', () => ({
  listTradeRelationships: vi.fn(),
  getTradeRelationship: vi.fn(),
  getTradeInvoice: vi.fn(),
  recordTradeInvoice: vi.fn(),
  recordTradeOutcome: vi.fn(),
  getDocument: vi.fn(),
  fetchDocumentBlob: vi.fn(),
  createDownloadLink: vi.fn(),
}));

const COMPANY = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const BUYER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const RELATIONSHIP = 'rrrrrrrr-rrrr-4rrr-8rrr-rrrrrrrrrrrr';

function relationship(overrides: Partial<TradeRelationship> = {}): TradeRelationship {
  return {
    id: RELATIONSHIP,
    seller: {
      company_id: COMPANY,
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
    invoice_count: 2,
    ...overrides,
  };
}

function list(relationships: TradeRelationship[]): TradeRelationshipList {
  return { relationships, total: relationships.length };
}

function invoice(overrides: Partial<TradeInvoice> = {}): TradeInvoice {
  return {
    id: 'iiiiiiii-iiii-4iii-8iii-iiiiiiiiiiii',
    relationship_id: RELATIONSHIP,
    deal_id: null,
    invoice_number: 'INV-2026-0041',
    invoice_date: '2026-03-10',
    amount: '18400.00',
    currency: 'USD',
    created_by: 'rm-1',
    created_at: '2026-03-10T10:00:00Z',
    current_outcome: null,
    ...overrides,
  };
}

function detail(invoices: TradeInvoice[]): TradeRelationshipDetail {
  return { relationship: relationship(), invoices };
}

function renderPanel(as: 'seller' | 'buyer', canRecord = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompanyTradePanel companyId={COMPANY} as={as} canRecord={canRecord} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listTradeRelationships).mockResolvedValue(list([relationship()]));
  vi.mocked(getTradeRelationship).mockResolvedValue(detail([invoice()]));
});

it('asks the server for one side at a time', async () => {
  renderPanel('buyer');
  await waitFor(() =>
    expect(listTradeRelationships).toHaveBeenCalledWith(COMPANY, { as: 'buyer' }),
  );
});

it('names the counterparty, never the company whose page this is', async () => {
  renderPanel('seller');

  expect(await screen.findByRole('link', { name: 'Rotterdam Trading BV' })).toHaveAttribute(
    'href',
    `/companies/${BUYER}`,
  );
  // Repeating "Pune Textiles" in every row would say nothing; the counterparty is
  // what tells the rows apart.
  expect(screen.queryByText('Pune Textiles')).not.toBeInTheDocument();
});

it('names the seller on the buying side, which is the other party there', async () => {
  renderPanel('buyer');

  expect(await screen.findByRole('link', { name: 'Pune Textiles' })).toBeInTheDocument();
  expect(screen.queryByText('Rotterdam Trading BV')).not.toBeInTheDocument();
});

it('says how many invoices a row holds before it is opened', async () => {
  renderPanel('seller');
  expect(await screen.findByText(/2 invoices/)).toBeInTheDocument();
});

it('fetches a relationship’s invoices only when its row is opened', async () => {
  renderPanel('seller');
  await screen.findByText(/2 invoices/);
  // Twenty counterparties must not be twenty requests on load.
  expect(getTradeRelationship).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: /Invoices/ }));
  await waitFor(() => expect(getTradeRelationship).toHaveBeenCalledWith(RELATIONSHIP));
  expect(await screen.findByText('INV-2026-0041')).toBeInTheDocument();
});

it('offers nothing to open on a relationship with no invoices', async () => {
  vi.mocked(listTradeRelationships).mockResolvedValue(
    list([relationship({ invoice_count: 0 })]),
  );
  renderPanel('seller');

  expect(await screen.findByText(/No invoices recorded/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Invoices/ })).not.toBeInTheDocument();
  // There is still somewhere to go — the counterparty's own page, through its name —
  // and only once: no second "Open company" link to the same place.
  expect(screen.getByRole('link', { name: 'Rotterdam Trading BV' })).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /Open company/ })).not.toBeInTheDocument();
});

it('marks a counterparty that is not in the sales pipeline', async () => {
  renderPanel('seller');
  // Usually a company created from a deal's buyer: its page has no qualification and
  // no conversation, by design rather than by omission.
  expect(await screen.findByText('Not in the pipeline')).toBeInTheDocument();
});

it('says when nobody is recorded as a buyer', async () => {
  vi.mocked(listTradeRelationships).mockResolvedValue(list([]));
  renderPanel('seller');

  expect(await screen.findByText(/Nobody recorded as a buyer from this company yet/)).toBeInTheDocument();
});

it('does not show a failed read as an empty list', async () => {
  vi.mocked(listTradeRelationships).mockRejectedValue(new Error('offline'));
  renderPanel('seller');

  expect(
    await screen.findByText(/Couldn't load this company's trade history/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Nobody recorded/)).not.toBeInTheDocument();
});

it('shows no counterparty identifiers, whatever the role', async () => {
  const { container } = renderPanel('seller');
  await screen.findByText(/2 invoices/);

  // The response carries none — that is the server's doing. This asserts the row
  // invents no identifier line of its own.
  expect(container.textContent).not.toMatch(/PAN|GSTIN|CIN|IEC/);
});

describe('recording past trade', () => {
  it('offers staff a past invoice on every relationship row', async () => {
    renderPanel('seller', true);
    fireEvent.click(await screen.findByRole('button', { name: 'Record past invoice' }));
    expect(screen.getByRole('form', { name: 'Record past invoice' })).toHaveTextContent(
      'Rotterdam Trading BV',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('form', { name: 'Record past invoice' })).not.toBeInTheDocument();
  });

  it('offers a read-only role nothing to record (DEVELOPER)', async () => {
    renderPanel('seller', false);
    await screen.findByText(/2 invoices/);
    expect(screen.queryByRole('button', { name: 'Record past invoice' })).not.toBeInTheDocument();
  });

  it('offers nothing to record against when there is no relationship yet', async () => {
    vi.mocked(listTradeRelationships).mockResolvedValue(list([]));
    renderPanel('seller', true);
    expect(await screen.findByText(/Nobody recorded as a buyer/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Record past invoice' })).not.toBeInTheDocument();
  });

  it('opens the invoices once a past invoice is recorded', async () => {
    vi.mocked(recordTradeInvoice).mockResolvedValue(invoice({ invoice_number: 'OLD-2024-17' }));
    renderPanel('seller', true);
    fireEvent.click(await screen.findByRole('button', { name: 'Record past invoice' }));
    fireEvent.change(screen.getByLabelText(/Invoice number/), { target: { value: 'OLD-2024-17' } });
    fireEvent.change(screen.getByLabelText(/Invoice date/), { target: { value: '2024-11-02' } });
    fireEvent.change(screen.getByLabelText(/^Amount/), { target: { value: '9200' } });
    fireEvent.change(screen.getByLabelText(/Currency/), { target: { value: 'EUR' } });
    fireEvent.click(
      within(screen.getByRole('form', { name: 'Record past invoice' })).getByRole('button', {
        name: 'Record past invoice',
      }),
    );

    await waitFor(() => expect(getTradeRelationship).toHaveBeenCalledWith(RELATIONSHIP));
    expect(screen.queryByRole('form', { name: 'Record past invoice' })).not.toBeInTheDocument();
  });
});
