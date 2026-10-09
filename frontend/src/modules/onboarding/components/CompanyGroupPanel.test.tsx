import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import { getCompanyGroup, listGroupSuggestions, setParentCompany } from '../api';
import type { CompanyGroup, GroupMember } from '../types';

import { CompanyGroupPanel } from './CompanyGroupPanel';

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  getCompanyGroup: vi.fn(),
  listGroupSuggestions: vi.fn(),
  setParentCompany: vi.fn(),
}));
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function member(overrides: Partial<GroupMember>): GroupMember {
  return {
    company_id: 'a',
    name: 'Acme Holdings',
    parent_company_id: null,
    group_relationship: null,
    depth: 0,
    journey: 'CUSTOMER',
    background_check: 'CLEAR',
    risk_rating: 'LOW',
    open_deals: 2,
    open_deal_value: { USD: '125000' },
    ...overrides,
  };
}

const GROUP: CompanyGroup = {
  company_id: 'b',
  ultimate_parent_id: 'a',
  members: [
    member({}),
    member({
      company_id: 'b',
      name: 'Acme Exports',
      parent_company_id: 'a',
      group_relationship: 'SUBSIDIARY',
      depth: 1,
      open_deals: 0,
      open_deal_value: {},
      background_check: null,
      risk_rating: null,
    }),
  ],
};

function renderPanel(canEdit = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompanyGroupPanel customerId="b" canEdit={canEdit} canSeeSuggestions />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCurrentUser).mockReturnValue({ role: 'COMPLIANCE' } as ReturnType<typeof useCurrentUser>);
  vi.mocked(getCompanyGroup).mockResolvedValue(GROUP);
  vi.mocked(listGroupSuggestions).mockResolvedValue({
    suggestions: [{ company_id: 'c', name: 'Acme Trading', shared_people: ['Priya Shah'] }],
  });
  vi.mocked(setParentCompany).mockResolvedValue(GROUP);
});

describe('CompanyGroupPanel', () => {
  it('shows the tree from the ultimate parent, with each member’s deals', async () => {
    renderPanel();
    const rows = await screen.findAllByTestId('group-member');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Acme Holdings');
    expect(rows[0]).toHaveTextContent('Ultimate parent');
    expect(rows[0]).toHaveTextContent('2 open deals');
    expect(rows[1]).toHaveTextContent('Subsidiary');
  });

  it('lists companies sharing a beneficial owner without linking them', async () => {
    renderPanel();
    expect(await screen.findByText('Acme Trading')).toBeInTheDocument();
    expect(screen.getByText(/shares Priya Shah/)).toBeInTheDocument();
    expect(setParentCompany).not.toHaveBeenCalled();
  });

  it('takes the company out of its group', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Remove from group' }));
    await waitFor(() =>
      expect(setParentCompany).toHaveBeenCalledWith('b', { parent_company_id: null, relationship: null }),
    );
  });

  it('offers no controls to a reader', async () => {
    renderPanel(false);
    await screen.findAllByTestId('group-member');
    expect(screen.queryByRole('button', { name: /Set parent|Change parent/ })).not.toBeInTheDocument();
  });
});
