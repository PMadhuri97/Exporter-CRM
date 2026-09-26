import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  getQualification,
  listReasonCodes,
  recordQualificationOutcome,
  setExporterMarker,
} from '../api';
import type { ExporterProfileDetail, Qualification } from '../types';

import { ExporterDetailPage } from './ExporterDetailPage';

vi.mock('@/platform/auth', () => ({ useCurrentUser: vi.fn() }));
vi.mock('../api', () => ({
  getExporterProfileDetail: vi.fn(),
  listExporterContacts: vi.fn(),
  listExporterActivities: vi.fn(),
  addExporterContact: vi.fn(),
  logExporterActivity: vi.fn(),
  setExporterMarker: vi.fn(),
  updateExporterProfile: vi.fn(),
  getQualification: vi.fn(),
  listReasonCodes: vi.fn(),
  recordQualificationResults: vi.fn(),
  recordQualificationOutcome: vi.fn(),
  listVerificationResults: vi.fn(),
  triggerVerification: vi.fn(),
  reviewVerification: vi.fn(),
  getScreeningReview: vi.fn(),
  updateScreeningReviewItem: vi.fn(),
  getBankActivity: vi.fn(),
}));

const DETAIL: ExporterProfileDetail = {
  customer_id: '11111111-1111-4111-8111-111111111111',
  name: 'Acme Exports Pvt Ltd',
  country: 'IN',
  gstins: ['27ABCDE1234F1Z5'],
  cin: null,
  journey: 'LEAD',
  qualification: 'NOT_YET_REVIEWED',
  marker: 'NONE',
  marker_reason: null,
  gstin_warnings: [],
  pan: 'ABCDE1234F',
  iec: '1234567890',
  source: 'MANUAL',
  relationship_manager: 'Jane RM',
  relationship_manager_user_id: '22222222-2222-4222-8222-222222222222',
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
  allowed_marker_moves: [],
};

const QUALIFICATION: Qualification = {
  customer_id: DETAIL.customer_id,
  state: 'NOT_YET_REVIEWED',
  journey: 'LEAD',
  suggested_outcome: 'QUALIFIED',
  standings: [
    {
      criterion: {
        id: '33333333-3333-4333-8333-333333333333',
        key: 'annual_exports',
        version: 1,
        label: 'Annual exports',
        kind: 'NUMBER_THRESHOLD',
        comparison: 'AT_LEAST',
        threshold: 100000,
        unit: 'USD',
        allowed_values: null,
        required: true,
        active: true,
        created_by: null,
        created_at: '2026-09-21T00:00:00Z',
      },
      latest_result: null,
      counts: false,
    },
  ],
  results: [],
  outcomes: [],
  allowed_outcomes: [],
  can_record_results: false,
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
    vi.mocked(getQualification).mockResolvedValue(QUALIFICATION);
    vi.mocked(listReasonCodes).mockResolvedValue({
      reason_codes: [
        { code: 'low_turnover', label: 'Turnover too low', requires_note: false, active: true },
        { code: 'retired', label: 'Retired code', requires_note: false, active: false },
      ],
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

  it('masks identifiers and exposes no reveal control to OPERATIONS', async () => {
    mockUser('OPERATIONS', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByText('••••••234F')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reveal value/i })).not.toBeInTheDocument();
  });

  // Previously 'allows the assigned OPERATIONS user to reveal identifiers'.
  // Decision 12 removed the ownership exception, so the assigned relationship
  // manager gets the same treatment as anyone else in sales — masked, and no
  // reveal control at all rather than a disabled one.
  it('gives the assigned OPERATIONS user no reveal control either', async () => {
    mockUser('OPERATIONS', DETAIL.relationship_manager_user_id!);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByText('••••••234F')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reveal value/i })).not.toBeInTheDocument();
  });

  it('gives COMPLIANCE a reveal control on every identifier', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getAllByRole('button', { name: /reveal value/i })).toHaveLength(3);
  });

  it('shows the journey, qualification and marker separately, with no journey control', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    vi.mocked(getExporterProfileDetail).mockResolvedValue({
      ...DETAIL,
      marker: 'PAUSED',
      marker_reason: 'Seasonal break',
    });
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getAllByTestId('journey-chip')[0]).toHaveTextContent('Lead');
    expect(screen.getAllByText('Paused').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /move to/i })).not.toBeInTheDocument();
    // No retired lifecycle label anywhere on the page.
    expect(screen.queryByText('Contacted')).not.toBeInTheDocument();
    expect(screen.queryByText('Data Collection')).not.toBeInTheDocument();
  });

  it('offers exactly the marker moves the server listed, and none when it listed none', async () => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(getExporterProfileDetail).mockResolvedValue({
      ...DETAIL,
      allowed_marker_moves: [
        { to: 'PAUSED', reason_required: false },
        { to: 'ENDED', reason_required: true },
      ],
    });
    const { unmount } = renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByRole('button', { name: 'Pause relationship' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'End relationship' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resume relationship' })).not.toBeInTheDocument();
    unmount();

    vi.mocked(getExporterProfileDetail).mockResolvedValue(DETAIL);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.queryByRole('button', { name: /relationship$/i })).not.toBeInTheDocument();
  });

  it('asks for a reason where the server requires one and sends it with the marker', async () => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(getExporterProfileDetail).mockResolvedValue({
      ...DETAIL,
      allowed_marker_moves: [{ to: 'ENDED', reason_required: true }],
    });
    vi.mocked(setExporterMarker).mockResolvedValue({
      ...DETAIL,
      marker: 'ENDED',
    } as Awaited<ReturnType<typeof setExporterMarker>>);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    fireEvent.click(screen.getByRole('button', { name: 'End relationship' }));
    const reason = screen.getByLabelText(/reason/i);
    expect(reason).toBeRequired();
    fireEvent.change(reason, { target: { value: 'Closed the account' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(setExporterMarker).toHaveBeenCalledWith(DETAIL.customer_id, {
        marker: 'ENDED',
        reason: 'Closed the account',
      }),
    );
  });

  it('shows the qualification suggestion and no recording controls the server did not allow', async () => {
    mockUser('DEVELOPER', 'someone-else');
    renderPage();
    expect(await screen.findByText('Annual exports')).toBeInTheDocument();
    expect(screen.getByTestId('qualification-suggestion')).toHaveTextContent('Suggested: Qualified');
    expect(screen.queryByRole('form', { name: 'Record results' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Record:/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit profile' })).not.toBeInTheDocument();
  });

  it('records exactly the outcomes the server allowed, with the chosen reason codes', async () => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(getQualification).mockResolvedValue({
      ...QUALIFICATION,
      allowed_outcomes: ['NOT_QUALIFIED'],
      can_record_results: true,
    });
    vi.mocked(recordQualificationOutcome).mockResolvedValue({
      ...QUALIFICATION,
      state: 'NOT_QUALIFIED',
    });
    renderPage();
    await screen.findByRole('form', { name: 'Record results' });
    expect(screen.getByRole('form', { name: 'Record results' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Record: Qualified' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Record: Not qualified' }));
    fireEvent.click(await screen.findByLabelText('Turnover too low'));
    expect(screen.queryByLabelText('Retired code')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(recordQualificationOutcome).toHaveBeenCalledWith(DETAIL.customer_id, {
        outcome: 'NOT_QUALIFIED',
        reason_codes: ['low_turnover'],
        note: null,
      }),
    );
  });

});
