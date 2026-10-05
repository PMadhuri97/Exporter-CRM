/**
 * Approvals (frontend-plan §8.8): the queue lists what awaits this officer's signature
 * and what is due for Re-KYC; choosing a case opens that company's background check
 * beside the queue.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ShellProvider } from '@/platform/shell';

import { listOpenProposals, listReKycDue } from '../api';
import type { BackgroundCheckProposal } from '../types';

import { ApprovalsPage } from './ApprovalsPage';

vi.mock('../api', () => ({
  listOpenProposals: vi.fn(),
  listReKycDue: vi.fn(),
  approveBackgroundCheckProposal: vi.fn(),
  rejectBackgroundCheckProposal: vi.fn(),
  withdrawBackgroundCheckProposal: vi.fn(),
}));
vi.mock('./panels/BackgroundCheckPanel', () => ({
  BackgroundCheckPanel: ({ customerId }: { customerId: string }) => (
    <p data-testid="case-panel">{customerId}</p>
  ),
}));

const PROPOSAL = {
  id: 'p1',
  company_id: 'company-a',
  company_name: 'Bharat Precision Metals',
  to_value: 'CLEAR',
  risk_rating: 'LOW',
  reason: 'Every check passed.',
  proposed_by: 'maker',
  proposed_by_name: 'R. Mehta',
  proposed_at: '2026-10-03T11:02:00Z',
  allowed_actions: ['APPROVE', 'REJECT'],
} as BackgroundCheckProposal;


function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/review']}>
        <ShellProvider>
          <ApprovalsPage />
        </ShellProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listOpenProposals).mockResolvedValue({ proposals: [PROPOSAL], total: 1, limit: 50, offset: 0 } as never);
  vi.mocked(listReKycDue).mockResolvedValue({
    companies: [
      {
        company_id: 'company-b',
        company_name: 'Coastal Seafood',
        journey: 'CUSTOMER',
        background_check: 'CLEAR',
        expires_at: '2026-10-12',
        is_expired: false,
        current_cycle_number: 1,
        pipeline_status: 'IN_PIPELINE',
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
    before: '2026-11-04',
  } as never);
});

describe('ApprovalsPage', () => {
  it('lists what awaits a signature and what is due, and opens the first case', async () => {
    renderPage();
    const queue = await screen.findByRole('navigation', { name: 'Review queue' });
    expect(await within(queue).findByText('Bharat Precision Metals')).toBeInTheDocument();
    expect(within(queue).getByText('Coastal Seafood')).toBeInTheDocument();
    expect(listOpenProposals).toHaveBeenCalledWith({ awaitingMe: true, limit: 50 });
    expect(await screen.findByTestId('case-panel')).toHaveTextContent('company-a');
  });

  it('opens another case when it is chosen', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Coastal Seafood/ }));
    expect(await screen.findByTestId('case-panel')).toHaveTextContent('company-b');
  });
});
