/**
 * The Deals page: every deal, its corridor, the filters that reach the server, and
 * *New deal*.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useCurrentUser } from '@/platform/auth';

import { listAllDeals, openDeal, searchExporterProfiles } from '../api';
import type { AllDeals, DealSummary, ExporterProfileListItem } from '../types';

import { DealsPage } from './DealsPage';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', () => ({
  listAllDeals: vi.fn(),
  openDeal: vi.fn(),
  searchExporterProfiles: vi.fn(),
  getExporterProfileDetail: vi.fn(),
}));

const DEAL: DealSummary = {
  id: 'd1',
  reference: 'Rotterdam shipment',
  stage: 'OPEN',
  seller_company_id: 's1',
  seller_name: 'Acme Exports',
  seller_country: 'IN',
  buyer_company_id: 'b1',
  buyer_name: 'Rotterdam Trading',
  buyer_country: 'NL',
  corridor: 'IN-NL',
  created_at: '2026-10-01T09:00:00Z',
  updated_at: '2026-10-01T09:00:00Z',
};

const NO_BUYER: DealSummary = {
  ...DEAL,
  id: 'd2',
  reference: 'Fresh enquiry',
  buyer_company_id: null,
  buyer_name: null,
  buyer_country: null,
  corridor: null,
};

function answer(deals: DealSummary[], extra: Partial<AllDeals> = {}): AllDeals {
  return {
    deals,
    total: deals.length,
    limit: 50,
    offset: 0,
    corridors: [
      { corridor: 'IN-NL', deals: 1 },
      { corridor: 'IN-US', deals: 4 },
      { corridor: null, deals: 1 },
    ],
    can_open_deal: true,
    ...extra,
  };
}

function company(overrides: Partial<ExporterProfileListItem>): ExporterProfileListItem {
  return {
    customer_id: 'c1',
    name: 'Company',
    country: 'IN',
    gstins: [],
    cin: null,
    journey: 'PROSPECT',
    qualification: 'QUALIFIED',
    marker: 'NONE',
    marker_reason: null,
    pan: null,
    iec: null,
    registration_number: null,
    identity_type: 'IN_PAN',
    pipeline_status: 'IN_PIPELINE',
    source: 'MANUAL',
    relationship_manager: null,
    relationship_manager_user_id: null,
    industry: null,
    year_established: null,
    date_added: '2026-01-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as ExporterProfileListItem;
}

function signInAs(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({ id: 'u1', role } as unknown as ReturnType<typeof useCurrentUser>);
}

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/deals" element={<DealsPage />} />
          <Route path="/deals/:dealId" element={<p>The deal page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The parameters of the most recent list request. */
function lastRequest() {
  return vi.mocked(listAllDeals).mock.lastCall?.[0];
}

beforeEach(() => {
  vi.mocked(listAllDeals).mockReset().mockResolvedValue(answer([DEAL, NO_BUYER]));
  vi.mocked(openDeal).mockReset();
  vi.mocked(searchExporterProfiles).mockReset();
  signInAs('OPERATIONS');
});

describe('DealsPage — the list', () => {
  it('names both parties, the corridor and the stage on each row', async () => {
    renderAt('/deals');
    const rows = await screen.findAllByTestId('deal-row');
    expect(rows).toHaveLength(2);

    const first = rows[0]!;
    expect(within(first).getByRole('link', { name: 'Rotterdam shipment' })).toHaveAttribute('href', '/deals/d1');
    expect(first).toHaveTextContent('Acme Exports → Rotterdam Trading');
    expect(within(first).getByText('IN → NL')).toBeInTheDocument();
    expect(within(first).getByText('India to Netherlands')).toBeInTheDocument();
    expect(within(first).getByText('Open')).toBeInTheDocument();
    expect(screen.getByText('2 deals')).toBeInTheDocument();
  });

  it('says a deal with no buyer has no corridor yet, rather than leaving it out', async () => {
    renderAt('/deals');
    const rows = await screen.findAllByTestId('deal-row');
    expect(within(rows[1]!).getByText('No buyer yet')).toBeInTheDocument();
  });

  it('offers the corridors in use, with counts, and the unknown ones last', async () => {
    renderAt('/deals');
    await screen.findAllByTestId('deal-row');
    const select = screen.getByRole('combobox', { name: 'Corridor' });
    const labels = within(select)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(labels).toEqual([
      'All corridors',
      'IN → NL · India to Netherlands (1)',
      'IN → US · India to United States (4)',
      'Corridor not known yet (1)',
    ]);
  });

  it('a failed load is not "no deals"', async () => {
    vi.mocked(listAllDeals).mockRejectedValue(new Error('down'));
    renderAt('/deals');
    expect(await screen.findByText("Couldn't load deals.")).toBeInTheDocument();
    expect(screen.queryByText('No deals yet.')).not.toBeInTheDocument();
  });
});

describe('DealsPage — filters', () => {
  it('sends the filters in the URL to the server', async () => {
    renderAt(
      '/deals?corridor=IN-NL&stage=OPEN&q=rotterdam&seller=s1&buyer=b1&from=2026-10-01&to=2026-10-05',
    );
    await screen.findAllByTestId('deal-row');
    expect(lastRequest()).toMatchObject({
      corridors: ['IN-NL'],
      stages: ['OPEN'],
      q: 'rotterdam',
      sellerCompanyId: 's1',
      buyerCompanyId: 'b1',
      // The viewer's own days: "to" includes the whole of the 5th.
      openedFrom: new Date(2026, 9, 1).toISOString(),
      openedBefore: new Date(2026, 9, 6).toISOString(),
      offset: 0,
    });
  });

  it('sends the seller and the buyer as their own filters', async () => {
    // Together these are "the deals between these two", which `company` cannot ask:
    // it matches either side, so naming one company twice says nothing new.
    renderAt('/deals?seller=acme&buyer=north');
    await screen.findAllByTestId('deal-row');
    expect(lastRequest()).toMatchObject({
      sellerCompanyId: 'acme',
      buyerCompanyId: 'north',
    });
  });

  it('lets each side of the pair filter on its own', async () => {
    renderAt('/deals?seller=acme');
    await screen.findAllByTestId('deal-row');
    const sent = lastRequest();
    expect(sent).toMatchObject({ sellerCompanyId: 'acme' });
    // Absent, not an empty string the server would have to interpret.
    expect(sent?.buyerCompanyId).toBeUndefined();
  });

  it('ignores a malformed filter in the URL instead of failing', async () => {
    renderAt('/deals?corridor=india&stage=SIDEWAYS&from=yesterday');
    await screen.findAllByTestId('deal-row');
    expect(lastRequest()).toMatchObject({ corridors: undefined, stages: undefined, openedFrom: undefined });
  });

  it('asks for the deals whose corridor is not known yet', async () => {
    renderAt('/deals');
    await screen.findAllByTestId('deal-row');
    fireEvent.change(screen.getByRole('combobox', { name: 'Corridor' }), { target: { value: 'UNKNOWN' } });
    await waitFor(() => expect(lastRequest()?.corridors).toEqual(['UNKNOWN']));
  });

  it('filters by stage and by search', async () => {
    renderAt('/deals');
    await screen.findAllByTestId('deal-row');
    fireEvent.click(screen.getByRole('radio', { name: 'Withdrawn' }));
    await waitFor(() => expect(lastRequest()?.stages).toEqual(['WITHDRAWN']));

    const search = screen.getByRole('searchbox', { name: /Search deals/ });
    fireEvent.change(search, { target: { value: '  acme ' } });
    fireEvent.submit(search.closest('form')!);
    await waitFor(() => expect(lastRequest()).toMatchObject({ q: 'acme', stages: ['WITHDRAWN'] }));
  });

  it('says when nothing matches, and clears every filter at once', async () => {
    vi.mocked(listAllDeals).mockResolvedValue(answer([]));
    renderAt('/deals?corridor=IN-US&q=nothing');
    expect(await screen.findByText('No deals match these filters.')).toBeInTheDocument();

    vi.mocked(listAllDeals).mockResolvedValue(answer([DEAL]));
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(lastRequest()).toMatchObject({ corridors: undefined, q: undefined }));
    expect(await screen.findByRole('link', { name: 'Rotterdam shipment' })).toBeInTheDocument();
  });

  it('pages through a long list', async () => {
    vi.mocked(listAllDeals).mockResolvedValue(answer([DEAL], { total: 120 }));
    renderAt('/deals');
    expect(await screen.findByText('1–1 of 120')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(lastRequest()?.offset).toBe(50));
  });
});

describe('DealsPage — New deal', () => {
  it('opens from ?new=1, lists leads greyed with the reason, and opens the deal on the chosen seller', async () => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [
        company({ customer_id: 'lead', name: 'Lead Co', journey: 'LEAD', qualification: 'NOT_YET_REVIEWED' }),
        company({ customer_id: 'p1', name: 'Prospect Co' }),
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(openDeal).mockResolvedValue({ id: 'new-deal' } as Awaited<ReturnType<typeof openDeal>>);
    renderAt('/deals?new=1');

    const panel = await screen.findByRole('dialog', { name: 'New deal' });
    const open = within(panel).getByRole('button', { name: 'Open deal' });
    expect(open).toBeDisabled();

    fireEvent.change(within(panel).getByRole('combobox', { name: 'Seller' }), { target: { value: 'co' } });
    const lead = await within(panel).findByRole('option', { name: /Lead Co/ });
    expect(lead).toHaveAttribute('aria-disabled', 'true');
    expect(lead).toHaveTextContent("Leads can't have deals yet");
    fireEvent.click(lead);
    // Not chosen: the search is still open.
    expect(within(panel).getByRole('combobox', { name: 'Seller' })).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole('option', { name: /Prospect Co/ }));
    expect(within(panel).getByTestId('company-select-value')).toHaveTextContent('Prospect Co');
    fireEvent.change(within(panel).getByLabelText(/Reference/), { target: { value: ' Hamburg order ' } });
    fireEvent.click(open);

    await waitFor(() => expect(openDeal).toHaveBeenCalledWith('p1', { reference: 'Hamburg order' }));
    expect(await screen.findByText('The deal page')).toBeInTheDocument();
  });

  it('opens from the page header', async () => {
    renderAt('/deals');
    fireEvent.click(await screen.findByRole('button', { name: 'New deal' }));
    expect(await screen.findByRole('dialog', { name: 'New deal' })).toBeInTheDocument();
  });

  it('is absent for DEVELOPER, which reads deals and opens none', async () => {
    signInAs('DEVELOPER');
    renderAt('/deals?new=1');
    await screen.findAllByTestId('deal-row');
    expect(screen.queryByRole('button', { name: 'New deal' })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
