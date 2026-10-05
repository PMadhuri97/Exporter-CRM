import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import { submitRxilPackage } from '../api';

import { RxilIntakePage } from './RxilIntakePage';

// Partial: the role helpers (`isStaffRole`, …) stay real, only the session is faked.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', () => ({ submitRxilPackage: vi.fn() }));

function mockRole(role: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: 'user-1',
    email: 'user@aner.example',
    full_name: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double, role widened for brevity
    role: role as any,
    is_active: true,
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RxilIntakePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function submit(text: string) {
  fireEvent.change(screen.getByLabelText('RXIL package'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Take in' }));
}

describe('RxilIntakePage — RXIL company intake', () => {
  beforeEach(() => {
    vi.mocked(submitRxilPackage).mockReset();
    mockRole('ADMIN');
  });

  // Who may open this screen is decided at the route now: any other role
  // gets the generic NotFound and never loads the page. That is asserted, role by
  // role, in `src/routes/access.matrix.test.tsx`, which replaces the in-page
  // "Only an administrator" checks that used to be here.

  it('refuses text that is not JSON without calling the server', () => {
    renderPage();
    submit('not json');
    expect(screen.getByRole('alert')).toHaveTextContent('not valid JSON');
    expect(submitRxilPackage).not.toHaveBeenCalled();
  });

  it('sends the package as pasted and shows the result', async () => {
    vi.mocked(submitRxilPackage).mockResolvedValue({
      customer_id: '11111111-1111-4111-8111-111111111111',
      company: 'created',
      qualification: 'recorded',
      replayed: false,
      warnings: [],
    });
    renderPage();
    submit('{"package_id": "p-1", "company": {"name": "Acme"}}');
    await waitFor(() =>
      expect(submitRxilPackage).toHaveBeenCalledWith({
        package_id: 'p-1',
        company: { name: 'Acme' },
      }),
    );
    expect(await screen.findByText('Taken in')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open company' })).toHaveAttribute(
      'href',
      '/companies/11111111-1111-4111-8111-111111111111',
    );
  });

  it('shows a refusal in the server’s own words', async () => {
    vi.mocked(submitRxilPackage).mockRejectedValue(
      new Error('Matches existing companies ambiguously'),
    );
    renderPage();
    submit('{"package_id": "p-2"}');
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Matches existing companies ambiguously',
    );
  });
});
