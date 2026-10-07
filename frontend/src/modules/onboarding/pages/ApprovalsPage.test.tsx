/**
 * Compliance work (frontend-plan §8.8): the rail lists the worklists the server
 * computes — reviews awaiting a reviewer, this officer's reviews, what awaits their
 * signature, what is due for Re-KYC, and, for a compliance lead, everyone's reviews,
 * the overdue and what needs attention. Choosing a case opens that company's
 * background check beside the rail; a review nobody holds offers *Assign to me*.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useHasPermission } from '@/platform/access';
import { ShellProvider } from '@/platform/shell';

import {
  claimBackgroundCheckReview,
  listComplianceWork,
  listOpenProposals,
  listReKycDue,
} from '../api';
import type { BackgroundCheckProposal, ComplianceWorkItem, ComplianceWorkView } from '../types';

import { ApprovalsPage } from './ApprovalsPage';

vi.mock('../api', () => ({
  listOpenProposals: vi.fn(),
  listReKycDue: vi.fn(),
  listComplianceWork: vi.fn(),
  claimBackgroundCheckReview: vi.fn(),
  assignBackgroundCheckReview: vi.fn(),
  releaseBackgroundCheckReview: vi.fn(),
  approveBackgroundCheckProposal: vi.fn(),
  rejectBackgroundCheckProposal: vi.fn(),
  withdrawBackgroundCheckProposal: vi.fn(),
}));
vi.mock('./panels/BackgroundCheckPanel', () => ({
  BackgroundCheckPanel: ({ customerId }: { customerId: string }) => (
    <p data-testid="case-panel">{customerId}</p>
  ),
}));
vi.mock('@/platform/access', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/access')>()),
  useHasPermission: vi.fn(),
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
  needs_senior_approval: false,
  is_due_soon: false,
  is_overdue: false,
} as BackgroundCheckProposal;

function item(overrides: Partial<ComplianceWorkItem>): ComplianceWorkItem {
  return {
    company_id: 'company-x',
    company_name: 'Unnamed',
    journey: 'PROSPECT',
    pipeline_status: 'IN_PIPELINE',
    background_check: 'IN_REVIEW',
    stage: 'review',
    relationship_manager_id: null,
    relationship_manager_name: null,
    relationship_manager_inactive: false,
    reviewer_id: null,
    reviewer_name: null,
    reviewer_inactive: false,
    waiting_since: '2026-10-05T09:00:00Z',
    due_at: null,
    is_due_soon: false,
    is_overdue: false,
    rejection_count: 0,
    needs_attention: false,
    needs_senior_approval: false,
    ...overrides,
  } as ComplianceWorkItem;
}

const WORK: Record<ComplianceWorkView, ComplianceWorkItem[]> = {
  awaiting: [item({ company_id: 'company-c', company_name: 'Deccan Leather' })],
  mine: [
    item({
      company_id: 'company-d',
      company_name: 'Eastern Spice',
      reviewer_id: 'me',
      reviewer_name: 'Me',
      due_at: '2026-10-06T09:00:00Z',
      is_overdue: true,
      rejection_count: 2,
    }),
  ],
  in_review: [item({ company_id: 'company-e', company_name: 'Fortune Textiles', reviewer_name: 'Priya' })],
  overdue: [],
  needs_attention: [],
};

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
  vi.mocked(useHasPermission).mockReturnValue(false);
  vi.mocked(listComplianceWork).mockImplementation(async (view) => ({
    view,
    items: WORK[view],
    total: WORK[view].length,
  }));
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

describe('Compliance work', () => {
  it('lists the reviews, what awaits a signature and what is due, and opens the first case', async () => {
    renderPage();
    const queue = await screen.findByRole('navigation', { name: 'Review queue' });
    expect(await within(queue).findByText('Bharat Precision Metals')).toBeInTheDocument();
    expect(within(queue).getByText('Coastal Seafood')).toBeInTheDocument();
    expect(await within(queue).findByText('Deccan Leather')).toBeInTheDocument();
    expect(within(queue).getByText('Eastern Spice')).toBeInTheDocument();
    expect(listOpenProposals).toHaveBeenCalledWith({ awaitingMe: true, limit: 50 });
    expect(await screen.findByTestId('case-panel')).toHaveTextContent('company-c');
  });

  it('says how long, whether it is late and how often it came back', async () => {
    renderPage();
    const mine = await screen.findByRole('region', { name: 'My reviews' });
    expect(await within(mine).findByText('Overdue')).toBeInTheDocument();
    expect(within(mine).getByText('Returned ×2')).toBeInTheDocument();
    expect(within(mine).getByText(/In review · waited/)).toBeInTheDocument();
  });

  it('offers Assign to me on a review nobody holds', async () => {
    vi.mocked(claimBackgroundCheckReview).mockResolvedValue({} as never);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Assign to me' }));
    await waitFor(() => expect(claimBackgroundCheckReview).toHaveBeenCalledWith('company-c'));
  });

  it('opens another case when it is chosen', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Coastal Seafood/ }));
    expect(await screen.findByTestId('case-panel')).toHaveTextContent('company-b');
    expect(screen.queryByRole('button', { name: 'Assign to me' })).not.toBeInTheDocument();
  });

  it('shows everyone’s reviews, the overdue and what needs attention to a lead only', async () => {
    renderPage();
    await screen.findByRole('region', { name: 'My reviews' });
    expect(screen.queryByRole('region', { name: 'In review (everyone)' })).not.toBeInTheDocument();
    expect(listComplianceWork).not.toHaveBeenCalledWith('in_review');
  });

  it('gives a compliance lead the lead views', async () => {
    vi.mocked(useHasPermission).mockReturnValue(true);
    renderPage();
    const everyone = await screen.findByRole('region', { name: 'In review (everyone)' });
    expect(await within(everyone).findByText('Fortune Textiles')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Overdue' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Needs attention' })).toBeInTheDocument();
  });
});
