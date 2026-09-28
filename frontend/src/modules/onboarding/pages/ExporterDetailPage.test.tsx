import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  updateExporterProfile,
  getExporterConversation,
  listConversationHistory,
  listCompanyDeals,
  listCompanyHistory,
} from '../api';
import type { ExporterProfileDetail, Qualification } from '../types';

import { ExporterDetailPage } from './ExporterDetailPage';

// Partial: the role helpers (`isStaffRole`, …) stay real, only the session is faked.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
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
  // Developer 3A, L3-03. `ConversationPanel` calls these itself rather than
  // taking them as props — the shell was never given the gauge to hold, and
  // Developer 3 does not edit this page. The factory has to list them, because
  // `vi.mock` with a factory replaces the whole module: a function left out is
  // `undefined` at the call site, not a passthrough.
  getExporterConversation: vi.fn(),
  setExporterConversation: vi.fn(),
  listConversationHistory: vi.fn(),
  // The tabbed page: the Deals tab's count, the Documents tab and the History tab.
  listCompanyDeals: vi.fn(),
  listCompanyDocuments: vi.fn(),
  getDocumentCategories: vi.fn(),
  listCompanyHistory: vi.fn(),
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

/** Opens the company page, on `tab` when given (`?tab=`). */
function renderPage(tab?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const url = `/companies/${DETAIL.customer_id}${tab ? `?tab=${tab}` : ''}`;
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/companies/:customerId" element={<ExporterDetailPage />} />
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
      capabilities: { can_record_result: true, can_review: true },
    });
    vi.mocked(getScreeningReview).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      items: [],
      catalogue: [],
      capabilities: { can_record_decision: true },
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
      provider_feed_connected: false,
      provider_feed_status: 'NOT_CONNECTED',
      provider_feed_message: 'No bank-monitoring provider feed is connected.',
      connected_accounts: 0,
      last_synced_at: null,
      open_findings: 0,
      findings: [],
    });
    // The gauge as a LEAD has it: the default value and no moves, because the
    // conversation gauge applies from PROSPECT onward. `DETAIL.journey` is 'LEAD',
    // so this is the consistent answer for this fixture.
    vi.mocked(getExporterConversation).mockResolvedValue({
      company_id: DETAIL.customer_id,
      conversation: 'NOT_CONTACTED',
      check_back_on: null,
      journey: 'LEAD',
      allowed_moves: [],
    });
    vi.mocked(listConversationHistory).mockResolvedValue({
      entries: [],
      total: 0,
      limit: 20,
      offset: 0,
    });
    vi.mocked(listCompanyDeals).mockResolvedValue({ deals: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(listCompanyHistory).mockResolvedValue({ entries: [], total: 0, limit: 25, offset: 0 });
  });

  it('renders relationship sections safely with no contacts or activity', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage('conversation');
    expect(await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' })).toBeInTheDocument();
    expect(screen.getByText('No contacts yet. Add the first person you work with.')).toBeInTheDocument();
    expect(screen.getByText('No activity logged yet.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Background check' }));
    expect(await screen.findByText('No screening results yet')).toBeInTheDocument();
  });

  it('opens on the tab named in the URL, and on Overview otherwise', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    const { unmount } = renderPage('qualification');
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByRole('tab', { name: 'Qualification' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('Annual exports')).toBeInTheDocument();
    unmount();

    renderPage('no-such-tab');
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { name: 'Company profile' })).toBeInTheDocument();
  });

  it('gives DEVELOPER no Background check tab, since the server refuses it the results', async () => {
    mockUser('DEVELOPER', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.queryByRole('tab', { name: 'Background check' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'History' })).toBeInTheDocument();
  });

  it('shows the company history, with who changed what and why', async () => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(listCompanyHistory).mockResolvedValue({
      entries: [
        {
          id: '44444444-4444-4444-8444-444444444444',
          company_id: DETAIL.customer_id,
          deal_id: null,
          dimension: 'marker',
          event_type: 'marker_set',
          from_value: 'NONE',
          to_value: 'PAUSED',
          actor_id: 'user-7',
          reason: 'Seasonal break',
          source: 'exporter_profile_service.set_marker',
          details: null,
          occurred_at: '2026-09-27T10:00:00Z',
        },
      ],
      total: 1,
      limit: 25,
      offset: 0,
    });
    renderPage('history');
    const row = await screen.findByTestId('history-row');
    expect(row).toHaveTextContent('Relationship');
    expect(row).toHaveTextContent('None →');
    expect(row).toHaveTextContent('Paused');
    expect(row).toHaveTextContent('“Seasonal break”');
    expect(row).toHaveTextContent('By user-7');

    fireEvent.click(screen.getByRole('button', { name: 'Journey' }));
    await waitFor(() =>
      expect(listCompanyHistory).toHaveBeenLastCalledWith(
        DETAIL.customer_id,
        expect.objectContaining({ dimension: 'journey', offset: 0 }),
      ),
    );
  });

  it('masks identifiers and exposes no reveal control to OPERATIONS', async () => {
    mockUser('OPERATIONS', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    // In the header's summary strip and in the profile, masked in both.
    expect(screen.getAllByText('••••••234F')).toHaveLength(2);
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
    expect(screen.getAllByText('••••••234F')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /reveal value/i })).not.toBeInTheDocument();
  });

  it('gives COMPLIANCE a reveal control on every identifier', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    // PAN, GSTIN and IEC in the profile, plus PAN and GSTIN in the header strip.
    expect(screen.getAllByRole('button', { name: /reveal value/i })).toHaveLength(5);
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
    renderPage('qualification');
    expect(await screen.findByText('Annual exports')).toBeInTheDocument();
    expect(screen.getByTestId('qualification-suggestion')).toHaveTextContent('Suggested: Qualified');
    expect(screen.queryByRole('form', { name: 'Record results' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Record:/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Overview' }));
    expect(await screen.findByRole('heading', { name: 'Company profile' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit profile' })).not.toBeInTheDocument();
  });

  it('starts every masked identifier empty in the edit form for OPERATIONS, CIN included', async () => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(getExporterProfileDetail).mockResolvedValue({
      ...DETAIL,
      cin: '•••••••••••••••••6789',
    });
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    const form = await screen.findByRole('form', { name: 'Edit profile' });
    for (const label of ['PAN', 'GSTINs (comma-separated)', 'IEC', 'CIN']) {
      const input = within(form).getByLabelText(label);
      expect(input).toHaveValue('');
      expect(input).toHaveAttribute('placeholder', 'Hidden — type to replace');
    }
  });

  it('sends a year that is not a number as typed, for the server to refuse, never as a cleared year', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    vi.mocked(updateExporterProfile).mockResolvedValue(DETAIL);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit profile' }));
    const form = await screen.findByRole('form', { name: 'Edit profile' });
    fireEvent.change(within(form).getByLabelText('Year established'), {
      target: { value: 'twenty' },
    });
    fireEvent.click(within(form).getByRole('button', { name: 'Save profile' }));
    await waitFor(() =>
      expect(updateExporterProfile).toHaveBeenCalledWith(DETAIL.customer_id, {
        year_established: 'twenty',
      }),
    );
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
    renderPage('qualification');
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
