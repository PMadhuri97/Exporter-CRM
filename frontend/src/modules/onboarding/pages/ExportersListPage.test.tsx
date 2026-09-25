import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
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
  legal_name: 'Acme Exports',
  gstin: '27ABCDE1234F1Z5',
  pan: 'ABCDE1234F',
  iec: null,
  source: 'MANUAL',
  relationship_manager: 'Jane RM',
  relationship_manager_user_id: 'user-owner',
  lifecycle_status: 'LEAD',
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
