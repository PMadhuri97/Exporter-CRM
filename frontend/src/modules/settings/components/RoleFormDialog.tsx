import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Composer, composerFieldError, Field, Input, Skeleton, Tag, Textarea } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { useCreateRole, usePermissionCatalog, useUpdateRole } from '../hooks';
import { permissionKey, type PermissionKey, type Role } from '../types';

interface RoleFormDialogProps {
  /** Absent = create a custom role; present = edit this one. */
  role?: Role;
  onClose: () => void;
}

const FIELDS = ['name', 'slug', 'description', 'permissions'] as const;

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 50);
}

/**
 * Create or edit a role — a composer holding the permission grid (frontend-plan
 * §8.9): a row per module, its actions as switches, and the catalogue's own word on
 * which modules are not enforced yet.
 */
export function RoleFormDialog({ role, onClose }: RoleFormDialogProps) {
  const isEdit = role !== undefined;
  const catalogQuery = usePermissionCatalog();
  const createMutation = useCreateRole();
  const updateMutation = useUpdateRole();
  const pending = createMutation.isPending || updateMutation.isPending;
  const error = isEdit ? updateMutation.error : createMutation.error;

  const [name, setName] = useState(role?.name ?? '');
  const [slug, setSlug] = useState(role?.slug ?? '');
  const [slugEdited, setSlugEdited] = useState(isEdit);
  const [description, setDescription] = useState(role?.description ?? '');
  const [selected, setSelected] = useState<Set<PermissionKey>>(
    () => new Set((role?.permissions ?? []).map(permissionKey)),
  );

  const modules = useMemo(() => catalogQuery.data?.modules ?? [], [catalogQuery.data]);

  function toggle(key: PermissionKey) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleModule(moduleKey: string, actionKeys: string[]) {
    const keys = actionKeys.map((action) => `${moduleKey}:${action}` as PermissionKey);
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

  async function handleSubmit() {
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
    } catch {
      // Shown in the composer, in the server's words.
    }
  }

  return (
    <Composer
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={isEdit ? `Edit ${role.name}` : 'Create role'}
      description={
        isEdit && role.is_builtin
          ? 'A built-in role. Its permissions can be changed; the role itself cannot be deleted.'
          : 'Choose exactly what this role can do.'
      }
      submitLabel={isEdit ? 'Save changes' : 'Create role'}
      pending={pending}
      error={error}
      fields={FIELDS}
      submitDisabled={name.trim().length === 0}
      onSubmit={() => void handleSubmit()}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="role-name" error={composerFieldError(error, 'name')}>
          <Input
            id="role-name"
            type="text"
            value={name}
            required
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Field
          label="Identifier"
          htmlFor="role-slug"
          error={composerFieldError(error, 'slug')}
          hint={
            isEdit
              ? 'Fixed — other systems and tests refer to this.'
              : 'Lowercase, hyphenated. Cannot be changed later.'
          }
        >
          <Input
            id="role-slug"
            type="text"
            className="font-mono"
            value={slugEdited ? slug : slugify(name)}
            disabled={isEdit}
            onChange={(event) => {
              setSlugEdited(true);
              setSlug(event.target.value);
            }}
          />
        </Field>
      </div>

      <Field
        label="Description"
        htmlFor="role-description"
        error={composerFieldError(error, 'description')}
      >
        <Textarea
          id="role-description"
          value={description}
          rows={2}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>

      <fieldset>
        <legend className="mb-2 text-caption font-medium text-ink-2">
          Permissions <span className="tabular-nums text-ink-3">({selected.size} selected)</span>
        </legend>

        {catalogQuery.isLoading && <Skeleton className="h-40" />}

        <div className="divide-y divide-line border-y border-line">
          {modules.map((module) => {
            const actionKeys = module.actions.map((action) => action.key);
            const allOn = actionKeys.every((action) => selected.has(`${module.key}:${action}`));
            return (
              <div key={module.key} className="py-3">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 text-body font-medium text-ink">
                      {module.label}
                      {/* An unenforced module's switches are stored but gate nothing
                          yet — saying so is the difference between a roadmap and a lie. */}
                      {!module.enforced && (
                        <Tag tone="idle" icon={<Icon.info size={11} aria-hidden />}>
                          Not enforced yet
                        </Tag>
                      )}
                    </p>
                    <p className="text-caption text-ink-3">{module.description}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleModule(module.key, actionKeys)}
                    className="shrink-0 text-caption font-medium text-ink underline-offset-[3px] hover:underline"
                  >
                    {allOn ? 'Clear all' : 'Select all'}
                  </button>
                </div>

                <div className="flex flex-wrap gap-1.5">
                  {module.actions.map((action) => {
                    const key = `${module.key}:${action.key}` as PermissionKey;
                    const on = selected.has(key);
                    return (
                      <label
                        key={key}
                        title={action.description}
                        className={cn(
                          'inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 text-secondary transition-colors duration-quick',
                          'has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ink',
                          on
                            ? 'border-ink bg-ink text-paper'
                            : 'border-line-strong bg-surface text-ink-2 hover:text-ink',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => toggle(key)}
                          className="sr-only"
                        />
                        {on ? (
                          <Icon.check size={12} aria-hidden />
                        ) : (
                          <Icon.add size={12} aria-hidden />
                        )}
                        {action.label}
                        <span className="sr-only"> — {action.description}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </fieldset>
    </Composer>
  );
}
