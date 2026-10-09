import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import { searchExporterProfiles } from '../api';
import type { ExporterJourney, ExporterProfileListItem, ExporterSearchParams } from '../types';

import { PipelinePage } from './PipelinePage';

// Partial: the role helpers (`isStaffRole`, …) stay real, only the session is faked.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', () => ({ searchExporterProfiles: vi.fn() }));

function company(journey: ExporterJourney, name: string): ExporterProfileListItem {
  return {
    customer_id: `${journey}-${name}`,
    name,
    country: 'IN',
    gstins: [],
    cin: null,
    relationship_manager_inactive: false,
    journey,
    qualification: journey === 'LEAD' ? 'NOT_YET_REVIEWED' : 'QUALIFIED',
    marker: 'NONE',
    marker_reason: null,
    pan: null,
    iec: null,
    registration_number: null,
    identity_type: null,
    pipeline_status: 'IN_PIPELINE',
  has_active_primary_contact: true,
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

describe('PipelinePage — the three-column journey', () => {
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

  it('says on each card what it is waiting for, and counts the ones waiting on us', async () => {
    renderPage();

    // A lead nobody has judged is the one case the board can call ours.
    const lead = await screen.findByRole('region', { name: 'Lead' });
    expect(await within(lead).findAllByText('Waiting on a qualification decision')).toHaveLength(2);
    expect(within(lead).getByText('2 waiting on you')).toBeInTheDocument();

    // A prospect waits on compliance, not on the person reading the board — so it is
    // said, but not counted.
    const prospect = screen.getByRole('region', { name: 'Prospect' });
    expect(await within(prospect).findByText('Needs a clear background check')).toBeInTheDocument();
    expect(within(prospect).queryByText(/waiting on you/)).not.toBeInTheDocument();
  });

  it('keeps the waiting count off the board for a role whose queue it is not', async () => {
    // COMPLIANCE holds `crm.write` and so *may* record a qualification decision, but
    // leads are the relationship manager's work. A count of someone else's queue reads
    // as a demand on whoever is looking at it.
    for (const role of ['COMPLIANCE', 'ADMIN'] as const) {
      vi.mocked(useCurrentUser).mockReturnValue({
        id: 'u1',
        email: 'user@aner.example',
        full_name: null,
        role,
        is_active: true,
      });
      const { unmount } = renderPage();
      const lead = await screen.findByRole('region', { name: 'Lead' });
      // The cards still say what each company waits on — only the tally is theirs alone.
      expect(await within(lead).findAllByText('Waiting on a qualification decision')).toHaveLength(2);
      expect(within(lead).queryByText(/waiting on you/)).not.toBeInTheDocument();
      unmount();
    }
  });

  it('reads the marker and its reason in place of a next step', async () => {
    vi.mocked(searchExporterProfiles).mockImplementation((params: ExporterSearchParams) =>
      Promise.resolve({
        profiles:
          params.journey === 'LEAD'
            ? [{ ...company('LEAD', 'Paused One'), marker: 'PAUSED', marker_reason: 'Seasonal' }]
            : [],
        limit: 100,
        offset: 0,
      }),
    );
    renderPage();

    const lead = await screen.findByRole('region', { name: 'Lead' });
    expect(await within(lead).findByText('Paused — Seasonal')).toBeInTheDocument();
    // Paused is not work waiting on anyone, whatever its qualification says.
    expect(within(lead).queryByText(/waiting on you/)).not.toBeInTheDocument();
    expect(within(lead).queryByText('Waiting on a qualification decision')).not.toBeInTheDocument();
  });

  it('puts industry, country and the RM on one line, and no bare country code', async () => {
    vi.mocked(searchExporterProfiles).mockImplementation((params: ExporterSearchParams) =>
      Promise.resolve({
        profiles:
          params.journey === 'CUSTOMER'
            ? [
                {
                  ...company('CUSTOMER', 'Kaveri Spice Traders'),
                  industry: 'Spices',
                  relationship_manager: 'Srikar',
                  relationship_manager_name: 'Srikar',
                },
              ]
            : [],
        limit: 100,
        offset: 0,
      }),
    );
    renderPage();

    const customer = await screen.findByRole('region', { name: 'Customer' });
    expect(await within(customer).findByText('Spices · India · RM Srikar')).toBeInTheDocument();
    // The country used to sit alone in the corner, where "IN" said nothing.
    expect(within(customer).queryByText('IN', { exact: true })).not.toBeInTheDocument();
    // A customer's next step is "trade", which the column note already says once.
    expect(within(customer).queryByText(/^Waiting on/)).not.toBeInTheDocument();
  });
});
