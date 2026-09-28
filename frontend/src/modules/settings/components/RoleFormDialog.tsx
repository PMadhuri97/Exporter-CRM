import { Info, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { useCreateRole, usePermissionCatalog, useUpdateRole } from '../hooks';
import {
  permissionKey,
  type PermissionKey,
  type Role,
} from '../types';

interface RoleFormDialogProps {
  /** Absent = create a custom role; present = edit this one. */
  role?: Role;
  onClose: () => void;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 50);
}

export function RoleFormDialog({ role, onClose }: RoleFormDialogProps) {
  const isEdit = role !== undefined;
  const catalogQuery = usePermissionCatalog();
  const createMutation = useCreateRole();
  const updateMutation = useUpdateRole();
  const pending = createMutation.isPending || updateMutation.isPending;

  const [name, setName] = useState(role?.name ?? '');
  const [slug, setSlug] = useState(role?.slug ?? '');
  const [slugEdited, setSlugEdited] = useState(isEdit);
  const [description, setDescription] = useState(role?.description ?? '');
  const [selected, setSelected] = useState<Set<PermissionKey>>(
    () => new Set((role?.permissions ?? []).map(permissionKey)),
  );

  const modules = useMemo(
    () => catalogQuery.data?.modules ?? [],
    [catalogQuery.data],
  );

  function toggle(key: PermissionKey) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleModule(moduleKey: string, actionKeys: string[]) {
    const keys = actionKeys.map(
      (action) => `${moduleKey}:${action}` as PermissionKey,
    );
    const allOn = keys.every((key) => selected.has(key));
    setSelected((current) => {
      const next = new Set(current);
      for (const key of keys) {
        if (allOn) next.delete(key);
        else next.add(key);
      }
      return next;
    });
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const permissions = [...selected].map((key) => {
      const [module, action] = key.split(':');
      return { module: module!, action: action! };
    });

    try {
      if (isEdit) {
        await updateMutation.mutateAsync({
          roleId: role.id,
          body: {
            name: name.trim(),
            description: description.trim() === '' ? null : description.trim(),
            permissions,
          },
        });
        toast.success('Role updated');
      } else {
        await createMutation.mutateAsync({
          slug: slugEdited ? slug.trim() : slugify(name),
          name: name.trim(),
          description: description.trim() === '' ? null : description.trim(),
          permissions,
        });
        toast.success('Role created');
      }
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save role');
    }
  }

  const canSubmit = !pending && name.trim().length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/30 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isEdit ? 'Edit role' : 'Create role'}
        className="my-8 w-full max-w-2xl rounded-xl border border-border bg-surface p-5 shadow-lg"
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">
              {isEdit ? `Edit ${role.name}` : 'Create role'}
            </h2>
            <p className="text-xs text-ink-muted">
              {isEdit && role.is_builtin
                ? 'A built-in role. Its permissions can be changed; the role itself cannot be deleted.'
                : 'Choose exactly what this role can do.'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-ink-faint hover:text-ink"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor="role-name"
                className="mb-1 block text-xs font-medium text-ink-muted"
              >
                Name
              </label>
              <input
                id="role-name"
                type="text"
                value={name}
                required
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
              />
            </div>
            <div>
              <label
                htmlFor="role-slug"
                className="mb-1 block text-xs font-medium text-ink-muted"
              >
                Identifier
              </label>
              <input
                id="role-slug"
                type="text"
                value={slugEdited ? slug : slugify(name)}
                disabled={isEdit}
                onChange={(event) => {
                  setSlugEdited(true);
                  setSlug(event.target.value);
                }}
                className="w-full rounded-lg border border-border px-3 py-2 font-mono text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              <p className="mt-1 text-xs text-ink-faint">
                {isEdit
                  ? 'Fixed — other systems and tests refer to this.'
                  : 'Lowercase, hyphenated. Cannot be changed later.'}
              </p>
            </div>
          </div>

          <div>
            <label
              htmlFor="role-description"
              className="mb-1 block text-xs font-medium text-ink-muted"
            >
              Description
            </label>
            <textarea
              id="role-description"
              value={description}
              rows={2}
              onChange={(event) => setDescription(event.target.value)}
              className="w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            />
          </div>

          <fieldset className="mt-1">
            <legend className="mb-2 text-xs font-medium text-ink-muted">
              Permissions ({selected.size} selected)
            </legend>

            {catalogQuery.isLoading && (
              <div className="h-40 animate-pulse rounded-lg bg-surface-sunken" />
            )}

            <div className="flex flex-col gap-3">
              {modules.map((module) => {
                const actionKeys = module.actions.map((action) => action.key);
                const allOn = actionKeys.every((action) =>
                  selected.has(`${module.key}:${action}`),
                );
                return (
                  <div
                    key={module.key}
                    className="rounded-lg border border-border p-3"
                  >
                    <div className="mb-2 flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-medium text-ink">
                          {module.label}
                          {/* An unenforced module's checkboxes are stored but
                              gate nothing yet — saying so is the difference
                              between a roadmap and a lie. */}
                          {!module.enforced && (
                            <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-surface-sunken px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
                              <Info size={10} /> Not enforced yet
                            </span>
                          )}
                        </p>
                        <p className="text-xs text-ink-muted">
                          {module.description}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => toggleModule(module.key, actionKeys)}
                        className="shrink-0 text-xs font-medium text-brand-600 hover:underline"
                      >
                        {allOn ? 'Clear all' : 'Select all'}
                      </button>
                    </div>

                    <div className="grid gap-1.5 sm:grid-cols-2">
                      {module.actions.map((action) => {
                        const key =
                          `${module.key}:${action.key}` as PermissionKey;
                        return (
                          <label
                            key={key}
                            className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 text-sm hover:bg-surface-subtle"
                          >
                            <input
                              type="checkbox"
                              checked={selected.has(key)}
                              onChange={() => toggle(key)}
                              className="mt-0.5 h-3.5 w-3.5 rounded border-border-strong text-brand-600 focus:ring-brand-500"
                            />
                            <span>
                              <span className="text-ink">{action.label}</span>
                              <span className="block text-xs text-ink-faint">
                                {action.description}
                              </span>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </fieldset>

          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-3 py-2 text-sm font-medium text-ink-muted hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {pending ? 'Saving…' : isEdit ? 'Save changes' : 'Create role'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
