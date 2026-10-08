/**
 * Who changed this account or role, and what — the audit trail of access changes,
 * newest first. There is no approval step for these changes; this is their record.
 *
 * One line per change: "Role: RM → Compliance", "Permissions: + deals:view, − documents:view",
 * "Password reset", each event with when and by whom.
 */

import { EmptyLine, Skeleton } from '@/components';
import type { UserRole } from '@/lib/api/types';
import { formatDateTime } from '@/lib/format';
import { roleLabel } from '@/platform/auth';

import { useAccessHistory } from '../hooks';
import type { AccessChange, AccessHistoryEntry } from '../types';

const FIELD_LABEL: Record<string, string> = {
  email: 'Email',
  full_name: 'Name',
  name: 'Name',
  description: 'Description',
  role: 'Role',
  permission_role: 'Permission role',
  is_active: 'Active',
  is_assignable: 'Assignable',
  permissions: 'Permissions',
};

const EVENT_LABEL: Record<string, string> = {
  'access.user_created': 'Account created',
  'access.user_updated': 'Account changed',
  'access.user_password_reset': 'Password reset',
  'access.role_created': 'Role created',
  'access.role_updated': 'Role changed',
  'access.role_deleted': 'Role deleted',
};

function show(field: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (field === 'role') return roleLabel(value as UserRole);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}

function describe(change: AccessChange): string {
  const label = FIELD_LABEL[change.field] ?? change.field;
  if (change.field === 'password') return 'Password reset';
  if (change.field === 'permissions') {
    const parts = [
      ...(change.added ?? []).map((key) => `+ ${key}`),
      ...(change.removed ?? []).map((key) => `− ${key}`),
    ];
    return `${label}: ${parts.join(', ')}`;
  }
  if (change.from_value === null || change.from_value === undefined) {
    return `${label}: ${show(change.field, change.to_value)}`;
  }
  return `${label}: ${show(change.field, change.from_value)} → ${show(change.field, change.to_value)}`;
}

function Entry({ entry }: { entry: AccessHistoryEntry }) {
  return (
    <li className="py-2" data-testid="access-history-entry">
      <p className="text-secondary text-ink">
        <span className="font-semibold">{EVENT_LABEL[entry.event_type] ?? entry.event_type}</span>
        <span className="text-ink-3">
          {' '}
          · {entry.actor_name ?? 'Someone'} · {formatDateTime(entry.occurred_at)}
        </span>
      </p>
      {entry.changes.length > 0 ? (
        <ul className="mt-0.5 space-y-0.5 text-caption text-ink-2">
          {entry.changes.map((change, index) => (
            <li key={`${change.field}-${index}`}>{describe(change)}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-0.5 text-caption text-ink-3">Saved with no changes.</p>
      )}
    </li>
  );
}

export function AccessHistory({ kind, id }: { kind: 'users' | 'roles'; id: string }) {
  const query = useAccessHistory(kind, id);
  return (
    <section aria-label="History" className="border-t border-line pt-3">
      <h3 className="text-body font-semibold text-ink">History</h3>
      {query.isLoading && <Skeleton className="mt-2 h-12" />}
      {query.isError && <p className="mt-2 text-caption text-negative">Couldn't load the history.</p>}
      {query.data &&
        (query.data.entries.length === 0 ? (
          <EmptyLine>No changes recorded yet.</EmptyLine>
        ) : (
          <ul className="divide-y divide-line">
            {query.data.entries.map((entry) => (
              <Entry key={entry.id} entry={entry} />
            ))}
          </ul>
        ))}
    </section>
  );
}
