import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import {
  getTradeRelationship,
  listTradeRelationships,
  recordDealPaymentOutcome,
} from '../api';
import type {
  TradeInvoice,
  TradeOutcome,
  TradeRelationship,
  TradeRelationshipDetail,
} from '../types';

import { RecordDealOutcomeForm } from './RecordDealOutcomeForm';

vi.mock('../api', () => ({
  listTradeRelationships: vi.fn(),
  getTradeRelationship: vi.fn(),
  getTradeInvoice: vi.fn(),
  recordDealPaymentOutcome: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SELLER = 'ssssssss-ssss-4sss-8sss-ssssssssssss';
const BUYER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const DEAL = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const RELATIONSHIP = 'rrrrrrrr-rrrr-4rrr-8rrr-rrrrrrrrrrrr';
const OUTCOME = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

const relationship: TradeRelationship = {
  id: RELATIONSHIP,
  seller: { company_id: SELLER, name: 'Pune Textiles', country: 'IN', pipeline_status: 'IN_PIPELINE' },
  buyer: {
    company_id: BUYER,
    name: 'Rotterdam Trading BV',
    country: 'NL',
    pipeline_status: 'NOT_IN_PIPELINE',
  },
  source: 'deal_buyer_recorded',
  created_at: '2026-03-01T10:00:00Z',
  invoice_count: 0,
};

function invoice(current: TradeOutcome | null): TradeInvoice {
  return {
    id: 'iiiiiiii-iiii-4iii-8iii-iiiiiiiiiiii',
    relationship_id: RELATIONSHIP,
    deal_id: DEAL,
    invoice_number: 'INV-2026-0041',
    invoice_date: '2026-03-10',
    amount: '18400.00',
    currency: 'USD',
    created_by: 'rm-1',
    created_at: '2026-03-10T10:00:00Z',
    current_outcome: current,
  };
}

function detail(invoices: TradeInvoice[]): TradeRelationshipDetail {
  return { relationship, invoices };
}

const head: TradeOutcome = {
  id: OUTCOME,
  invoice_id: invoice(null).id,
  payment_status: 'UNPAID',
  amount_paid: null,
  proof_status: 'CLAIMED',
  evidence_note: null,
  evidence_refs: null,
  recorded_by: 'rm-1',
  recorded_at: '2026-04-01T10:00:00Z',
  supersedes_outcome_id: null,
  is_current: true,
};

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RecordDealOutcomeForm
        dealId={DEAL}
        sellerId={SELLER}
        buyerId={BUYER}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listTradeRelationships).mockResolvedValue({
    relationships: [relationship],
    total: 1,
  });
  vi.mocked(getTradeRelationship).mockResolvedValue(detail([]));
  vi.mocked(recordDealPaymentOutcome).mockResolvedValue({
    outcome: head,
    invoice: invoice(head),
    invoice_created: true,
    relationship_id: RELATIONSHIP,
  } as never);
});

it('asks for the invoice when the deal has none, and sends all four fields', async () => {
  renderForm();

  const number = await screen.findByLabelText('Invoice number');
  fireEvent.change(number, { target: { value: 'INV-2026-0041' } });
  fireEvent.change(screen.getByLabelText('Invoice date'), { target: { value: '2026-03-10' } });
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '18400.00' } });
  fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'usd' } });
  fireEvent.change(screen.getByLabelText('What happened'), { target: { value: 'PAID' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record outcome' }));

  await waitFor(() =>
    expect(recordDealPaymentOutcome).toHaveBeenCalledWith(DEAL, {
      payment_status: 'PAID',
      proof_status: 'CLAIMED',
      amount_paid: null,
      evidence_note: null,
      supersedes_outcome_id: null,
      invoice_number: 'INV-2026-0041',
      invoice_date: '2026-03-10',
      amount: '18400.00',
      // Upper-cased here, as the server stores it.
      currency: 'USD',
    }),
  );
});

it('refuses a half-filled invoice rather than sending it', async () => {
  renderForm();

  fireEvent.change(await screen.findByLabelText('Invoice number'), {
    target: { value: 'INV-2026-0041' },
  });
  fireEvent.change(screen.getByLabelText('What happened'), { target: { value: 'PAID' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record outcome' }));

  // All four or none: an invoice with a number but no amount is not an invoice.
  expect(await screen.findByRole('alert')).toHaveTextContent(/number, date, amount and currency/);
  expect(recordDealPaymentOutcome).not.toHaveBeenCalled();
});

it('does not ask for the invoice again once the deal has one', async () => {
  vi.mocked(getTradeRelationship).mockResolvedValue(detail([invoice(null)]));
  renderForm();

  await screen.findByLabelText('What happened');
  // Its identity is frozen, so sending the fields again is refused rather than
  // treated as an edit — the form does not offer them.
  expect(screen.queryByLabelText('Invoice number')).not.toBeInTheDocument();
});

it('corrects by superseding the current outcome, never by editing it', async () => {
  vi.mocked(getTradeRelationship).mockResolvedValue(detail([invoice(head)]));
  renderForm();

  expect(await screen.findByText('Correct the outcome')).toBeInTheDocument();
  expect(screen.getByText(/stays visible as superseded/)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('What happened'), { target: { value: 'DISPUTED' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record correction' }));

  await waitFor(() =>
    expect(recordDealPaymentOutcome).toHaveBeenCalledWith(
      DEAL,
      // The head, which is the only outcome the server accepts as superseded.
      expect.objectContaining({ payment_status: 'DISPUTED', supersedes_outcome_id: OUTCOME }),
    ),
  );
});

it('offers "not known" as an answer', async () => {
  renderForm();
  const select = await screen.findByLabelText('What happened');
  // Somebody looked and could not say — a real answer, and the reason an outcome is
  // required to carry a status at all.
  expect(select).toContainHTML('Not known');
});

it('asks what was seen before accepting a proven outcome', async () => {
  vi.mocked(getTradeRelationship).mockResolvedValue(detail([invoice(null)]));
  renderForm();

  fireEvent.change(await screen.findByLabelText('What happened'), { target: { value: 'PAID' } });
  fireEvent.change(screen.getByLabelText('Proof'), { target: { value: 'PROVEN' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record outcome' }));

  expect(await screen.findByRole('alert')).toHaveTextContent(/needs a note/);
  expect(recordDealPaymentOutcome).not.toHaveBeenCalled();
});

it('shows the server’s own words when it refuses', async () => {
  const { ApiError } = await import('@/lib/api/errors');
  vi.mocked(getTradeRelationship).mockResolvedValue(detail([invoice(null)]));
  vi.mocked(recordDealPaymentOutcome).mockRejectedValue(
    new ApiError(409, 'This deal has not been handed over yet', 'DEAL_NOT_HANDED_OVER'),
  );
  renderForm();

  fireEvent.change(await screen.findByLabelText('What happened'), { target: { value: 'PAID' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record outcome' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('This deal has not been handed over yet');
});
