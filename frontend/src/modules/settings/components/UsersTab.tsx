import { useState } from 'react';
import { toast } from 'sonner';

import { Button, EmptyLine, Input, Segmented, Select, Skeleton, Tag } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { formatDateTime } from '@/lib/format';
import { roleLabel, roleShortLabel, useCurrentUser } from '@/platform/auth';

import { useUpdateUser, useUsers } from '../hooks';
import { ROLE_OPTIONS, ROLE_TAG_TONE } from '../roles';
import type { AdminUser } from '../types';
import { usePermissions } from '../usePermissions';

import { ResetPasswordDialog } from './ResetPasswordDialog';
import { UserFormDialog } from './UserFormDialog';

const PAGE_SIZE = 24;

type StatusFilter = 'all' | 'active' | 'inactive';
type RoleLens = AdminUser['role'] | 'all';

const ROLE_LENS = [
  { value: 'all' as RoleLens, label: 'All' },
  ...ROLE_OPTIONS.map((option) => ({ value: option as RoleLens, label: roleShortLabel(option) })),
];

/** The app's one date-time format (`@/lib/format`); an account never signed in says so. */
function formatWhen(value: string | null): string {
  return value === null ? 'Never signed in' : `Last signed in ${formatDateTime(value)}`;
}

/** Up to two letters for the person's mark — from the name, else the address. */
function initials(user: AdminUser): string {
  const source = user.full_name?.trim() || user.email;
  const words = source.split(/[\s@._-]+/).filter(Boolean);
  return ((words[0]?.[0] ?? '') + (words[1]?.[0] ?? '')).toUpperCase() || '?';
}

const ICON_BUTTON =
  'rounded-md p-1.5 text-ink-3 transition-colors duration-quick hover:bg-sunken hover:text-ink';

/**
 * Users (frontend-plan §8.9): the accounts that can sign in, as people tiles — a
 * search, a role lens and a status filter above them. Write controls follow the
 * server's permissions, so a role granted only `users:view` sees the people without
 * edit affordances it would get a 403 from.
 */
export function UsersTab() {
  const currentUser = useCurrentUser();
  const { can } = usePermissions();
  const canCreate = can('users', 'create');
  const canEdit = can('users', 'edit');
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [role, setRole] = useState<RoleLens>('all');
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
      toast.error(caught instanceof Error ? caught.message : 'Could not update account');
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setQuery(searchInput.trim());
            setPage(0);
          }}
          className="flex min-w-0 flex-1 flex-wrap items-center gap-2"
        >
          <Input
            type="search"
            data-page-search
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search name or email…"
            aria-label="Search users"
            className="w-full sm:w-64"
          />
          <Select
            value={status}
            aria-label="Filter by status"
            onChange={(event) => {
              setStatus(event.target.value as StatusFilter);
              setPage(0);
            }}
            className="w-auto"
          >
            <option value="all">Active and inactive</option>
            <option value="active">Active only</option>
            <option value="inactive">Inactive only</option>
          </Select>
          <Button type="submit" variant="subtle">
            Search
          </Button>
        </form>
        {canCreate && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Icon.addUser size={15} aria-hidden /> Add user
          </Button>
        )}
      </div>

      <Segmented
        label="Filter by role"
        size="sm"
        value={role}
        onValueChange={(next) => {
          setRole(next);
          setPage(0);
        }}
        options={ROLE_LENS}
      />

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-36 rounded" />
          ))}
        </div>
      ) : isError ? (
        <p role="alert" className="text-body text-negative">
          {error instanceof Error ? error.message : 'Could not load users.'}
        </p>
      ) : users.length === 0 ? (
        <EmptyLine>
          No users match this filter.
          {canCreate && (
            <>
              {' '}
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="font-semibold text-accent underline-offset-2 hover:underline"
              >
                Add a user
              </button>
            </>
          )}
        </EmptyLine>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Users">
          {users.map((user) => {
            const isSelf = user.id === currentUser.id;
            return (
              <li
                key={user.id}
                className={cn(
                  'flex min-w-0 flex-col gap-3 rounded border bg-surface p-4',
                  user.is_active ? 'border-line' : 'border-dashed border-line-strong',
                )}
              >
                <div className="flex items-start gap-3">
                  <span
                    aria-hidden
                    className={cn(
                      'grid h-9 w-9 shrink-0 place-items-center rounded-full text-secondary font-semibold',
                      user.is_active ? 'bg-accent-solid text-white' : 'bg-sunken text-ink-3',
                    )}
                  >
                    {initials(user)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-body font-medium text-ink">
                      {user.full_name ?? '—'}
                      {isSelf && (
                        <span className="ml-1.5 text-caption font-normal text-ink-3">(you)</span>
                      )}
                    </p>
                    <p className="truncate text-caption text-ink-2">{user.email}</p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Tag tone={ROLE_TAG_TONE[user.role]} title={roleLabel(user.role)}>
                    {roleShortLabel(user.role)}
                  </Tag>
                  <Tag tone={user.is_active ? 'positive' : 'idle'} dot>
                    {user.is_active ? 'Active' : 'Inactive'}
                  </Tag>
                </div>
                <p className="text-caption tabular-nums text-ink-3">{formatWhen(user.last_login_at)}</p>
                {canEdit && (
                  <div className="mt-auto flex items-center gap-1 border-t border-line pt-3">
                    <button
                      type="button"
                      onClick={() => setEditing(user)}
                      aria-label={`Edit ${user.email}`}
                      className={ICON_BUTTON}
                    >
                      <Icon.edit size={15} aria-hidden />
                    </button>
                    <button
                      type="button"
                      onClick={() => setResetting(user)}
                      aria-label={`Reset password for ${user.email}`}
                      className={ICON_BUTTON}
                    >
                      <Icon.key size={15} aria-hidden />
                    </button>
                    {/* Deactivating yourself is refused by the server (409), so it is
                        not offered here at all. */}
                    {!isSelf && (
                      <Button
                        size="sm"
                        variant={user.is_active ? 'subtle' : 'secondary'}
                        className="ml-auto"
                        onClick={() => void toggleActive(user)}
                      >
                        {user.is_active ? 'Deactivate' : 'Reactivate'}
                      </Button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {total > 0 && (
        <div className="flex items-center justify-between text-caption text-ink-2">
          <p className="tabular-nums">
            Showing {showingFrom}–{showingTo} of {total}
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="subtle"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="subtle"
              disabled={showingTo >= total}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {creating && <UserFormDialog onClose={() => setCreating(false)} />}
      {editing !== null && <UserFormDialog user={editing} onClose={() => setEditing(null)} />}
      {resetting !== null && (
        <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
      )}
    </div>
  );
}
