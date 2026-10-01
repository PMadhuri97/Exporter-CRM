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

it('does not pretend a company has no deals as the buyer before that read exists', async () => {
  // The distinction this stub exists to protect: "none" and "we cannot answer
  // that yet" must not look the same. It must also not fall back to the seller
  // read, which would show the wrong deals under the right heading.
  renderList('buyer');

  expect(
    await screen.findByText(/are not listed yet/),
  ).toBeInTheDocument();
  await waitFor(() => expect(listCompanyDeals).not.toHaveBeenCalled());
});
