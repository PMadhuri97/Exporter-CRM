import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { listCompanyDeals } from '../../api';
import type { DealListItem } from '../../types';

import { DealsPanel } from './DealsPanel';

vi.mock('../../api', () => ({
  listCompanyDeals: vi.fn(),
  openDeal: vi.fn(),
}));

const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function dealRow(overrides: Partial<DealListItem> = {}): DealListItem {
  return {
    id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    company_id: COMPANY_ID,
    reference: 'Rotterdam shipment, March',
    stage: 'OPEN',
    buyer_name: null,
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-01T10:00:00Z',
    ...overrides,
  };
}

function renderPanel(isStaff = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DealsPanel customerId={COMPANY_ID} isStaff={isStaff} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCompanyDeals).mockResolvedValue({
    deals: [dealRow()],
    total: 1,
    limit: 50,
    offset: 0,
    can_open_deal: true,
  });
});

describe('DealsPanel', () => {
  it('lists the company deals with their stage', async () => {
    renderPanel();

    await waitFor(() => expect(listCompanyDeals).toHaveBeenCalledWith(COMPANY_ID, {}));
    expect(await screen.findByText('Rotterdam shipment, March')).toBeInTheDocument();
    expect(screen.getByText('Open')).toBeInTheDocument();
    // A deal with no buyer yet says so rather than showing an empty cell.
    expect(screen.getByText(/No buyer recorded yet/)).toBeInTheDocument();
  });

  it('shows an honest empty state, and invites staff to open the first deal', async () => {
    vi.mocked(listCompanyDeals).mockResolvedValue({
      deals: [],
      total: 0,
      limit: 50,
      offset: 0,
      can_open_deal: true,
    });
    renderPanel();

    expect(await screen.findByText(/No deals yet/)).toBeInTheDocument();
    expect(
      screen.getByText(/Open one when this company has something to finance/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Open a deal/ })).toBeInTheDocument();
  });

  it('offers staff no deal on a company the server says is not ready — a LEAD', async () => {
    vi.mocked(listCompanyDeals).mockResolvedValue({
      deals: [],
      total: 0,
      limit: 50,
      offset: 0,
      can_open_deal: false,
    });
    renderPanel(true);

    expect(await screen.findByText(/No deals yet/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Open a deal/ })).not.toBeInTheDocument();
    expect(screen.getByText(/once the company has been qualified/)).toBeInTheDocument();
  });

  it('gives a non-staff viewer no action and no invitation', async () => {
    vi.mocked(listCompanyDeals).mockResolvedValue({
      deals: [],
      total: 0,
      limit: 50,
      offset: 0,
      can_open_deal: false,
    });
    renderPanel(false);

    expect(await screen.findByText(/No deals yet/)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Open a deal/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Open one when this company/),
    ).not.toBeInTheDocument();
  });

  it('always offers the way through to the company documents', async () => {
    renderPanel(false);

    const link = await screen.findByRole('link', { name: 'Company documents' });
    // A tab of the company page now, not a page of its own.
    expect(link).toHaveAttribute('href', `/companies/${COMPANY_ID}?tab=documents`);
  });

  it('links each deal to its own page', async () => {
    renderPanel();

    // The whole row is the link, so its name carries the buyer line too.
    const link = await screen.findByRole('link', {
      name: /Rotterdam shipment, March/,
    });
    expect(link).toHaveAttribute('href', '/deals/dddddddd-dddd-4ddd-8ddd-dddddddddddd');
  });
});
