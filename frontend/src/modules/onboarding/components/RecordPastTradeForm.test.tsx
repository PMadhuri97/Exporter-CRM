import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import { recordTradeInvoice, recordTradeOutcome } from '../api';
import type { TradeInvoice, TradeOutcome } from '../types';

import { RecordPastTradeForm } from './RecordPastTradeForm';

vi.mock('../api', () => ({
  recordTradeInvoice: vi.fn(),
  recordTradeOutcome: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const RELATIONSHIP = 'rrrrrrrr-rrrr-4rrr-8rrr-rrrrrrrrrrrr';
const INVOICE = 'iiiiiiii-iiii-4iii-8iii-iiiiiiiiiiii';

const recorded: TradeInvoice = {
  id: INVOICE,
  relationship_id: RELATIONSHIP,
  deal_id: null,
  invoice_number: 'OLD-2024-17',
  invoice_date: '2024-11-02',
  amount: '9200.00',
  currency: 'EUR',
  created_by: 'rm-1',
  created_at: '2026-10-04T10:00:00Z',
  current_outcome: null,
};

const outcome: TradeOutcome = {
  id: 'oooooooo-oooo-4ooo-8ooo-oooooooooooo',
  invoice_id: INVOICE,
  payment_status: 'PAID',
  amount_paid: null,
  proof_status: 'CLAIMED',
  evidence_note: null,
  evidence_refs: null,
  recorded_by: 'rm-1',
  recorded_at: '2026-10-04T10:00:00Z',
  supersedes_outcome_id: null,
  is_current: true,
};

function renderForm() {
  const onDone = vi.fn();
  const onCancel = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  render(
    <QueryClientProvider client={client}>
      <RecordPastTradeForm
        relationshipId={RELATIONSHIP}
        counterpartyName="Rotterdam Trading BV"
        onDone={onDone}
        onCancel={onCancel}
      />
    </QueryClientProvider>,
  );
  return { onDone, onCancel, invalidate };
}

function fillInvoice() {
  fireEvent.change(screen.getByLabelText(/Invoice number/), { target: { value: ' OLD-2024-17 ' } });
  fireEvent.change(screen.getByLabelText(/Invoice date/), { target: { value: '2024-11-02' } });
  fireEvent.change(screen.getByLabelText(/^Amount/), { target: { value: '9200.00' } });
  fireEvent.change(screen.getByLabelText(/Currency/), { target: { value: 'eur' } });
}

const submit = () => screen.getByRole('button', { name: 'Record past invoice' });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(recordTradeInvoice).mockResolvedValue(recorded);
  vi.mocked(recordTradeOutcome).mockResolvedValue(outcome);
});

describe('RecordPastTradeForm', () => {
  it('says who the invoice is with and that it records no deal', () => {
    renderForm();
    const form = screen.getByRole('form', { name: 'Record past invoice' });
    expect(form).toHaveTextContent('Rotterdam Trading BV');
    expect(form).toHaveTextContent(/records no deal/);
  });

  it('cannot be sent until the invoice carries what the API requires', () => {
    renderForm();
    expect(submit()).toBeDisabled();
    fillInvoice();
    expect(submit()).toBeEnabled();
    // A currency is three letters; anything else waits rather than round-trips.
    fireEvent.change(screen.getByLabelText(/Currency/), { target: { value: 'eu' } });
    expect(submit()).toBeDisabled();
  });

  it('records the invoice with no deal and refreshes the relationship', async () => {
    const { onDone, invalidate } = renderForm();
    fillInvoice();
    fireEvent.click(submit());

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(recordTradeInvoice).toHaveBeenCalledWith(RELATIONSHIP, {
      invoice_number: 'OLD-2024-17',
      invoice_date: '2024-11-02',
      amount: '9200.00',
      currency: 'EUR',
    });
    expect(vi.mocked(recordTradeInvoice).mock.calls[0]?.[1]).not.toHaveProperty('deal_id');
    // No outcome was chosen, so none is sent: "no outcome" is not "not known".
    expect(recordTradeOutcome).not.toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tradeRelationship', RELATIONSHIP] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tradeRelationships'] });
  });

  it('appends the outcome to the invoice it just recorded, claimed by default', async () => {
    const { onDone, invalidate } = renderForm();
    fillInvoice();
    fireEvent.change(screen.getByLabelText(/How it was paid/), { target: { value: 'PARTIAL' } });
    fireEvent.change(screen.getByLabelText(/Amount paid/), { target: { value: '4000' } });
    fireEvent.change(screen.getByLabelText(/Note/), { target: { value: 'Seller says so' } });
    fireEvent.click(submit());

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(recordTradeOutcome).toHaveBeenCalledWith(INVOICE, {
      payment_status: 'PARTIAL',
      proof_status: 'CLAIMED',
      amount_paid: '4000',
      evidence_note: 'Seller says so',
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tradeInvoice', INVOICE] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['companyHistory'] });
  });

  it('shows the server’s refusal of the invoice and records nothing else', async () => {
    vi.mocked(recordTradeInvoice).mockRejectedValue(
      new ApiError(409, 'This relationship already has invoice OLD-2024-17'),
    );
    const { onDone } = renderForm();
    fillInvoice();
    fireEvent.change(screen.getByLabelText(/How it was paid/), { target: { value: 'PAID' } });
    fireEvent.click(submit());

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This relationship already has invoice OLD-2024-17',
    );
    expect(recordTradeOutcome).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });

  it('never re-sends a recorded invoice when only its outcome was refused', async () => {
    vi.mocked(recordTradeOutcome).mockRejectedValueOnce(
      new ApiError(422, 'A part-paid outcome needs the amount paid'),
    );
    const { onDone } = renderForm();
    fillInvoice();
    fireEvent.change(screen.getByLabelText(/How it was paid/), { target: { value: 'PARTIAL' } });
    fireEvent.click(submit());

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /The invoice is recorded, but its outcome was refused: A part-paid outcome needs the amount paid/,
    );
    // The invoice's fields are frozen and the button now sends the outcome only.
    expect(screen.getByLabelText(/Invoice number/)).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Amount paid/), { target: { value: '4000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record the outcome' }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(recordTradeInvoice).toHaveBeenCalledTimes(1);
    expect(recordTradeOutcome).toHaveBeenCalledTimes(2);
    expect(vi.mocked(recordTradeOutcome).mock.calls[1]?.[0]).toBe(INVOICE);
  });

  it('cancels without a request', () => {
    const { onCancel } = renderForm();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
    expect(recordTradeInvoice).not.toHaveBeenCalled();
  });
});
