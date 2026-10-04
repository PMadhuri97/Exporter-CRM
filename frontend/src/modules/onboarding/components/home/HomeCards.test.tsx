import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import {
  approveBackgroundCheckProposal,
  listFollowUps,
  listOpenProposals,
  listReKycDue,
  searchExporterProfiles,
} from '../../api';
import type {
  BackgroundCheckProposal,
  ExporterProfileListItem,
  FollowUpList,
} from '../../types';

import {
  PipelineSummaryCard,
  ProposalsAwaitingMeCard,
  ReKycDueCard,
  UpNextCard,
} from './HomeCards';

vi.mock('../../api', () => ({
  approveBackgroundCheckProposal: vi.fn(),
  listFollowUps: vi.fn(),
  listOpenProposals: vi.fn(),
  listReKycDue: vi.fn(),
  rejectBackgroundCheckProposal: vi.fn(),
  searchExporterProfiles: vi.fn(),
  withdrawBackgroundCheckProposal: vi.fn(),
}));

const CUSTOMER_ID = '11111111-1111-4111-8111-111111111111';

const LIST: FollowUpList = {
  follow_ups: [
    {
      activity_id: 'a1',
      customer_id: CUSTOMER_ID,
      exporter_display_name: 'Coastal Seafood Exports Pvt Ltd',
      activity_type: 'FOLLOW_UP',
      subject: 'Send the rate sheet',
      notes: null,
      actor_id: 'user-1',
      occurred_at: '2026-09-01T10:00:00Z',
      due_at: '2026-09-10T10:00:00Z',
      is_overdue: true,
      state: 'OVERDUE',
      completion: null,
    },
  ],
  follow_ups_total: 3,
  check_backs: [
    {
      customer_id: CUSTOMER_ID,
      exporter_display_name: 'Aarav Textiles Pvt Ltd',
      conversation: 'NOT_NOW',
      check_back_on: '2026-09-20',
      is_overdue: true,
    },
  ],
  check_backs_total: 1,
  limit: 5,
  offset: 0,
};

function renderCard(card: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{card}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listFollowUps).mockResolvedValue(LIST);
});

describe('Home cards', () => {
  it("shows the user's own overdue follow-ups first, and the team's on request", async () => {
    renderCard(<UpNextCard userId="user-1" canComplete />);
    expect(await screen.findByText('Send the rate sheet')).toBeInTheDocument();
    expect(screen.getByTestId('overdue-count')).toHaveTextContent('3');
    expect(listFollowUps).toHaveBeenLastCalledWith(
      expect.objectContaining({ state: 'OVERDUE', actorId: 'user-1' }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Team' }));
    await waitFor(() =>
      expect(listFollowUps).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: 'OVERDUE', actorId: undefined }),
      ),
    );
  });

  it('puts due check-backs in the same queue, as their own kind, linking to the conversation', async () => {
    renderCard(<UpNextCard userId="user-1" />);
    // One time-ordered queue; a check-back is never "completed" here.
    expect(await screen.findAllByTestId('up-next-check-back')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /Done/ })).not.toBeInTheDocument();
    const link = await screen.findByRole('link', { name: /Aarav Textiles/ });
    expect(link).toHaveAttribute('href', `/companies/${CUSTOMER_ID}?tab=conversation`);
    expect(listFollowUps).toHaveBeenLastCalledWith(
      expect.objectContaining({ includeCheckBacks: true, checkBacksDueOnly: true }),
    );
  });

  it('counts each journey stage, and says "200+" rather than a wrong total at the cap', async () => {
    vi.mocked(searchExporterProfiles).mockImplementation(async (params) => ({
      profiles: Array.from(
        { length: params.journey === 'LEAD' ? 200 : params.journey === 'PROSPECT' ? 7 : 0 },
        (_, i) => ({ customer_id: `c${i}` }) as ExporterProfileListItem,
      ),
      limit: params.limit ?? 100,
      offset: 0,
    }));
    renderCard(<PipelineSummaryCard />);
    await waitFor(() => expect(screen.getByTestId('stage-count-LEAD')).toHaveTextContent('200+'));
    await waitFor(() => expect(screen.getByTestId('stage-count-PROSPECT')).toHaveTextContent('7'));
    await waitFor(() => expect(screen.getByTestId('stage-count-CUSTOMER')).toHaveTextContent('0'));
    expect(screen.getByTestId('stage-count-PROSPECT')).toHaveAttribute(
      'href',
      '/companies?journey=PROSPECT',
    );
  });
});

// ── Developer 1: maker-checker (P3-1c) and Re-KYC due (P3-3c) ──────────────

const PROPOSAL: BackgroundCheckProposal = {
  id: 'p1',
  company_id: CUSTOMER_ID,
  company_name: 'Coastal Seafood Exports Pvt Ltd',
  based_on_decision_id: 'd1',
  from_value: 'IN_REVIEW',
  to_value: 'CLEAR',
  risk_rating: 'MEDIUM',
  reason: 'Every check passed.',
  proposed_by: 'maker-id',
  proposed_by_name: 'Asha Maker',
  proposed_at: '2026-10-01T09:00:00Z',
  cycle_id: 'c1',
  cycle_number: 1,
  rules_version: 'clear-2026-10-01-7items-kyb-aml-sanctions',
  evidence_count: 10,
  status: 'OPEN',
  allowed_actions: ['APPROVE', 'REJECT'],
};

describe('Home cards — compliance', () => {
  it('lists the proposals awaiting me, and approves one in two clicks', async () => {
    vi.mocked(listOpenProposals).mockResolvedValue({
      proposals: [PROPOSAL],
      total: 1,
      limit: 5,
      offset: 0,
    });
    vi.mocked(approveBackgroundCheckProposal).mockResolvedValue({
      decision: {} as never,
      proposal: { ...PROPOSAL, status: 'APPROVED' },
    });
    renderCard(<ProposalsAwaitingMeCard />);

    const row = await screen.findByTestId('proposal-awaiting');
    expect(listOpenProposals).toHaveBeenCalledWith({ awaitingMe: true, limit: 5 });
    expect(screen.getByTestId('proposals-awaiting-count')).toHaveTextContent('1');
    expect(within(row).getByRole('link', { name: /Coastal Seafood/ })).toHaveAttribute(
      'href',
      `/companies/${CUSTOMER_ID}?tab=background-check`,
    );
    expect(row).toHaveTextContent('Asha Maker');

    fireEvent.click(within(row).getByRole('button', { name: 'Approve' })); // 1
    const dialog = screen.getByRole('dialog', { name: 'Approve this decision' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' })); // 2

    await waitFor(() =>
      expect(approveBackgroundCheckProposal).toHaveBeenCalledWith(CUSTOMER_ID, 'p1'),
    );
  });

  it('says so when nothing awaits approval, and when the queue cannot be loaded', async () => {
    vi.mocked(listOpenProposals).mockResolvedValueOnce({
      proposals: [],
      total: 0,
      limit: 5,
      offset: 0,
    });
    const { unmount } = renderCard(<ProposalsAwaitingMeCard />);
    expect(
      await screen.findByText('No background-check decision is waiting for your approval.'),
    ).toBeInTheDocument();
    unmount();

    vi.mocked(listOpenProposals).mockRejectedValueOnce(new ApiError(500, 'boom'));
    renderCard(<ProposalsAwaitingMeCard />);
    expect(await screen.findByRole('alert')).toHaveTextContent(/Couldn't load the proposals/);
  });

  it('lists companies due for Re-KYC, the expired ones marked as such', async () => {
    vi.mocked(listReKycDue).mockResolvedValue({
      companies: [
        {
          company_id: CUSTOMER_ID,
          company_name: 'Aarav Textiles Pvt Ltd',
          journey: 'CUSTOMER',
          background_check: 'CLEAR',
          expires_at: '2026-09-20T00:00:00Z',
          is_expired: true,
          current_cycle_number: 1,
          pipeline_status: 'IN_PIPELINE',
        },
        {
          company_id: 'other',
          company_name: 'Blue Harbour Foods',
          journey: 'PROSPECT',
          background_check: 'CLEAR',
          expires_at: '2026-10-20T00:00:00Z',
          is_expired: false,
          current_cycle_number: 2,
          pipeline_status: 'NOT_IN_PIPELINE',
        },
      ],
      total: 2,
      limit: 5,
      offset: 0,
      before: '2026-10-31T00:00:00Z',
    });
    renderCard(<ReKycDueCard />);

    const rows = await screen.findAllByTestId('rekyc-due-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent(/Aarav Textiles.*Expired/);
    expect(rows[1]).toHaveTextContent(/Blue Harbour Foods.*Expires/);
    // R-29: the buyer-only company is marked; the lead is not.
    expect(rows[1]).toHaveTextContent('Buyer only');
    expect(rows[0]).not.toHaveTextContent('Buyer only');
    expect(screen.getByTestId('rekyc-due-count')).toHaveTextContent('2');
    expect(within(rows[0] as HTMLElement).getByRole('link')).toHaveAttribute(
      'href',
      `/companies/${CUSTOMER_ID}?tab=background-check`,
    );
  });

  it('says plainly when no Clear is due', async () => {
    vi.mocked(listReKycDue).mockResolvedValue({
      companies: [],
      total: 0,
      limit: 5,
      offset: 0,
      before: '2026-10-31T00:00:00Z',
    });
    renderCard(<ReKycDueCard />);
    expect(await screen.findByText(/No Clear has expired or expires before/)).toBeInTheDocument();
  });
});
