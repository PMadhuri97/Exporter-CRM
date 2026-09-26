import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import { searchExporterProfiles } from '../api';
import type { ExporterJourney, ExporterProfileListItem, ExporterSearchParams } from '../types';

import { PipelinePage } from './PipelinePage';

vi.mock('@/platform/auth', () => ({ useCurrentUser: vi.fn() }));
vi.mock('../api', () => ({ searchExporterProfiles: vi.fn() }));

function company(journey: ExporterJourney, name: string): ExporterProfileListItem {
  return {
    customer_id: `${journey}-${name}`,
    name,
    country: 'IN',
    gstins: [],
    cin: null,
    journey,
    qualification: journey === 'LEAD' ? 'NOT_YET_REVIEWED' : 'QUALIFIED',
    marker: 'NONE',
    marker_reason: null,
    pan: null,
    iec: null,
    source: 'MANUAL',
    relationship_manager: null,
    relationship_manager_user_id: null,
    industry: null,
    year_established: null,
    date_added: '2026-01-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

const BY_JOURNEY: Record<ExporterJourney, ExporterProfileListItem[]> = {
  LEAD: [company('LEAD', 'Lead One'), company('LEAD', 'Lead Two')],
  PROSPECT: [company('PROSPECT', 'Prospect One')],
  CUSTOMER: [],
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PipelinePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('PipelinePage — the three-column journey (L2-14)', () => {
  beforeEach(() => {
    vi.mocked(useCurrentUser).mockReturnValue({
      id: 'u1',
      email: 'user@aner.example',
      full_name: null,
      role: 'OPERATIONS',
      is_active: true,
    });
    vi.mocked(searchExporterProfiles).mockReset();
    vi.mocked(searchExporterProfiles).mockImplementation((params: ExporterSearchParams) =>
      Promise.resolve({ profiles: BY_JOURNEY[params.journey!], limit: 100, offset: 0 }),
    );
  });

  it('has exactly three columns, Lead, Prospect and Customer, in order', async () => {
    renderPage();
    const columns = await screen.findAllByRole('region');
    expect(columns.map((column) => column.getAttribute('aria-label'))).toEqual([
      'Lead',
      'Prospect',
      'Customer',
    ]);
  });

  it('fills each column from its own server query by journey', async () => {
    renderPage();
    const lead = await screen.findByRole('region', { name: 'Lead' });
    expect(await within(lead).findByText('Lead One')).toBeInTheDocument();
    expect(within(lead).getByText('Lead Two')).toBeInTheDocument();
    const prospect = screen.getByRole('region', { name: 'Prospect' });
    expect(await within(prospect).findByText('Prospect One')).toBeInTheDocument();
    const customer = screen.getByRole('region', { name: 'Customer' });
    expect(await within(customer).findByText('No companies in this stage')).toBeInTheDocument();

    const journeys = vi.mocked(searchExporterProfiles).mock.calls.map(([params]) => params.journey);
    expect(new Set(journeys)).toEqual(new Set(['LEAD', 'PROSPECT', 'CUSTOMER']));
  });

  it('offers no way to move a company between stages by hand', async () => {
    renderPage();
    const cards = await screen.findAllByTestId('pipeline-card');
    for (const card of cards) {
      expect(card).not.toHaveAttribute('draggable', 'true');
    }
    expect(screen.queryByRole('button', { name: /move/i })).not.toBeInTheDocument();
  });
});
