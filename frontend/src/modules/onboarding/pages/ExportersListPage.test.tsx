import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import { searchExporterProfiles } from '../api';
import type { ExporterProfileListItem } from '../types';

import { ExportersListPage } from './ExportersListPage';

// vitest hoists vi.mock calls above every import in this file automatically
// (its esbuild transform, not declaration order), so these apply regardless
// of being written after the imports they replace.
vi.mock('@/platform/auth', () => ({ useCurrentUser: vi.fn() }));
vi.mock('../api', () => ({ searchExporterProfiles: vi.fn() }));

const PROFILE: ExporterProfileListItem = {
  customer_id: 'c1',
  name: 'Acme Exports',
  country: 'IN',
  gstins: ['27ABCDE1234F1Z5'],
  cin: null,
  journey: 'LEAD',
  qualification: 'NOT_YET_REVIEWED',
  marker: 'NONE',
  marker_reason: null,
  pan: 'ABCDE1234F',
  iec: null,
  source: 'MANUAL',
  relationship_manager: 'Jane RM',
  relationship_manager_user_id: 'user-owner',
  industry: null,
  year_established: null,
  date_added: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function mockUser(role: string, id: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id,
    email: 'user@aner.example',
    full_name: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double, role widened for brevity
    role: role as any,
    is_active: true,
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ExportersListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ExportersListPage — PAN/GSTIN masking (EXP-F2 acceptance criterion)', () => {
  beforeEach(() => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [PROFILE],
      limit: 100,
      offset: 0,
    });
  });

  // Decision 12: OPERATIONS sees masked tax IDs whether or not it is the
  // assigned relationship manager. The second case below used to assert the
  // opposite for an owner; both ownership states now have the same answer, so
  // the owner case asserts that rather than being dropped.
  it('masks PAN for OPERATIONS on an exporter they do not own', async () => {
    mockUser('OPERATIONS', 'someone-else');
    renderPage();
    expect(await screen.findByText('Acme Exports')).toBeInTheDocument();
    expect(screen.getByText('••••••234F')).toBeInTheDocument();
    expect(screen.queryByText('ABCDE1234F')).not.toBeInTheDocument();
  });

  it('still masks PAN for OPERATIONS on an exporter they do own', async () => {
    mockUser('OPERATIONS', 'user-owner');
    renderPage();
    expect(await screen.findByText('Acme Exports')).toBeInTheDocument();
    expect(screen.getByText('••••••234F')).toBeInTheDocument();
    expect(screen.queryByText('ABCDE1234F')).not.toBeInTheDocument();
  });

  it('never masks PAN for COMPLIANCE', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();
    expect(await screen.findByText('Acme Exports')).toBeInTheDocument();
    expect(screen.getByText('ABCDE1234F')).toBeInTheDocument();
  });
});

describe('ExportersListPage — the journey, qualification and marker filters (L2-14)', () => {
  beforeEach(() => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(searchExporterProfiles).mockReset();
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [{ ...PROFILE, marker: 'PAUSED', marker_reason: 'Seasonal' }],
      limit: 100,
      offset: 0,
    });
  });

  it('shows the journey, qualification and marker as three separate chips', async () => {
    renderPage();
    expect(await screen.findByText('Acme Exports')).toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getByTestId('journey-chip')).toHaveTextContent('Lead');
    expect(within(table).getByText('Not yet reviewed')).toBeInTheDocument();
    expect(within(table).getByText('Paused')).toBeInTheDocument();
  });

  it('asks the server for one journey stage when a tab is chosen', async () => {
    renderPage();
    await screen.findByText('Acme Exports');
    fireEvent.click(screen.getByRole('tab', { name: 'Prospect' }));
    await waitFor(() =>
      expect(searchExporterProfiles).toHaveBeenLastCalledWith(
        expect.objectContaining({ journey: 'PROSPECT' }),
      ),
    );
  });

  it('passes the qualification and marker filters to the server rather than filtering here', async () => {
    renderPage();
    await screen.findByText('Acme Exports');
    fireEvent.change(screen.getByLabelText('Qualification'), { target: { value: 'QUALIFIED' } });
    fireEvent.change(screen.getByLabelText('Relationship'), { target: { value: 'ENDED' } });
    await waitFor(() =>
      expect(searchExporterProfiles).toHaveBeenLastCalledWith(
        expect.objectContaining({ qualification: 'QUALIFIED', marker: 'ENDED' }),
      ),
    );
  });

  it('offers no lifecycle status filter and sends no status parameter', async () => {
    renderPage();
    await screen.findByText('Acme Exports');
    for (const [params] of vi.mocked(searchExporterProfiles).mock.calls) {
      expect(params).not.toHaveProperty('status');
    }
    expect(screen.queryByText(/compliance review/i)).not.toBeInTheDocument();
  });
});
