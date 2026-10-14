/**
 * Payment terms are a live rule: retiring one stops every new deal choosing it. So no
 * change goes out on a single click or without a reason — Retire asks first, and the
 * form will not save until it says why.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { addPaymentTerm, listPaymentTerms, revisePaymentTerm } from '../api';
import type { PaymentTerm } from '../types';

import { PaymentTermsPage } from './PaymentTermsPage';

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  listPaymentTerms: vi.fn(),
  addPaymentTerm: vi.fn(),
  revisePaymentTerm: vi.fn(),
}));

const REASON = 'CHG-2001: replaced by DA 60 days for all buyers';

const TERM: PaymentTerm = {
  id: '44444444-4444-4444-8444-444444444444',
  code: 'DA_90',
  version: 1,
  label: 'DA 90 days',
  kind: 'DA',
  days: 90,
  active: true,
  is_current: true,
  created_by: 'admin-1',
  created_at: '2026-10-01T09:00:00Z',
  change_reason: 'CHG-1000: initial terms',
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PaymentTermsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function giveReason(scope: HTMLElement, reason = REASON) {
  fireEvent.change(within(scope).getByLabelText(/^Reason for change/), { target: { value: reason } });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listPaymentTerms).mockResolvedValue({ terms: [TERM], history: [TERM], can_edit: true });
  vi.mocked(revisePaymentTerm).mockResolvedValue({ ...TERM, version: 2, active: false });
  vi.mocked(addPaymentTerm).mockResolvedValue(TERM);
});

describe('PaymentTermsPage', () => {
  it('shows why the current version was written', async () => {
    renderPage();
    const row = await screen.findByTestId('payment-term-row');
    expect(row).toHaveTextContent('Last change: CHG-1000: initial terms');
  });

  it('asks before retiring a term, and sends nothing without a reason', async () => {
    renderPage();
    const row = await screen.findByTestId('payment-term-row');
    fireEvent.click(within(row).getByRole('button', { name: 'Retire' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Retire DA 90 days?');
    const commit = within(dialog).getByRole('button', { name: 'Retire term' });
    expect(commit).toBeDisabled();
    giveReason(dialog, 'retire');
    expect(commit).toBeDisabled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(revisePaymentTerm).not.toHaveBeenCalled();
  });

  it('retires a term with the reason given', async () => {
    renderPage();
    const row = await screen.findByTestId('payment-term-row');
    fireEvent.click(within(row).getByRole('button', { name: 'Retire' }));

    const dialog = await screen.findByRole('dialog');
    giveReason(dialog);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Retire term' }));

    await waitFor(() =>
      expect(revisePaymentTerm).toHaveBeenCalledWith('DA_90', { active: false, change_reason: REASON }),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('will not save a changed term until the change says why', async () => {
    renderPage();
    const row = await screen.findByTestId('payment-term-row');
    fireEvent.click(within(row).getByRole('button', { name: /Change/ }));

    fireEvent.change(screen.getByLabelText(/^Label/), { target: { value: 'DA 90 days (from B/L date)' } });
    const save = screen.getByRole('button', { name: 'Save term' });
    expect(save).toBeDisabled();
    giveReason(document.body);
    fireEvent.click(save);

    await waitFor(() =>
      expect(revisePaymentTerm).toHaveBeenCalledWith('DA_90', {
        label: 'DA 90 days (from B/L date)',
        kind: 'DA',
        days: 90,
        change_reason: REASON,
      }),
    );
  });
});
