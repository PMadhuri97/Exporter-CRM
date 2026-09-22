import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import {
  getExporterProfileDetail,
  listExporterActivities,
  listExporterContacts,
  listVerificationResults,
  getScreeningReview,
  getBankActivity,
} from '../api';
import { PERMITTED_LIFECYCLE_TRANSITIONS } from '../constants';
import { lifecycleActionLabel } from '../components/LifecycleMoveControl';
import type { ExporterProfileDetail } from '../types';

import { ExporterDetailPage } from './ExporterDetailPage';

vi.mock('@/platform/auth', () => ({ useCurrentUser: vi.fn() }));
vi.mock('../api', () => ({
  getExporterProfileDetail: vi.fn(),
  listExporterContacts: vi.fn(),
  listExporterActivities: vi.fn(),
  addExporterContact: vi.fn(),
  logExporterActivity: vi.fn(),
  transitionExporterLifecycle: vi.fn(),
  listVerificationResults: vi.fn(),
  triggerVerification: vi.fn(),
  reviewVerification: vi.fn(),
  getScreeningReview: vi.fn(),
  updateScreeningReviewItem: vi.fn(),
  getBankActivity: vi.fn(),
}));

const DETAIL: ExporterProfileDetail = {
  customer_id: '11111111-1111-4111-8111-111111111111',
  gstin: '27ABCDE1234F1Z5',
  pan: 'ABCDE1234F',
  iec: '1234567890',
  source: 'MANUAL',
  relationship_manager: 'Jane RM',
  relationship_manager_user_id: '22222222-2222-4222-8222-222222222222',
  lifecycle_status: 'LEAD',
  industry: 'Textiles',
  export_markets: ['US', 'GB'],
  products: ['Garments'],
  year_established: 2019,
  website: 'https://example.com',
  date_added: '2026-09-21T00:00:00Z',
  created_at: '2026-09-21T00:00:00Z',
  updated_at: '2026-09-21T00:00:00Z',
  contacts: [],
  recent_activities: [],
  onboarding_history: [
    {
      onboarding_id: '33333333-3333-4333-8333-333333333333',
      status: 'DRAFT',
      legal_name: 'Acme Exports Pvt Ltd',
      initiated_at: null,
      completed_at: null,
      rejection_category: null,
    },
  ],
};

function mockUser(role: string, id: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id,
    email: 'user@aner.example',
    full_name: 'Jane RM',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- concise test fixture
    role: role as any,
    is_active: true,
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/exporters/${DETAIL.customer_id}`]}>
        <Routes>
          <Route path="/exporters/:customerId" element={<ExporterDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ExporterDetailPage — E9', () => {
  beforeEach(() => {
    vi.mocked(getExporterProfileDetail).mockResolvedValue(DETAIL);
    vi.mocked(listExporterContacts).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      contacts: [],
    });
    vi.mocked(listExporterActivities).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      activities: [],
    });
    vi.mocked(listVerificationResults).mockResolvedValue({
      entity_type: 'EXPORTER',
      entity_reference: DETAIL.customer_id,
      results: [],
      total: 0,
    });
    vi.mocked(getScreeningReview).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      items: [],
    });
    vi.mocked(getBankActivity).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      connected_accounts: 0,
      last_synced_at: null,
      open_findings: 0,
      findings: [],
    });
  });

  it('renders relationship sections safely with no contacts or activity', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' })).toBeInTheDocument();
    expect(screen.getByText('No contacts yet. Add the first person you work with.')).toBeInTheDocument();
    expect(screen.getByText('No activity logged yet.')).toBeInTheDocument();
    expect(await screen.findByText('No screening results yet')).toBeInTheDocument();
  });

  it('masks identifiers and exposes no reveal control to non-owner OPERATIONS', async () => {
    mockUser('OPERATIONS', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByText('••••••234F')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reveal value/i })).not.toBeInTheDocument();
  });

  it('allows the assigned OPERATIONS user to reveal identifiers', async () => {
    mockUser('OPERATIONS', DETAIL.relationship_manager_user_id!);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getAllByRole('button', { name: /reveal value/i })).toHaveLength(3);
  });

  it('defines only CONTACTED as the legal next state from LEAD', () => {
    expect(PERMITTED_LIFECYCLE_TRANSITIONS.LEAD).toEqual(['CONTACTED']);
    expect(PERMITTED_LIFECYCLE_TRANSITIONS.LEAD).not.toContain('ACTIVE');
    expect(PERMITTED_LIFECYCLE_TRANSITIONS.LEAD).not.toContain('ONBOARDED');
  });

  it('keeps the compliance send-back label and both legal next states deterministic', () => {
    expect(PERMITTED_LIFECYCLE_TRANSITIONS.COMPLIANCE_REVIEW).toEqual([
      'DATA_COLLECTION',
      'ONBOARDED',
    ]);
    expect(lifecycleActionLabel('COMPLIANCE_REVIEW', 'DATA_COLLECTION')).toBe(
      'Send back to Data Collection',
    );
    expect(lifecycleActionLabel('COMPLIANCE_REVIEW', 'ONBOARDED')).toBe(
      'Move to Onboarded',
    );
  });

});
