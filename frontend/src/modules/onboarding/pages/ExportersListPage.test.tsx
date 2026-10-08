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
  relationship_manager_inactive: false,
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
  relationship_manager_name: 'Jane RM',
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

function renderPage(at = '/companies') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
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
      total: 1,
    });
  });

  // This block used to assert how PAN was *masked* on each row (masked for OPERATIONS
  // whether or not they own the company, plain for COMPLIANCE). The rows no
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

  it('keeps the country and the relationship manager on the second line', async () => {
    mockUser('OPERATIONS', 'someone-else');
    renderPage();
    expect(await screen.findByText('IN · RM Jane RM')).toBeInTheDocument();
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
      total: 1,
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
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 100, offset: 0 , total: 0 });
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
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 100, offset: 0 , total: 0 });
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

describe('ExportersListPage — the filter panel', () => {
  beforeEach(() => {
    mockUser('OPERATIONS', 'someone-else');
    vi.mocked(searchExporterProfiles).mockReset();
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [PROFILE],
      limit: 100,
      offset: 0,
      total: 1,
    });
  });

  it('filters as each choice is made, without an apply step', async () => {
    renderPage();
    await screen.findByText('Acme Exports');

    fireEvent.click(screen.getByRole('button', { name: /Filters/ }));
    fireEvent.change(await screen.findByLabelText('Buyer or seller'), {
      target: { value: 'BUYER' },
    });
    await waitFor(() =>
      expect(searchExporterProfiles).toHaveBeenLastCalledWith(
        expect.objectContaining({ trade_role: 'BUYER' }),
      ),
    );

    // The second choice joins the first rather than replacing it.
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'RXIL' } });
    await waitFor(() =>
      expect(searchExporterProfiles).toHaveBeenLastCalledWith(
        expect.objectContaining({ trade_role: 'BUYER', source: 'RXIL' }),
      ),
    );

    // And the panel is still open, so the next choice needs no second trip.
    expect(screen.getByLabelText('Country')).toBeInTheDocument();
  });

  it('counts what is in force, and clears it', async () => {
    renderPage();
    await screen.findByText('Acme Exports');

    fireEvent.click(screen.getByRole('button', { name: /Filters/ }));
    fireEvent.change(await screen.findByLabelText('Background check'), {
      target: { value: 'CLEAR' },
    });
    await waitFor(() =>
      expect(searchExporterProfiles).toHaveBeenLastCalledWith(
        expect.objectContaining({ background_check: 'CLEAR' }),
      ),
    );

    // Closed first: the panel is a modal, so while it is open the page behind it is
    // hidden from assistive tech — and from a query that asks the way one would.
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    // The badge is how a narrowed list is told apart from an empty one.
    expect(await screen.findByRole('button', { name: /Filters 1/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => {
      const [params] = vi.mocked(searchExporterProfiles).mock.calls.at(-1)!;
      expect(params).not.toHaveProperty('background_check');
    });
  });

  it('sends has_open_deals=false, which is a filter and not an absent one', async () => {
    renderPage();
    await screen.findByText('Acme Exports');

    fireEvent.click(screen.getByRole('button', { name: /Filters/ }));
    fireEvent.change(await screen.findByLabelText('Deals'), { target: { value: 'false' } });

    await waitFor(() =>
      expect(searchExporterProfiles).toHaveBeenLastCalledWith(
        expect.objectContaining({ has_open_deals: false }),
      ),
    );
  });

  it('waits for typing to stop before filtering by industry', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPage();
      await screen.findByText('Acme Exports');
      fireEvent.click(screen.getByRole('button', { name: /Filters/ }));

      const field = await screen.findByLabelText('Industry');
      for (const value of ['T', 'Te', 'Tex']) {
        fireEvent.change(field, { target: { value } });
      }
      // Nothing sent yet: a request per keystroke is what the delay exists to avoid.
      expect(vi.mocked(searchExporterProfiles).mock.calls.at(-1)?.[0]).not.toHaveProperty(
        'industry',
      );

      await vi.advanceTimersByTimeAsync(400);
      await waitFor(() =>
        expect(searchExporterProfiles).toHaveBeenLastCalledWith(
          expect.objectContaining({ industry: 'Tex' }),
        ),
      );
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('ExportersListPage — whose companies', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser('OPERATIONS', 'rm-me');
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 50, offset: 0 , total: 0 });
  });

  it('is My companies at ?owner=me, asking the server for this RM’s companies only', async () => {
    renderPage('/companies?owner=me');
    expect(await screen.findByRole('heading', { name: 'My companies' })).toBeInTheDocument();
    await waitFor(() =>
      expect(searchExporterProfiles).toHaveBeenLastCalledWith(
        expect.objectContaining({ relationship_manager: 'me' }),
      ),
    );
    // The owner is the page itself, so there is no owner filter to change it.
    expect(screen.queryByLabelText('Owner')).not.toBeInTheDocument();
    expect(await screen.findByText(/not the relationship manager of any company yet/)).toBeInTheDocument();
  });

  it('still filters by owner from the URL, with no control on the bar', async () => {
    // The dropdown that offered Unassigned and RM deactivated has gone from the filter
    // bar. The lens itself did not: `?owner=` is still read and still sent, so a link
    // or a bookmark to one of them keeps working.
    renderPage('/companies?owner=none');

    await waitFor(() =>
      expect(searchExporterProfiles).toHaveBeenLastCalledWith(
        expect.objectContaining({ relationship_manager: 'none' }),
      ),
    );
    expect(screen.queryByLabelText('Owner')).not.toBeInTheDocument();
  });

  it('says "Any relationship" without explaining the ended rule in the option', async () => {
    renderPage();
    const relationship = await screen.findByLabelText('Relationship');
    expect(within(relationship).getAllByRole('option')[0]).toHaveTextContent(
      /^Any relationship$/,
    );
  });
});

describe('ExportersListPage — exporting', () => {
  beforeEach(() => {
    mockUser('OPERATIONS', 'someone-else');
    window.localStorage.clear();
    vi.mocked(searchExporterProfiles).mockReset();
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [PROFILE],
      limit: 100,
      offset: 0,
      total: 1,
    });
  });

  it('asks which columns before writing anything', async () => {
    renderPage();
    await screen.findByText('Acme Exports');

    fireEvent.click(screen.getByRole('button', { name: /Export/ }));

    // The panel, not a download: a file nobody chose the shape of is the thing this
    // replaced.
    expect(await screen.findByRole('checkbox', { name: 'Company' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'PAN' })).not.toBeChecked();
    // It exports the whole filtered list, not the page on screen — which is the
    // distinction this panel exists to make honest.
    expect(
      screen.getByText(/Every company the filters match, not just the page on screen/),
    ).toBeInTheDocument();
  });

  it('remembers the chosen columns for the next export', async () => {
    const { unmount } = renderPage();
    await screen.findByText('Acme Exports');
    fireEvent.click(screen.getByRole('button', { name: /Export/ }));
    fireEvent.click(await screen.findByRole('checkbox', { name: 'PAN' }));
    unmount();

    renderPage();
    await screen.findByText('Acme Exports');
    fireEvent.click(screen.getByRole('button', { name: /Export/ }));
    // The habit, not a one-off: whoever exports the same columns weekly should not
    // re-tick them weekly.
    expect(await screen.findByRole('checkbox', { name: 'PAN' })).toBeChecked();
  });

  it('says which companies the file will hold, so the Source column is not read as the Source filter', async () => {
    renderPage();
    await screen.findByText('Acme Exports');

    // Narrow the rows first — the Filters panel's question.
    fireEvent.click(screen.getByRole('button', { name: /Filters/ }));
    fireEvent.change(await screen.findByLabelText('Source'), { target: { value: 'RXIL' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    fireEvent.click(screen.getByRole('button', { name: /Export/ }));
    const panel = await screen.findByRole('dialog');
    // Stated in the export panel, which has its own Source *column* checkbox.
    expect(within(panel).getByText('Source: RXIL')).toBeInTheDocument();
  });

  it('says so plainly when nothing is filtered', async () => {
    renderPage();
    await screen.findByText('Acme Exports');
    fireEvent.click(screen.getByRole('button', { name: /Export/ }));

    const panel = await screen.findByRole('dialog');
    expect(within(panel).getByText(/the boxes below choose columns, not companies/)).toBeInTheDocument();
  });

  it('refuses to export nothing', async () => {
    renderPage();
    await screen.findByText('Acme Exports');
    fireEvent.click(screen.getByRole('button', { name: /Export/ }));

    const panel = await screen.findByRole('dialog');
    for (const box of within(panel).getAllByRole('checkbox')) {
      if ((box as HTMLInputElement).checked) fireEvent.click(box);
    }
    expect(within(panel).getByRole('button', { name: 'Export' })).toBeDisabled();
  });
});
