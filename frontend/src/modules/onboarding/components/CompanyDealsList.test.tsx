import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';

import { listCompanyDeals } from '../api';
import type { DealList, DealListItem } from '../types';

import { CompanyDealsList } from './CompanyDealsList';

vi.mock('../api', () => ({ listCompanyDeals: vi.fn() }));

const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function item(overrides: Partial<DealListItem> = {}): DealListItem {
  return {
    id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    company_id: COMPANY_ID,
    reference: 'Rotterdam shipment, March',
    stage: 'GATHERING_PAPERWORK',
    buyer_name: 'Rotterdam Trading BV',
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-02T10:00:00Z',
    ...overrides,
  };
}

function list(deals: DealListItem[]): DealList {
  return { deals, total: deals.length, limit: 50, offset: 0, can_open_deal: false };
}

function renderList(as: 'seller' | 'buyer') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompanyDealsList companyId={COMPANY_ID} as={as} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCompanyDeals).mockResolvedValue(list([item()]));
});

it('lists the deals this company is the seller on, and links to each', async () => {
  renderList('seller');

  const link = await screen.findByRole('link', { name: /Rotterdam shipment, March/ });
  expect(link).toHaveAttribute('href', '/deals/dddddddd-dddd-4ddd-8ddd-dddddddddddd');
  expect(screen.getByText(/Rotterdam Trading BV/)).toBeInTheDocument();
});

it('says a company with no deals as the seller has none', async () => {
  vi.mocked(listCompanyDeals).mockResolvedValue(list([]));
  renderList('seller');

  expect(
    await screen.findByText(/No deals where this company is the seller/),
  ).toBeInTheDocument();
});

it('says the read failed rather than that there are no deals', async () => {
  vi.mocked(listCompanyDeals).mockRejectedValue(new Error('boom'));
  renderList('seller');

  expect(await screen.findByRole('alert')).toHaveTextContent(/Couldn't load this company's deals/);
  expect(screen.queryByText(/No deals where this company is the seller/)).not.toBeInTheDocument();
});

it('asks the server for the buyer side, rather than reusing the seller read', async () => {
  // The mistake this guards against is showing the seller's deals under the buyer
  // heading — the right heading over the wrong rows.
  renderList('buyer');

  await waitFor(() => expect(listCompanyDeals).toHaveBeenCalled());
  expect(vi.mocked(listCompanyDeals).mock.calls[0]).toEqual([
    COMPANY_ID,
    expect.objectContaining({ as: 'buyer' }),
  ]);
});

it('names the seller on the buyer side, not the company whose page it is', async () => {
  // The server puts the other party in `buyer_name` both ways: on this side that is
  // the seller. Repeating this company in every row would say nothing.
  vi.mocked(listCompanyDeals).mockResolvedValue(list([item({ buyer_name: 'Acme Exports' })]));
  renderList('buyer');

  expect(await screen.findByText(/Acme Exports/)).toBeInTheDocument();
});

it('says when there are no deals on the buyer side', async () => {
  vi.mocked(listCompanyDeals).mockResolvedValue(list([]));
  renderList('buyer');

  expect(
    await screen.findByText(/No deals where this company is the buyer/),
  ).toBeInTheDocument();
});
