import { Pencil, Plus, Shield, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { useDeleteRole, useRoles } from '../hooks';
import type { Role } from '../types';
import { usePermissions } from '../usePermissions';

import { RoleFormDialog } from './RoleFormDialog';

function PermissionSummary({ role }: { role: Role }) {
  if (role.permissions.length === 0) {
    return (
      <span className="text-xs text-ink-faint">
        No permissions — reaches nothing
      </span>
    );
  }

  // Grouped by module, because "12 permissions" tells an administrator nothing
  // about what the role can actually reach.
  const byModule = new Map<string, number>();
  for (const permission of role.permissions) {
    byModule.set(permission.module, (byModule.get(permission.module) ?? 0) + 1);
  }

  return (
    <div className="flex flex-wrap gap-1">
      {[...byModule.entries()].map(([module, count]) => (
        <span
          key={module}
          className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs text-ink-muted"
        >
          {module} <span className="tabular-nums text-ink-faint">×{count}</span>
        </span>
      ))}
    </div>
  );
}

export function RolesTab() {
  const { can } = usePermissions();
  const { data, isLoading, isError, error } = useRoles();
  const deleteMutation = useDeleteRole();
  const [editing, setEditing] = useState<Role | null>(null);
  const [creating, setCreating] = useState(false);

  const roles = data?.roles ?? [];

  async function handleDelete(role: Role) {
    if (
      !window.confirm(
        `Delete the role "${role.name}"? This cannot be undone.`,
      )
    ) {
      return;
    }
    try {
      await deleteMutation.mutateAsync(role.id);
      toast.success('Role deleted');
    } catch (caught) {
      // The server refuses a role that is still held, and names the count —
      // surface that message rather than a generic failure.
      toast.error(
        caught instanceof Error ? caught.message : 'Could not delete role',
      );
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-2xl text-sm text-ink-muted">
          A role is a set of permissions. Built-in roles can be edited but not
          deleted; custom roles are yours to shape. Permissions marked{' '}
          <span className="font-medium">not enforced yet</span> are saved and
          will apply once those screens move over — they gate nothing today.
        </p>
        {can('roles', 'create') && (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            <Plus size={15} /> New role
          </button>
        )}
      </div>

      {isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="h-20 animate-pulse rounded-xl bg-surface-sunken"
            />
          ))}
        </div>
      )}

      {isError && (
        <p className="rounded-xl border border-border bg-surface p-6 text-center text-sm text-status-failed">
          {error instanceof Error ? error.message : 'Could not load roles.'}
        </p>
      )}

      <div className="flex flex-col gap-2">
        {roles.map((role) => (
          <div
            key={role.id}
            className="rounded-xl border border-border bg-surface p-4"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="font-medium text-ink">{role.name}</p>
                  {role.is_builtin && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-600">
                      <Shield size={11} /> Built-in
                    </span>
                  )}
                  {!role.is_assignable && (
                    <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs font-medium text-ink-faint">
                      Not assignable
                    </span>
                  )}
                </div>
                <p className="font-mono text-xs text-ink-faint">{role.slug}</p>
                {role.description && (
                  <p className="mt-1 text-sm text-ink-muted">
                    {role.description}
                  </p>
                )}
                <div className="mt-2">
                  <PermissionSummary role={role} />
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <span className="text-xs tabular-nums text-ink-muted">
                  {role.user_count} {role.user_count === 1 ? 'user' : 'users'}
                </span>
                {can('roles', 'edit') && (
                  <button
                    type="button"
                    onClick={() => setEditing(role)}
                    aria-label={`Edit ${role.name}`}
                    className="rounded p-1.5 text-ink-faint transition-colors hover:bg-surface-sunken hover:text-ink"
                  >
                    <Pencil size={14} />
                  </button>
                )}
                {/* Built-in roles cannot be deleted server-side, so no control
                    is offered for them at all rather than one that always fails. */}
                {can('roles', 'delete') && !role.is_builtin && (
                  <button
                    type="button"
                    onClick={() => void handleDelete(role)}
                    aria-label={`Delete ${role.name}`}
                    className="rounded p-1.5 text-ink-faint transition-colors hover:bg-surface-sunken hover:text-status-failed"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {creating && <RoleFormDialog onClose={() => setCreating(false)} />}
      {editing !== null && (
        <RoleFormDialog role={editing} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}
