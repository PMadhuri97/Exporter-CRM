import { useState } from 'react';
import { toast } from 'sonner';

import { Composer, composerFieldError, Field, Input, Select } from '@/components';
import { roleLabel, useCurrentUser } from '@/platform/auth';

import { useCreateUser, useRoles, useUpdateUser } from '../hooks';
import { assessPassword } from '../passwordStrength';
import { ROLE_DESCRIPTION, ROLE_OPTIONS } from '../roles';
import type { AdminUser } from '../types';

import { PasswordField } from './PasswordField';

interface UserFormDialogProps {
  /** Absent = create a new account; present = edit this one. */
  user?: AdminUser;
  onClose: () => void;
}

const FIELDS = ['email', 'full_name', 'role', 'role_id', 'password'] as const;

/** Add a user, or edit one — a composer (frontend-plan §6.10), not a box mid-page. */
export function UserFormDialog({ user, onClose }: UserFormDialogProps) {
  const isEdit = user !== undefined;
  const currentUser = useCurrentUser();
  const isSelf = isEdit && user.id === currentUser.id;

  const [email, setEmail] = useState(user?.email ?? '');
  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [role, setRole] = useState<AdminUser['role']>(user?.role ?? 'OPERATIONS');
  const [roleId, setRoleId] = useState<string>(user?.role_id ?? '');
  const [password, setPassword] = useState('');

  // Only assignable roles are offered; the server refuses the rest with a 409,
  // so listing them would be a choice that cannot be saved.
  const rolesQuery = useRoles();
  const assignableRoles = (rolesQuery.data?.roles ?? []).filter(
    (candidate) => candidate.is_assignable,
  );

  const createMutation = useCreateUser();
  const updateMutation = useUpdateUser();
  const pending = createMutation.isPending || updateMutation.isPending;
  const error = isEdit ? updateMutation.error : createMutation.error;

  const passwordOk = assessPassword(password).meetsPolicy;
  const canSubmit = isEdit ? true : email.trim().length > 0 && passwordOk;

  async function handleSubmit() {
    const name = fullName.trim() === '' ? null : fullName.trim();

    try {
      if (isEdit) {
        const nextRoleId = roleId === '' ? null : roleId;
        await updateMutation.mutateAsync({
          userId: user.id,
          // Never send `role` or `role_id` for your own account: the server
          // refuses both with a 409, so offering them would be a button that
          // cannot work. `role_id` is only sent when it actually changed, so an
          // unrelated name edit does not re-assert the assignment.
          body: isSelf
            ? { full_name: name }
            : {
                full_name: name,
                role,
                ...(nextRoleId !== (user.role_id ?? null) ? { role_id: nextRoleId } : {}),
              },
        });
        toast.success('User updated');
      } else {
        await createMutation.mutateAsync({
          email: email.trim(),
          password,
          full_name: name,
          role,
          ...(roleId === '' ? {} : { role_id: roleId }),
        });
        toast.success('User created');
      }
      onClose();
    } catch {
      // The refusal stays in the composer, in the server's words, beside its field
      // when it names one.
    }
  }

  return (
    <Composer
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={isEdit ? 'Edit user' : 'Add user'}
      description={
        isEdit
          ? 'Change the display name and role for this account.'
          : 'Creates a working account with the role you choose.'
      }
      submitLabel={isEdit ? 'Save changes' : 'Create user'}
      pending={pending}
      error={error}
      fields={FIELDS}
      submitDisabled={!canSubmit}
      onSubmit={() => void handleSubmit()}
    >
      <Field
        label="Email"
        htmlFor="user-email"
        error={composerFieldError(error, 'email')}
        hint={
          isEdit
            ? 'Email cannot be changed — no address-confirmation flow exists yet, so a silent change would lock the account out.'
            : undefined
        }
      >
        <Input
          id="user-email"
          type="email"
          value={email}
          required
          disabled={isEdit}
          onChange={(event) => setEmail(event.target.value)}
        />
      </Field>

      <Field label="Full name" htmlFor="user-name" error={composerFieldError(error, 'full_name')}>
        <Input
          id="user-name"
          type="text"
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
        />
      </Field>

      <Field
        label="Role"
        htmlFor="user-role"
        error={composerFieldError(error, 'role')}
        hint={
          isSelf
            ? 'You cannot change your own role — ask another administrator.'
            : ROLE_DESCRIPTION[role]
        }
      >
        <Select
          id="user-role"
          value={role}
          disabled={isSelf}
          onChange={(event) => setRole(event.target.value as AdminUser['role'])}
        >
          {ROLE_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {roleLabel(option)}
            </option>
          ))}
        </Select>
      </Field>

      <Field
        label="Permission role"
        htmlFor="user-permission-role"
        error={composerFieldError(error, 'role_id')}
        hint={
          isSelf
            ? 'You cannot change your own permission role — ask another administrator.'
            : 'Leave as the default unless this account needs a different permission set. Only the settings screens consult it today; the CRM screens still follow the account role above.'
        }
      >
        <Select
          id="user-permission-role"
          value={roleId}
          disabled={isSelf}
          onChange={(event) => setRoleId(event.target.value)}
        >
          <option value="">Default for {roleLabel(role)}</option>
          {assignableRoles.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.name}
              {candidate.is_builtin ? '' : ' (custom)'}
            </option>
          ))}
        </Select>
      </Field>

      {!isEdit && (
        <PasswordField
          label="Initial password"
          value={password}
          onChange={setPassword}
          showStrength
          required
        />
      )}
    </Composer>
  );
}
