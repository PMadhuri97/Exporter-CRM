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
// Partial: the role helpers (`isStaffRole`, …) stay real, only the session is faked.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
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
  registration_number: null,
  identity_type: 'IN_PAN',
  pipeline_status: 'IN_PIPELINE',
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

describe('ExportersListPage — identifiers are not on the list', () => {
  beforeEach(() => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [PROFILE],
      limit: 100,
      offset: 0,
    });
  });

  // This block used to assert how PAN was *masked* on each row (decision 12: masked for
  // OPERATIONS whether or not they own the company, plain for COMPLIANCE). The rows no
  // longer carry PAN or GSTIN at all, so there is no masking left here to get wrong —
  // the rule itself is still proved on the company record, in `ExporterDetailPage.test`.
  // What matters now is the stronger claim: neither value reaches this screen in any
  // form, for any role, so no reveal control can appear on a list either.
  it.each(['OPERATIONS', 'COMPLIANCE'])('shows no PAN or GSTIN for %s', async (role) => {
    mockUser(role, 'someone-else');
    renderPage();
    expect(await screen.findByText('Acme Exports')).toBeInTheDocument();

    expect(screen.queryByText('ABCDE1234F')).not.toBeInTheDocument();
    expect(screen.queryByText('••••••234F')).not.toBeInTheDocument();
    expect(screen.queryByText(/PAN/)).not.toBeInTheDocument();
    expect(screen.queryByText(/GSTIN/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reveal value/i })).not.toBeInTheDocument();
  });
});

describe('ExportersListPage — the journey, qualification and marker filters', () => {
  beforeEach(() => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(searchExporterProfiles).mockReset();
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [{ ...PROFILE, marker: 'PAUSED', marker_reason: 'Seasonal' }],
      limit: 100,
      offset: 0,
    });
  });

  it('shows the journey, qualification and marker as three separate marks, in rows not a table', async () => {
    renderPage();
    expect(await screen.findByText('Acme Exports')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    const rows = screen.getByRole('list', { name: 'Companies' });
    expect(within(rows).getByTestId('journey-chip')).toHaveTextContent('Lead');
    expect(within(rows).getByText('Not yet reviewed')).toBeInTheDocument();
    expect(within(rows).getByText('Paused')).toBeInTheDocument();
  });

  it('asks the server for one journey stage when a tab is chosen', async () => {
    renderPage();
    await screen.findByText('Acme Exports');
    fireEvent.click(screen.getByRole('radio', { name: /^Prospect/ }));
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

describe('ExportersListPage — RXIL intake link', () => {
  beforeEach(() => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 100, offset: 0 });
  });

  it('offers RXIL intake to ADMIN', () => {
    mockUser('ADMIN', 'user-admin');
    renderPage();
    expect(screen.getByRole('link', { name: 'RXIL intake' })).toBeInTheDocument();
  });

  it.each(['OPERATIONS', 'COMPLIANCE', 'DEVELOPER'])(
    'does not offer RXIL intake to %s, whom the server refuses',
    (role) => {
      mockUser(role, 'user-1');
      renderPage();
      expect(screen.queryByRole('link', { name: 'RXIL intake' })).not.toBeInTheDocument();
    },
  );
});

describe('ExportersListPage — write screens by role', () => {
  beforeEach(() => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 100, offset: 0 });
  });

  it.each(['OPERATIONS', 'COMPLIANCE', 'ADMIN'])('offers %s New company and Import companies', (role) => {
    mockUser(role, 'user-1');
    renderPage();
    expect(screen.getByRole('link', { name: /New company/ })).toHaveAttribute('href', '/companies/new');
    expect(screen.getByRole('link', { name: /Import companies/ })).toHaveAttribute('href', '/companies/import');
  });

  it.each(['DEVELOPER', 'API_USER'])(
    'offers %s neither, since the server refuses both — absent, not disabled',
    (role) => {
      mockUser(role, 'user-1');
      renderPage();
      expect(screen.queryByRole('link', { name: /New company/ })).not.toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /Import companies/ })).not.toBeInTheDocument();
      expect(screen.queryByText(/New company|Import companies/)).not.toBeInTheDocument();
    },
  );

  it('offers the identity completion list to a read-only role, which may read it', () => {
    mockUser('DEVELOPER', 'user-1');
    renderPage();
    expect(screen.getByRole('link', { name: 'Identity to complete' })).toBeInTheDocument();
  });
});
