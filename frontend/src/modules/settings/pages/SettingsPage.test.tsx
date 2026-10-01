import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth, useCurrentUser } from '@/platform/auth';

import {
  getMyPermissions,
  getPermissionCatalog,
  listOwnSessions,
  listRoles,
  listUsers,
  updateUser,
} from '../api';
import type { AdminUser, PermissionRef, Role } from '../types';

import { SettingsPage } from './SettingsPage';

// vitest hoists vi.mock above the imports it replaces.
// Partial: only the session is faked. `roleLabel` and the role predicates are pure
// and stay real, so these tests exercise the label a person actually sees rather than
// a stub that would pass whatever it was given.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
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
  getMyPermissions: vi.fn(),
  listRoles: vi.fn(),
  getPermissionCatalog: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
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
    role_id: null,
    ...overrides,
  };
}

function role(overrides: Partial<Role> = {}): Role {
  return {
    id: 'role-1',
    slug: 'operations',
    name: 'Operations',
    description: 'Day-to-day CRM work.',
    builtin_role: 'OPERATIONS',
    is_builtin: true,
    is_assignable: true,
    permissions: [{ module: 'exporters', action: 'view' }],
    user_count: 3,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

/** Grant exactly these permissions to the signed-in user. */
function signedInWith(permissions: PermissionRef[], roleName = 'Administrator') {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: SELF_ID,
    email: 'me@aner.example',
    full_name: 'Me Myself',
    role: 'ADMIN',
    is_active: true,
  });
  vi.mocked(useAuth).mockReturnValue({
    status: 'authenticated',
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
  });
  vi.mocked(getMyPermissions).mockResolvedValue({
    role: 'ADMIN',
    role_id: null,
    role_name: roleName,
    permissions,
  });
}

const ALL_USER_PERMISSIONS: PermissionRef[] = [
  { module: 'users', action: 'view' },
  { module: 'users', action: 'create' },
  { module: 'users', action: 'edit' },
];
const ALL_ROLE_PERMISSIONS: PermissionRef[] = [
  { module: 'roles', action: 'view' },
  { module: 'roles', action: 'create' },
  { module: 'roles', action: 'edit' },
  { module: 'roles', action: 'delete' },
];

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
  vi.mocked(listRoles).mockResolvedValue({
    roles: [
      role(),
      role({
        id: 'role-custom',
        slug: 'credit-reviewer',
        name: 'Credit reviewer',
        builtin_role: null,
        is_builtin: false,
        user_count: 0,
      }),
    ],
  });
  vi.mocked(getPermissionCatalog).mockResolvedValue({
    modules: [
      {
        key: 'users',
        label: 'User management',
        description: 'Accounts that can sign in',
        enforced: true,
        actions: [{ key: 'view', label: 'View', description: 'See the user list' }],
      },
      {
        key: 'exporters',
        label: 'Companies',
        description: 'Exporter profiles',
        enforced: false,
        actions: [{ key: 'view', label: 'View', description: 'See companies' }],
      },
    ],
  });
});

describe('SettingsPage — tabs follow permissions, not role names', () => {
  it('shows no admin tabs to someone with no permissions', async () => {
    signedInWith([], 'API user');
    renderPage();

    expect(await screen.findByText('Your details')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Users' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Roles' })).not.toBeInTheDocument();
    // And it never asks for a list it cannot have.
    expect(listUsers).not.toHaveBeenCalled();
  });

  it('shows the Users tab to any role granted users:view — the whole point of RBAC', async () => {
    // This is the case that used to need a code change: a non-ADMIN role with
    // the permission granted now gets the tab.
    signedInWith([{ module: 'users', action: 'view' }], 'Compliance');
    renderPage();

    expect(await screen.findByRole('button', { name: 'Users' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Roles' })).not.toBeInTheDocument();
  });

  it('shows the Roles tab only with roles:view', async () => {
    signedInWith(ALL_ROLE_PERMISSIONS);
    renderPage();

    expect(await screen.findByRole('button', { name: 'Roles' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Users' })).not.toBeInTheDocument();
  });

  it('renders no admin tab while permissions are still loading', () => {
    signedInWith(ALL_USER_PERMISSIONS);
    // Never resolves: anything on screen was rendered without an answer.
    vi.mocked(getMyPermissions).mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.queryByRole('button', { name: 'Users' })).not.toBeInTheDocument();
  });
});

describe('UsersTab — write controls follow permissions', () => {
  it('hides every write control from a view-only user', async () => {
    signedInWith([{ module: 'users', action: 'view' }]);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Users' }));
    await waitFor(() => expect(listUsers).toHaveBeenCalled());

    expect(await screen.findByText('colleague@aner.example')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add user' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Edit colleague@aner.example' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument();
  });

  it('offers no Deactivate control on your own row', async () => {
    signedInWith(ALL_USER_PERMISSIONS);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Users' }));
    await waitFor(() => expect(listUsers).toHaveBeenCalled());

    // Exactly one row offers it — the colleague's — which is itself the
    // assertion that the signed-in user's own row does not.
    expect(await screen.findByRole('button', { name: 'Deactivate' })).toBeInTheDocument();
    expect(screen.getByText('(you)')).toBeInTheDocument();
  });

  it('marks an account inactive immediately, before the server replies', async () => {
    signedInWith(ALL_USER_PERMISSIONS);
    vi.mocked(updateUser).mockReturnValue(new Promise(() => {}));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Users' }));
    await waitFor(() => expect(listUsers).toHaveBeenCalled());

    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }));

    expect(await screen.findByText('Inactive')).toBeInTheDocument();
  });

  it('rolls the row back when the server refuses', async () => {
    signedInWith(ALL_USER_PERMISSIONS);
    vi.mocked(updateUser).mockRejectedValue(new Error('Refused'));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Users' }));
    await waitFor(() => expect(listUsers).toHaveBeenCalled());

    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }));

    await waitFor(() =>
      expect(screen.queryByText('Inactive')).not.toBeInTheDocument(),
    );
    expect(await screen.findByRole('button', { name: 'Deactivate' })).toBeInTheDocument();
  });

  it('never offers a role or permission-role picker for your own account', async () => {
    signedInWith(ALL_USER_PERMISSIONS);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Users' }));
    await waitFor(() => expect(listUsers).toHaveBeenCalled());

    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit me@aner.example' }),
    );

    expect(await screen.findByLabelText('Role')).toBeDisabled();
    expect(screen.getByLabelText('Permission role')).toBeDisabled();
    expect(screen.getByText(/cannot change your own role/i)).toBeInTheDocument();
  });
});

describe('RolesTab', () => {
  beforeEach(() => signedInWith(ALL_ROLE_PERMISSIONS));

  it('lists roles, marks built-ins, and offers delete only for custom ones', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Roles' }));
    await waitFor(() => expect(listRoles).toHaveBeenCalled());

    expect(await screen.findByText('Operations')).toBeInTheDocument();
    expect(screen.getByText('Credit reviewer')).toBeInTheDocument();
    expect(screen.getByText('Built-in')).toBeInTheDocument();

    // The built-in role cannot be deleted server-side, so no control exists.
    expect(
      screen.queryByRole('button', { name: 'Delete Operations' }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Delete Credit reviewer' }),
    ).toBeInTheDocument();
  });

  it('hides create, edit and delete controls without those permissions', async () => {
    signedInWith([{ module: 'roles', action: 'view' }]);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Roles' }));
    await waitFor(() => expect(listRoles).toHaveBeenCalled());

    expect(await screen.findByText('Operations')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New role' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Edit Operations' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Delete Credit reviewer' }),
    ).not.toBeInTheDocument();
  });

  it('says which permissions are not enforced yet, instead of implying they work', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Roles' }));
    await waitFor(() => expect(listRoles).toHaveBeenCalled());

    fireEvent.click(await screen.findByRole('button', { name: 'Edit Operations' }));
    await waitFor(() => expect(getPermissionCatalog).toHaveBeenCalled());

    // The catalogue marks `exporters` unenforced and `users` enforced; only the
    // unenforced one carries the warning.
    expect(await screen.findByText('Companies')).toBeInTheDocument();
    expect(screen.getAllByText('Not enforced yet')).toHaveLength(1);
  });
});
