import { useState } from 'react';
import { toast } from 'sonner';

import { Button, ConfirmDialog, Skeleton, Tag } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { useDeleteRole, useRoles } from '../hooks';
import type { Role } from '../types';
import { usePermissions } from '../usePermissions';

import { RoleFormDialog } from './RoleFormDialog';

function PermissionSummary({ role }: { role: Role }) {
  if (role.permissions.length === 0) {
    return <span className="text-caption text-ink-3">No permissions — reaches nothing</span>;
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
        <Tag key={module} tone="idle">
          {module} <span className="tabular-nums text-ink-3">×{count}</span>
        </Tag>
      ))}
    </div>
  );
}

const ICON_BUTTON =
  'rounded-md p-1.5 text-ink-3 transition-colors duration-quick hover:bg-sunken hover:text-ink';

/**
 * Roles (frontend-plan §8.9): one tile per role — what it reaches, how many hold
 * it — and the permission grid behind Edit. Built-in roles say so and offer no
 * delete; the server refuses it, so no control that always fails is shown.
 */
export function RolesTab() {
  const { can } = usePermissions();
  const { data, isLoading, isError, error } = useRoles();
  const deleteMutation = useDeleteRole();
  const [editing, setEditing] = useState<Role | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Role | null>(null);

  const roles = data?.roles ?? [];

  async function handleDelete(role: Role) {
    try {
      await deleteMutation.mutateAsync(role.id);
      toast.success('Role deleted');
    } catch (caught) {
      // The server refuses a role that is still held, and names the count —
      // surface that message rather than a generic failure.
      toast.error(caught instanceof Error ? caught.message : 'Could not delete role');
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-2xl text-body text-ink-2">
          A role is a set of permissions. Built-in roles can be edited but not deleted;
          custom roles are yours to shape. Permissions marked{' '}
          <span className="font-medium">not enforced yet</span> are saved and will apply
          once those screens move over — they gate nothing today.
        </p>
        {can('roles', 'create') && (
          <Button variant="primary" className="shrink-0" onClick={() => setCreating(true)}>
            <Icon.add size={15} aria-hidden /> New role
          </Button>
        )}
      </div>

      {isLoading && (
        <div className="grid gap-3 md:grid-cols-2" aria-hidden>
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-32 rounded" />
          ))}
        </div>
      )}

      {isError && (
        <p role="alert" className="text-body text-negative">
          {error instanceof Error ? error.message : 'Could not load roles.'}
        </p>
      )}

      <ul className="grid gap-3 md:grid-cols-2" aria-label="Roles">
        {roles.map((role) => (
          <li key={role.id} className="flex min-w-0 flex-col gap-3 rounded border border-line bg-surface p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-heading font-semibold text-ink">{role.name}</p>
                  {role.is_builtin && (
                    <Tag tone="ink" icon={<Icon.shield size={11} aria-hidden />}>
                      Built-in
                    </Tag>
                  )}
                  {!role.is_assignable && <Tag tone="idle">Not assignable</Tag>}
                </div>
                <p className="text-caption text-ink-3">{role.slug}</p>
              </div>
              <span className="shrink-0 text-caption tabular-nums text-ink-2">
                {role.user_count} {role.user_count === 1 ? 'user' : 'users'}
              </span>
            </div>
            {role.description && <p className="text-secondary text-ink-2">{role.description}</p>}
            <PermissionSummary role={role} />
            {(can('roles', 'edit') || (can('roles', 'delete') && !role.is_builtin)) && (
              <div className="mt-auto flex items-center gap-1 border-t border-line pt-3">
                {can('roles', 'edit') && (
                  <button
                    type="button"
                    onClick={() => setEditing(role)}
                    aria-label={`Edit ${role.name}`}
                    className={ICON_BUTTON}
                  >
                    <Icon.edit size={15} aria-hidden />
                  </button>
                )}
                {/* Built-in roles cannot be deleted server-side, so no control is
                    offered for them at all rather than one that always fails. */}
                {can('roles', 'delete') && !role.is_builtin && (
                  <button
                    type="button"
                    onClick={() => setDeleting(role)}
                    aria-label={`Delete ${role.name}`}
                    className={cn(ICON_BUTTON, 'hover:text-negative')}
                  >
                    <Icon.remove size={15} aria-hidden />
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>

      {creating && <RoleFormDialog onClose={() => setCreating(false)} />}
      {editing !== null && <RoleFormDialog role={editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={deleting ? `Delete ${deleting.name}?` : 'Delete role?'}
        description="This cannot be undone. The server refuses a role that anyone still holds."
        confirmLabel="Delete role"
        confirmVariant="destructive"
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (deleting) void handleDelete(deleting);
        }}
      />
    </div>
  );
}
