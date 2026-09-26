import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  changeOwnPassword,
  createUser,
  listOwnSessions,
  listUsers,
  resetUserPassword,
  revokeOwnSession,
  updateOwnProfile,
  updateUser,
} from '../api';
import type {
  AdminUser,
  ChangePasswordRequest,
  CreateUserRequest,
  UpdateMeRequest,
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
    },
  });
}

export function useResetUserPassword() {
  return useMutation({
    mutationFn: ({ userId, newPassword }: { userId: string; newPassword: string }) =>
      resetUserPassword(userId, { new_password: newPassword }),
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
