import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  changeOwnPassword,
  createRole,
  createUser,
  deleteRole,
  getAccessHistory,
  getPermissionCatalog,
  listRoles,
  listOwnSessions,
  listUsers,
  resetUserPassword,
  revokeOwnSession,
  updateOwnProfile,
  updateRole,
  updateUser,
} from '../api';
import type {
  AdminUser,
  ChangePasswordRequest,
  CreateRoleRequest,
  CreateUserRequest,
  UpdateMeRequest,
  UpdateRoleRequest,
  UpdateUserRequest,
  UserList,
  UserSearchParams,
} from '../types';

export function useUsers(params: UserSearchParams) {
  return useQuery({
    queryKey: ['settings', 'users', params],
    queryFn: () => listUsers(params),
  });
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateUserRequest) => createUser(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'users'] });
    },
  });
}

/**
 * Optimistic update with rollback, for the one action an administrator takes
 * repeatedly while scanning the list: the activate/deactivate toggle. A row
 * that waits for a round trip before changing makes bulk work feel broken, so
 * the cache is patched immediately and restored from the snapshot if the
 * request fails — the pattern the reference implementation in
 * `settings/components/user-management-tab.tsx` used, kept because it is the
 * right one, not because it was there.
 *
 * Every other mutation here invalidates instead: they open a dialog and wait,
 * so there is nothing to hide.
 */
export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, body }: { userId: string; body: UpdateUserRequest }) =>
      updateUser(userId, body),
    onMutate: async ({ userId, body }) => {
      await queryClient.cancelQueries({ queryKey: ['settings', 'users'] });
      const snapshot = queryClient.getQueriesData<UserList>({
        queryKey: ['settings', 'users'],
      });
      queryClient.setQueriesData<UserList>(
        { queryKey: ['settings', 'users'] },
        (current) =>
          current === undefined
            ? current
            : {
                ...current,
                users: current.users.map((user) =>
                  user.id === userId ? { ...user, ...body } : user,
                ) as AdminUser[],
              },
      );
      return { snapshot };
    },
    onError: (_error, _variables, context) => {
      // Put every cached page back exactly as it was — a partial restore would
      // leave the table showing a state the server never agreed to.
      for (const [queryKey, data] of context?.snapshot ?? []) {
        queryClient.setQueryData(queryKey, data);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'users'] });
      void queryClient.invalidateQueries({ queryKey: ['settings', 'accessHistory'] });
    },
  });
}

export function useResetUserPassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, newPassword }: { userId: string; newPassword: string }) =>
      resetUserPassword(userId, { new_password: newPassword }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'accessHistory'] });
    },
  });
}

export function useUpdateOwnProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: UpdateMeRequest) => updateOwnProfile(body),
    onSuccess: () => {
      // The administrator list shows this user too, if they are looking at it.
      void queryClient.invalidateQueries({ queryKey: ['settings', 'users'] });
    },
  });
}

export function useChangeOwnPassword() {
  return useMutation({
    mutationFn: (body: ChangePasswordRequest) => changeOwnPassword(body),
  });
}

export function useOwnSessions() {
  return useQuery({
    queryKey: ['settings', 'sessions'],
    queryFn: () => listOwnSessions(),
  });
}

export function useRevokeOwnSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => revokeOwnSession(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'sessions'] });
    },
  });
}

// ── Role management ───────────────────────────────────────────────

export function useRoles() {
  return useQuery({
    queryKey: ['settings', 'roles'],
    queryFn: listRoles,
  });
}

export function usePermissionCatalog() {
  return useQuery({
    queryKey: ['settings', 'permissionCatalog'],
    queryFn: getPermissionCatalog,
    // The catalogue is compiled into the backend; it only changes on deploy.
    staleTime: 5 * 60_000,
  });
}

/** Invalidates the caller's own permissions too: editing a role can change
 * what the person doing the editing is allowed to see, and a stale answer there
 * means a screen that disagrees with the server. */
function useRoleMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'roles'] });
      void queryClient.invalidateQueries({
        queryKey: ['settings', 'myPermissions'],
      });
      void queryClient.invalidateQueries({ queryKey: ['settings', 'users'] });
      void queryClient.invalidateQueries({ queryKey: ['settings', 'accessHistory'] });
    },
  });
}

export function useCreateRole() {
  return useRoleMutation((body: CreateRoleRequest) => createRole(body));
}

export function useUpdateRole() {
  return useRoleMutation(
    ({ roleId, body }: { roleId: string; body: UpdateRoleRequest }) =>
      updateRole(roleId, body),
  );
}

export function useDeleteRole() {
  return useRoleMutation((roleId: string) => deleteRole(roleId));
}

/** An account's or a role's change history. Refreshed after every save in the panel. */
export function useAccessHistory(kind: 'users' | 'roles', id: string | undefined) {
  return useQuery({
    queryKey: ['settings', 'accessHistory', kind, id],
    queryFn: () => getAccessHistory(kind, id as string),
    enabled: id !== undefined,
  });
}
