import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth, useCurrentUser } from '@/platform/auth';

import { listOwnSessions, listUsers, updateUser } from '../api';
import type { AdminUser } from '../types';

import { SettingsPage } from './SettingsPage';

// vitest hoists vi.mock above the imports it replaces.
vi.mock('@/platform/auth', () => ({
  useCurrentUser: vi.fn(),
  useAuth: vi.fn(),
}));
vi.mock('../api', () => ({
  listUsers: vi.fn(),
  listOwnSessions: vi.fn(),
  updateUser: vi.fn(),
  createUser: vi.fn(),
  resetUserPassword: vi.fn(),
  updateOwnProfile: vi.fn(),
  changeOwnPassword: vi.fn(),
  revokeOwnSession: vi.fn(),
}));

const SELF_ID = 'self-1111';

function user(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    id: 'user-2222',
    email: 'colleague@aner.example',
    full_name: 'Colleague Two',
    role: 'OPERATIONS',
    is_active: true,
    is_verified: true,
    last_login_at: null,
    created_by: null,
    deactivated_at: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function mockSignedInAs(role: AdminUser['role']) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: SELF_ID,
    email: 'me@aner.example',
    full_name: 'Me Myself',
    role,
    is_active: true,
  });
  vi.mocked(useAuth).mockReturnValue({
    status: 'authenticated',
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listOwnSessions).mockResolvedValue({ sessions: [] });
  vi.mocked(listUsers).mockResolvedValue({
    users: [user(), user({ id: SELF_ID, email: 'me@aner.example', role: 'ADMIN' })],
    total: 2,
    limit: 25,
    offset: 0,
  });
});

describe('SettingsPage — who can see user management', () => {
  it.each<AdminUser['role']>(['OPERATIONS', 'COMPLIANCE', 'DEVELOPER', 'API_USER'])(
    'gives %s no Users tab at all — not a disabled one',
    async (role) => {
      mockSignedInAs(role);
      renderPage();

      expect(screen.queryByRole('button', { name: 'Users' })).not.toBeInTheDocument();
      // And it never asks the server for a list it cannot have.
      expect(listUsers).not.toHaveBeenCalled();
      expect(await screen.findByText('Your details')).toBeInTheDocument();
    },
  );

  it('shows ADMIN both tabs', async () => {
    mockSignedInAs('ADMIN');
    renderPage();

    expect(screen.getByRole('button', { name: 'Users' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'My profile' })).toBeInTheDocument();
  });
});

describe('UsersTab — self-protection matches the server guards', () => {
  beforeEach(() => mockSignedInAs('ADMIN'));

  it('offers no Deactivate control on your own row', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Users' }));

    await waitFor(() => expect(listUsers).toHaveBeenCalled());
    // The colleague's row has one; there is exactly one in the table, so the
    // signed-in user's own row does not.
    const deactivateButtons = await screen.findAllByRole('button', {
      name: 'Deactivate',
    });
    expect(deactivateButtons).toHaveLength(1);
    expect(screen.getByText('(you)')).toBeInTheDocument();
  });

  it('marks an account inactive immediately, before the server replies', async () => {
    // Optimistic update: the request never resolves during this assertion, so
    // anything on screen came from the cache patch, not the response.
    vi.mocked(updateUser).mockReturnValue(new Promise(() => {}));
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Users' }));
    await waitFor(() => expect(listUsers).toHaveBeenCalled());

    // Singular: exactly one row offers it (the colleague's), which is itself
    // the assertion that your own row does not.
    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }));

    expect(await screen.findByText('Inactive')).toBeInTheDocument();
  });

  it('rolls the row back when the server refuses', async () => {
    vi.mocked(updateUser).mockRejectedValue(new Error('Refused'));
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Users' }));
    await waitFor(() => expect(listUsers).toHaveBeenCalled());

    // Singular: exactly one row offers it (the colleague's), which is itself
    // the assertion that your own row does not.
    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }));

    // Back to Active, and the button is offered again — no stale "Inactive"
    // left behind claiming a change the server rejected.
    await waitFor(() =>
      expect(screen.queryByText('Inactive')).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByRole('button', { name: 'Deactivate' }),
    ).toBeInTheDocument();
  });

  it('never offers a role picker for your own account', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Users' }));
    await waitFor(() => expect(listUsers).toHaveBeenCalled());

    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit me@aner.example' }),
    );

    expect(await screen.findByLabelText('Role')).toBeDisabled();
    expect(
      screen.getByText(/cannot change your own role/i),
    ).toBeInTheDocument();
  });
});
