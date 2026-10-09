/**
 * The header search (frontend-plan §7.5). What matters most is what it never does: a
 * masked role never sends an identifier search (decision 12) — it gets a hint
 * instead — nothing is requested until someone types, and it offers no actions.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useCurrentUser } from '@/platform/auth';
import { rememberCompany, ShellProvider } from '@/platform/shell';

import { HeaderSearch } from './HeaderSearch';

const search = vi.hoisted(() => vi.fn());

vi.mock('@/modules/onboarding/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/modules/onboarding/api')>()),
  searchExporterProfiles: search,
}));
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));

const COMPANY = '3f1c2b7e-0000-4000-8000-000000000001';

function signInAs(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: 7,
    email: 'someone@example.com',
    full_name: 'Some One',
    role,
    is_active: true,
  } as unknown as ReturnType<typeof useCurrentUser>);
}

async function renderBar(role: UserRole) {
  signInAs(role);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <ShellProvider>
          <Routes>
            <Route path="/" element={<HeaderSearch open onOpenChange={onOpenChange} role={role} />} />
            <Route path="/companies/:id" element={<p>company page</p>} />
            <Route path="/follow-ups" element={<p>follow-ups page</p>} />
          </Routes>
        </ShellProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  // The body is loaded on first open.
  await screen.findByRole('combobox', {}, { timeout: 15_000 });
  return { onOpenChange };
}

function type(text: string) {
  fireEvent.change(screen.getByRole('combobox'), { target: { value: text } });
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  search.mockResolvedValue({
    profiles: [{ customer_id: COMPANY, name: 'Bharat Precision Metals', country: 'IN', journey: 'CUSTOMER' }],
    limit: 8,
    offset: 0,
  });
});

// The first test pays for loading the lazy body (cmdk and the company finder); under
// a full parallel run that can take longer than the 5 s default.
describe('HeaderSearch', { timeout: 30_000 }, () => {
  it('sends nothing until someone types', async () => {
    await renderBar('OPERATIONS');
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });

  it('finds a company by name and opens it', async () => {
    await renderBar('OPERATIONS');
    type('bharat');
    const option = await screen.findByRole('option', { name: /Bharat Precision Metals/ });
    expect(search).toHaveBeenCalledWith({ name: 'bharat', limit: 8 });
    fireEvent.click(option);
    expect(await screen.findByText('company page')).toBeInTheDocument();
  });

  it.each<UserRole>(['OPERATIONS', 'DEVELOPER', 'ADMIN'])(
    'never sends an identifier search for %s, and says how to match one',
    async (role) => {
      await renderBar(role);
      type('AAAPL1234C');
      expect(await screen.findByText(/To match a company by PAN, use New company/)).toBeInTheDocument();
      // Past the debounce, still nothing sent.
      await new Promise((resolve) => setTimeout(resolve, 300));
      expect(search).not.toHaveBeenCalled();
    },
  );

  it.each<UserRole>(['COMPLIANCE'])('searches a full PAN for %s, who may see it', async (role) => {
    await renderBar(role);
    type('aaapl1234c');
    await waitFor(() => expect(search).toHaveBeenCalledWith({ pan: 'AAAPL1234C', limit: 8 }));
  });

  it('shows the companies this viewer opened last, before anything is typed', async () => {
    rememberCompany('7', { id: COMPANY, name: 'Coastal Seafood Exports' });
    await renderBar('OPERATIONS');
    expect(screen.getByRole('option', { name: /Coastal Seafood Exports/ })).toBeInTheDocument();
  });

  it('offers no actions: only companies, recent companies and pages', async () => {
    await renderBar('OPERATIONS');
    const groups = screen.getAllByRole('group').map((group) => group.getAttribute('aria-labelledby'));
    expect(groups.length).toBeGreaterThan(0);
    expect(screen.queryByText('On this page')).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Log a call/ })).not.toBeInTheDocument();
  });

  it('goes to a page the role has', async () => {
    await renderBar('DEVELOPER');
    fireEvent.click(screen.getByRole('option', { name: /Follow-ups/ }));
    expect(await screen.findByText('follow-ups page')).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Qualification criteria/ })).not.toBeInTheDocument();
  });
});

describe('HeaderSearch at rest', () => {
  it('is a button that opens the field, and names its keys', () => {
    signInAs('OPERATIONS');
    const onOpenChange = vi.fn();
    render(
      <MemoryRouter>
        <HeaderSearch open={false} onOpenChange={onOpenChange} role="OPERATIONS" />
      </MemoryRouter>,
    );
    const field = screen.getByRole('button', { name: 'Search companies and pages' });
    expect(field).toHaveAttribute('aria-keyshortcuts', '/ Control+K Meta+K');
    fireEvent.click(field);
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(search).not.toHaveBeenCalled();
  });
});
