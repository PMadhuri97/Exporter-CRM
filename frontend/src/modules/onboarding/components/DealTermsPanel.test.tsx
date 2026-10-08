import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { listPaymentTerms, setDealTerms } from '../api';
import type { Deal, PaymentTerm } from '../types';

import { DealTermsPanel } from './DealTermsPanel';

vi.mock('../api', () => ({ listPaymentTerms: vi.fn(), setDealTerms: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function term(code: string, label: string, overrides: Partial<PaymentTerm> = {}): PaymentTerm {
  return { id: `t-${code}`, code, version: 1, label, kind: 'DA', days: 90, active: true, is_current: true, ...overrides };
}

const DA_90 = term('DA_90', 'DA 90 days');
const LC_SIGHT = term('LC_SIGHT', 'LC at sight', { kind: 'LC_SIGHT', days: null });

const DEAL = {
  id: 'd1',
  value_amount: '125000.50',
  currency: 'USD',
  payment_term: DA_90,
  payment_term_override_reason: null,
  company_default_payment_term: DA_90,
} as unknown as Deal;

function renderPanel(deal: Deal = DEAL, canEdit = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DealTermsPanel deal={deal} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listPaymentTerms).mockResolvedValue({ terms: [DA_90, LC_SIGHT], history: [], can_edit: false });
  vi.mocked(setDealTerms).mockResolvedValue(DEAL);
});

describe('DealTermsPanel', () => {
  it('shows the value with its currency and the term', () => {
    renderPanel();
    expect(screen.getByTestId('deal-value')).toHaveTextContent('USD 1,25,000.5');
    expect(screen.getByTestId('deal-term')).toHaveTextContent('DA 90 days');
  });

  it('asks why when a term other than the company default is chosen', async () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /Edit/ }));
    await screen.findByRole('option', { name: 'LC at sight' });

    fireEvent.change(screen.getByLabelText(/^Payment term/), { target: { value: 't-LC_SIGHT' } });
    expect(screen.getByRole('button', { name: 'Save terms' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Why this term/), { target: { value: 'New buyer' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save terms' }));

    await waitFor(() =>
      expect(setDealTerms).toHaveBeenCalledWith('d1', {
        payment_term_id: 't-LC_SIGHT',
        payment_term_override_reason: 'New buyer',
      }),
    );
  });

  it('offers no edit on a closed deal', () => {
    renderPanel(DEAL, false);
    expect(screen.queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument();
  });
});
