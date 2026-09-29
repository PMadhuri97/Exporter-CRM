import { KeyRound, Pencil, UserPlus } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { formatDateTime } from '@/lib/format';
import { useCurrentUser } from '@/platform/auth';

import { useUpdateUser, useUsers } from '../hooks';
import { ROLE_CHIP_CLASS, ROLE_OPTIONS } from '../roles';
import type { AdminUser } from '../types';
import { usePermissions } from '../usePermissions';

import { ResetPasswordDialog } from './ResetPasswordDialog';
import { UserFormDialog } from './UserFormDialog';

const PAGE_SIZE = 25;

type StatusFilter = 'all' | 'active' | 'inactive';

/** The app's one date-time format (`@/lib/format`); an account never signed in says so. */
function formatWhen(value: string | null): string {
  return value === null ? 'Never' : formatDateTime(value);
}

function RoleChip({ role }: { role: AdminUser['role'] }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_CHIP_CLASS[role]}`}
    >
      {role}
    </span>
  );
}

function SkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 5 }).map((_, index) => (
        <td key={index} className="px-4 py-3">
          <div className="h-4 w-24 animate-pulse rounded bg-surface-sunken" />
        </td>
      ))}
    </tr>
  );
}

export function UsersTab() {
  const currentUser = useCurrentUser();
  // Write controls follow the server's permissions, so a role granted only
  // users:view sees the list without edit affordances it would get a 403 from.
  const { can } = usePermissions();
  const canCreate = can('users', 'create');
  const canEdit = can('users', 'edit');
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [role, setRole] = useState<AdminUser['role'] | 'all'>('all');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<AdminUser | null>(null);

  const { data, isLoading, isError, error } = useUsers({
    q: query || undefined,
    role: role === 'all' ? undefined : role,
    isActive: status === 'all' ? undefined : status === 'active',
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });
  const updateMutation = useUpdateUser();

  const users = data?.users ?? [];
  const total = data?.total ?? 0;
  const showingFrom = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const showingTo = Math.min((page + 1) * PAGE_SIZE, total);

  async function toggleActive(user: AdminUser) {
    try {
      await updateMutation.mutateAsync({
        userId: user.id,
        body: { is_active: !user.is_active },
      });
      toast.success(user.is_active ? 'Account deactivated' : 'Account reactivated');
    } catch (caught) {
      // The optimistic patch has already been rolled back by the hook; this
      // only needs to explain why.
      toast.error(
        caught instanceof Error ? caught.message : 'Could not update account',
      );
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setQuery(searchInput.trim());
            setPage(0);
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search name or email…"
            aria-label="Search users"
            className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 sm:w-64"
          />
          <select
            value={role}
            aria-label="Filter by role"
            onChange={(event) => {
              setRole(event.target.value as AdminUser['role'] | 'all');
              setPage(0);
            }}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand-500"
          >
            <option value="all">All roles</option>
            {ROLE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          <select
            value={status}
            aria-label="Filter by status"
            onChange={(event) => {
              setStatus(event.target.value as StatusFilter);
              setPage(0);
            }}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand-500"
          >
            <option value="all">Active and inactive</option>
            <option value="active">Active only</option>
            <option value="inactive">Inactive only</option>
          </select>
          <button
            type="submit"
            className="rounded-lg border border-border px-3 py-2 text-sm font-medium text-ink-muted hover:text-ink"
          >
            Search
          </button>
        </form>

        {canCreate && (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            <UserPlus size={15} /> Add user
          </button>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-surface-subtle text-xs uppercase tracking-wide text-ink-faint">
            <tr>
              <th className="px-4 py-2.5 font-medium">User</th>
              <th className="px-4 py-2.5 font-medium">Role</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Last sign-in</th>
              <th className="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isLoading &&
              Array.from({ length: 4 }).map((_, index) => <SkeletonRow key={index} />)}

            {isError && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-status-failed">
                  {error instanceof Error
                    ? error.message
                    : 'Could not load users.'}
                </td>
              </tr>
            )}

            {!isLoading && !isError && users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center">
                  <p className="text-sm text-ink-muted">No users match this filter.</p>
                  {canCreate && (
                    <button
                      type="button"
                      onClick={() => setCreating(true)}
                      className="mt-2 text-sm font-medium text-brand-600 hover:underline"
                    >
                      Add a user
                    </button>
                  )}
                </td>
              </tr>
            )}

            {users.map((user) => {
              const isSelf = user.id === currentUser.id;
              return (
                <tr key={user.id} className="hover:bg-surface-subtle">
                  <td className="px-4 py-3">
                    <p className="font-medium text-ink">
                      {user.full_name ?? '—'}
                      {isSelf && (
                        <span className="ml-1.5 text-xs font-normal text-ink-faint">
                          (you)
                        </span>
                      )}
                    </p>
                    <p className="font-mono text-xs text-ink-muted">{user.email}</p>
                  </td>
                  <td className="px-4 py-3">
                    <RoleChip role={user.role} />
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                        user.is_active ? 'text-status-passed' : 'text-ink-faint'
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          user.is_active ? 'bg-status-passed' : 'bg-ink-faint'
                        }`}
                      />
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs tabular-nums text-ink-muted">
                    {formatWhen(user.last_login_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      {canEdit && (
                      <button
                        type="button"
                        onClick={() => setEditing(user)}
                        aria-label={`Edit ${user.email}`}
                        className="rounded p-1.5 text-ink-faint transition-colors hover:bg-surface-sunken hover:text-ink"
                      >
                        <Pencil size={14} />
                      </button>
                      )}
                      {canEdit && (
                      <button
                        type="button"
                        onClick={() => setResetting(user)}
                        aria-label={`Reset password for ${user.email}`}
                        className="rounded p-1.5 text-ink-faint transition-colors hover:bg-surface-sunken hover:text-ink"
                      >
                        <KeyRound size={14} />
                      </button>
                      )}
                      {/* Deactivating yourself is refused by the server (409),
                          so it is not offered here at all. */}
                      {canEdit && !isSelf && (
                        <button
                          type="button"
                          onClick={() => void toggleActive(user)}
                          className="ml-1 rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
                        >
                          {user.is_active ? 'Deactivate' : 'Reactivate'}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <div className="mt-3 flex items-center justify-between text-xs text-ink-muted">
          <p>
            Showing {showingFrom}–{showingTo} of {total}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
              className="rounded-lg border border-border px-2.5 py-1 font-medium transition-colors hover:text-ink disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={showingTo >= total}
              onClick={() => setPage((current) => current + 1)}
              className="rounded-lg border border-border px-2.5 py-1 font-medium transition-colors hover:text-ink disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {creating && <UserFormDialog onClose={() => setCreating(false)} />}
      {editing !== null && (
        <UserFormDialog user={editing} onClose={() => setEditing(null)} />
      )}
      {resetting !== null && (
        <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
      )}
    </div>
  );
}
