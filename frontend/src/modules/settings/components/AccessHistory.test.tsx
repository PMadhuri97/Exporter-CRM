import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { getAccessHistory } from '../api';

import { AccessHistory } from './AccessHistory';

vi.mock('../api', () => ({ getAccessHistory: vi.fn() }));

function renderHistory(kind: 'users' | 'roles') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccessHistory kind={kind} id="subject-1" />
    </QueryClientProvider>,
  );
}

describe('AccessHistory — who changed whose access', () => {
  it('says what changed on an account, by whom', async () => {
    vi.mocked(getAccessHistory).mockResolvedValue({
      total: 2,
      entries: [
        {
          id: 'e2',
          occurred_at: '2026-10-08T08:35:00Z',
          event_type: 'access.user_updated',
          actor_id: 'a1',
          actor_name: 'Admin A',
          changes: [
            { field: 'role', from_value: 'OPERATIONS', to_value: 'COMPLIANCE', added: [], removed: [] },
            { field: 'is_active', from_value: true, to_value: false, added: [], removed: [] },
          ],
        },
        {
          id: 'e1',
          occurred_at: '2026-10-07T08:35:00Z',
          event_type: 'access.user_password_reset',
          actor_id: 'a1',
          actor_name: 'Admin A',
          changes: [{ field: 'password', from_value: null, to_value: 'reset', added: [], removed: [] }],
        },
      ],
    });
    renderHistory('users');
    const entries = await screen.findAllByTestId('access-history-entry');
    expect(entries[0]).toHaveTextContent('Account changed · Admin A');
    expect(entries[0]).toHaveTextContent('Role: RM (Relationship Manager) → Compliance');
    expect(entries[0]).toHaveTextContent('Active: Yes → No');
    expect(entries[1]).toHaveTextContent('Password reset');
    expect(getAccessHistory).toHaveBeenCalledWith('users', 'subject-1');
  });

  it('lists a role’s permissions as added and removed', async () => {
    vi.mocked(getAccessHistory).mockResolvedValue({
      total: 1,
      entries: [
        {
          id: 'e1',
          occurred_at: '2026-10-08T08:35:00Z',
          event_type: 'access.role_updated',
          actor_id: 'a1',
          actor_name: 'Admin A',
          changes: [
            { field: 'permissions', from_value: null, to_value: null, added: ['deals:view'], removed: ['documents:view'] },
          ],
        },
      ],
    });
    renderHistory('roles');
    expect(await screen.findByText('Permissions: + deals:view, − documents:view')).toBeInTheDocument();
  });

  it('says so when nothing has been recorded', async () => {
    vi.mocked(getAccessHistory).mockResolvedValue({ total: 0, entries: [] });
    renderHistory('roles');
    expect(await screen.findByText('No changes recorded yet.')).toBeInTheDocument();
  });
});
