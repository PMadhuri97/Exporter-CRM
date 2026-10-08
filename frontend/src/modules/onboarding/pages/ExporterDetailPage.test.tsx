import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';
import { ShellProvider } from '@/platform/shell';

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
  listTradeRelationships,
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
  // `ConversationPanel` calls these itself rather than
  // taking them as props — the shell was never given the gauge to hold.
  // The factory has to list them, because
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
  // The Deals tab's trade history, both sides.
  listTradeRelationships: vi.fn(),
  getTradeRelationship: vi.fn(),
  getTradeInvoice: vi.fn(),
}));

const DETAIL: ExporterProfileDetail = {
  customer_id: '11111111-1111-4111-8111-111111111111',
  name: 'Acme Exports Pvt Ltd',
  country: 'IN',
  gstins: ['27ABCDE1234F1Z5'],
  cin: null,
  relationship_manager_inactive: false,
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
  registration_number: null,
  identity_type: 'IN_PAN',
  pipeline_status: 'IN_PIPELINE',
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

function renderPage(tab?: string, withShell = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const url = `/companies/${DETAIL.customer_id}${tab ? `?tab=${tab}` : ''}`;
  const routes = (
    <Routes>
      <Route path="/companies/:customerId" element={<ExporterDetailPage />} />
    </Routes>
  );
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        {withShell ? (
          <ShellProvider>
            {routes}
          </ShellProvider>
        ) : (
          routes
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ExporterDetailPage — screening review', () => {
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
    vi.mocked(listCompanyDeals).mockResolvedValue({
      deals: [],
      total: 0,
      limit: 50,
      offset: 0,
      can_open_deal: false,
    });
    vi.mocked(listCompanyHistory).mockResolvedValue({ entries: [], total: 0, limit: 25, offset: 0 });
    vi.mocked(listTradeRelationships).mockResolvedValue({ relationships: [], total: 0 });
  });

  it('renders relationship sections safely with no contacts or activity', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage('conversation');
    expect(await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' })).toBeInTheDocument();
    expect(screen.getByText('No one recorded yet.')).toBeInTheDocument();
    expect(screen.getByText('No activity logged yet.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Background check' }));
    expect(await screen.findByText('No screening results yet')).toBeInTheDocument();
  });

  it('opens on the tab named in the URL, and on Details otherwise', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    const { unmount } = renderPage('qualification');
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByRole('tab', { name: 'Qualification' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('Annual exports')).toBeInTheDocument();
    unmount();

    renderPage('no-such-tab');
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByRole('tab', { name: 'Details' })).toHaveAttribute('aria-selected', 'true');
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

    // The lane chips are the lanes present (frontend-plan §6.5); choosing one asks
    // the server for that dimension.
    expect(screen.queryByRole('button', { name: 'Journey' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Relationship' }));
    await waitFor(() =>
      expect(listCompanyHistory).toHaveBeenLastCalledWith(
        DETAIL.customer_id,
        expect.objectContaining({ dimension: 'marker', offset: 0 }),
      ),
    );
  });

  it('masks identifiers and exposes no reveal control to OPERATIONS', async () => {
    mockUser('OPERATIONS', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    // In the profile, masked. The header's summary strip no longer carries PAN.
    expect(screen.getAllByText('••••••234F')).toHaveLength(1);
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
    expect(screen.getAllByText('••••••234F')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /reveal value/i })).not.toBeInTheDocument();
  });

  it('gives COMPLIANCE a reveal control on every identifier', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    // PAN and IEC in the profile. `cin` and `registration_number` are null in this
    // fixture, and a null value renders no reveal control — there is nothing to reveal.
    //
    // Two, not four: PAN and GSTIN left the header's summary strip, which carries state
    // rather than identifiers. The panel's own GSTIN row had already gone with the branch
    // routes — the GSTINs are `GstRegistrationsSection` now, where each is a branch with a
    // state, a status and possibly a flag rather than a bare value.
    expect(screen.getAllByRole('button', { name: /reveal value/i })).toHaveLength(2);
  });

  it('shows no website at all, whatever is stored', async () => {
    // The field retired. Stored values are kept — nothing is
    // destroyed — and simply never shown. This replaces the test that proved an
    // http(s) value became a link and anything else stayed text: with nothing
    // rendered, the `javascript:` href that rule existed for cannot arise here.
    mockUser('COMPLIANCE', 'someone-else');
    vi.mocked(getExporterProfileDetail).mockResolvedValue({
      ...DETAIL,
      // Still on the record, as a company created before the field retired has.
      website: 'https://example.com',
    } as never);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });

    expect(screen.queryByText('Website')).not.toBeInTheDocument();
    expect(screen.queryByText(/example\.com/)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /example\.com/ })).not.toBeInTheDocument();
  });

  it('replaces the journey chip and both gauges for a buyer-only company', async () => {
    // Its `journey` column reads LEAD because the column is NOT NULL, not because
    // anyone judged it — and the server refuses to qualify it. Showing a
    // Lead chip and an empty qualification form would invite exactly the action that
    // 409s.
    mockUser('COMPLIANCE', 'someone-else');
    vi.mocked(getExporterProfileDetail).mockResolvedValue({
      ...DETAIL,
      pipeline_status: 'NOT_IN_PIPELINE',
    } as never);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });

    expect(screen.getByText('Outside pipeline')).toBeInTheDocument();
    expect(screen.queryByTestId('journey-chip')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /Qualification/ }));
    expect(await screen.findByTestId('not-in-pipeline-notice')).toBeInTheDocument();
    expect(screen.getByText(/Qualification is not needed/)).toBeInTheDocument();
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
    // The journey is a read-only path: Lead is the current step, and no step is a button.
    const journey = screen.getByRole('list', { name: 'Journey' });
    expect(within(journey).getByText('Lead').closest('li')).toHaveAttribute('aria-current', 'step');
    expect(within(journey).queryByRole('button')).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('tab', { name: 'Details' }));
    expect(await screen.findByRole('heading', { name: 'Company profile' })).toBeInTheDocument();
    // Facts are inline edits for staff (frontend-plan §8.5); a read-only role gets text.
    expect(screen.queryByRole('button', { name: /^Edit / })).not.toBeInTheDocument();
  });

  it('starts every masked identifier empty when OPERATIONS edits it, CIN included', async () => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(getExporterProfileDetail).mockResolvedValue({
      ...DETAIL,
      cin: '•••••••••••••••••6789',
    });
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    // Each fact is edited in place; a masked one starts empty, never as its bullets.
    for (const label of ['PAN', 'IEC', 'CIN']) {
      fireEvent.click(screen.getByRole('button', { name: `Edit ${label}` }));
      const input = await screen.findByRole('textbox', { name: label });
      expect(input).toHaveValue('');
      expect(input).toHaveAttribute('placeholder', 'Hidden — type to replace');
      fireEvent.keyDown(input, { key: 'Escape' });
    }
  });

  it('sends a year that is not a number as typed, for the server to refuse, never as a cleared year', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    vi.mocked(updateExporterProfile).mockResolvedValue(DETAIL);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    fireEvent.click(screen.getByRole('button', { name: 'Edit Year established' }));
    const input = await screen.findByRole('textbox', { name: 'Year established' });
    fireEvent.change(input, { target: { value: 'twenty' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(updateExporterProfile).toHaveBeenCalledWith(DETAIL.customer_id, {
        year_established: 'twenty',
        // What the screen showed: a field someone else changed since is refused.
        seen: { year_established: 2019 },
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
        relationship_manager_user_id: null,
      }),
    );
  });

  it('names each other company holding a shared GSTIN once, one link each', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    vi.mocked(getExporterProfileDetail).mockResolvedValue({
      ...DETAIL,
      gstin_warnings: [
        { gstin: '27ABCDE1234F1Z5', other_customer_ids: ['other-1'] },
        { gstin: '29ABCDE1234F1Z5', other_customer_ids: ['other-2', 'other-3'] },
      ],
    });
    renderPage();
    const warning = await screen.findByText(/A GSTIN on this company is also on another company/);
    const list = within(warning.closest('section')!).getAllByRole('listitem');
    const [one, two] = list as [HTMLElement, HTMLElement];
    expect(one).toHaveTextContent(/also on another company$/);
    expect(two).toHaveTextContent(/also on 2 other companies: company 1 and company 2$/);
    expect(within(two).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual([
      '/companies/other-2',
      '/companies/other-3',
    ]);
  });

  it('asks only for a note when recording Qualified, never for a rejection reason', async () => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(getQualification).mockResolvedValue({
      ...QUALIFICATION,
      allowed_outcomes: ['QUALIFIED', 'NOT_QUALIFIED'],
    });
    vi.mocked(recordQualificationOutcome).mockResolvedValue({
      ...QUALIFICATION,
      state: 'QUALIFIED',
    });
    renderPage('qualification');
    fireEvent.click(await screen.findByRole('button', { name: 'Record: Qualified' }));
    const form = await screen.findByRole('form', { name: 'Record outcome' });
    // Every seeded reason code is a reason to reject, so none is offered here.
    expect(within(form).queryByText('Reasons')).not.toBeInTheDocument();
    expect(within(form).queryByLabelText('Turnover too low')).not.toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText('Note'), { target: { value: 'Meets all four' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(recordQualificationOutcome).toHaveBeenCalledWith(DETAIL.customer_id, {
        outcome: 'QUALIFIED',
        reason_codes: [],
        note: 'Meets all four',
        // The company has an RM already, so none is sent.
        relationship_manager_user_id: null,
      }),
    );
  });

  // Task 3.22's company-page half. Both sides are asked for, because a company can
  // sell to one counterparty and buy from another, and one list mixing them would
  // read differently row by row.
  it('shows deals first, and trade as its own view, so a buyer is not listed twice', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage('deals');

    // The Deals view: no trade list under it.
    expect(await screen.findByRole('radio', { name: 'Deals' })).toBeChecked();
    expect(screen.queryByText('Sold to')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: 'Trade' }));
    expect(await screen.findByText('Sold to')).toBeInTheDocument();
    // Nobody has invoiced this company, so there is no empty "Bought from" list.
    await waitFor(() => expect(screen.queryByText('Bought from')).not.toBeInTheDocument());
    await waitFor(() => {
      expect(listTradeRelationships).toHaveBeenCalledWith(DETAIL.customer_id, {
        as: 'seller',
      });
      expect(listTradeRelationships).toHaveBeenCalledWith(DETAIL.customer_id, {
        as: 'buyer',
      });
    });
    // An empty seller side says why it is empty rather than implying the company has
    // never sold anything.
    expect(
      await screen.findByText(/Nobody recorded as a buyer from this company yet/),
    ).toBeInTheDocument();
  });
});
