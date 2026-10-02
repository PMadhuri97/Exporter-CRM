import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { searchExporterProfiles } from '../api';
import type { ExporterProfileListItem } from '../types';

import { CompanyPicker } from './CompanyPicker';

vi.mock('../api', () => ({ searchExporterProfiles: vi.fn() }));

const ROTTERDAM = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const SELLER = 'ssssssss-ssss-4sss-8sss-ssssssssssss';

function company(overrides: Partial<ExporterProfileListItem> = {}): ExporterProfileListItem {
  return {
    customer_id: ROTTERDAM,
    name: 'Rotterdam Trading BV',
    country: 'NL',
    journey: 'LEAD',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double
    ...(overrides as any),
  } as ExporterProfileListItem;
}

function renderPicker(onSelect = vi.fn(), excludeCompanyId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompanyPicker onSelect={onSelect} excludeCompanyId={excludeCompanyId} />
    </QueryClientProvider>,
  );
  return onSelect;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(searchExporterProfiles).mockResolvedValue({
    profiles: [company()],
    limit: 10,
    offset: 0,
  });
});

describe('CompanyPicker (F3 stub)', () => {
  it('does not search until the term is worth a query', async () => {
    renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), { target: { value: 'R' } });
    expect(await screen.findByText(/at least two characters/)).toBeInTheDocument();
    // One letter would return most of the database and tell the user nothing.
    await waitFor(() =>
      expect(vi.mocked(searchExporterProfiles).mock.calls.every(
        ([params]) => params?.name === undefined,
      )).toBe(true),
    );
  });

  it('lists matches and hands back the company id when one is picked', async () => {
    const onSelect = renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'Rotterdam' },
    });

    fireEvent.click(await screen.findByRole('button', { name: /Rotterdam Trading BV/ }));
    expect(onSelect).toHaveBeenCalledWith(ROTTERDAM);
  });

  it('leaves the seller out, so nobody picks a company as its own buyer', async () => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [company(), company({ customer_id: SELLER, name: 'Acme Exports' })],
      limit: 10,
      offset: 0,
    });
    renderPicker(vi.fn(), SELLER);

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'company' },
    });

    expect(await screen.findByText('Rotterdam Trading BV')).toBeInTheDocument();
    // `ck_deal_buyer_is_not_the_seller` would refuse it anyway; offering the choice
    // and then failing is worse than not offering it.
    expect(screen.queryByText('Acme Exports')).not.toBeInTheDocument();
  });

  it('says plainly that identifier search and creating are not here yet', async () => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 10, offset: 0 });
    renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'nobody' },
    });

    // The stub's honest limits, rather than a dead "create" button.
    expect(await screen.findByText(/Creating one from here arrives/)).toBeInTheDocument();
  });
});
