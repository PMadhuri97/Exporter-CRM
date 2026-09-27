import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { listFollowUps, searchExporterProfiles } from '../../api';
import type { ExporterProfileListItem, FollowUpList } from '../../types';

import { CheckBacksDueCard, FollowUpsDueCard, PipelineSummaryCard } from './HomeCards';

vi.mock('../../api', () => ({
  listFollowUps: vi.fn(),
  searchExporterProfiles: vi.fn(),
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
    renderCard(<FollowUpsDueCard userId="user-1" />);
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

  it('lists the check-backs that are due, linking to the conversation', async () => {
    renderCard(<CheckBacksDueCard />);
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
