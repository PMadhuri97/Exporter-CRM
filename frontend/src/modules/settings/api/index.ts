import { apiRequest } from '@/lib/api/client';
import type { User } from '@/lib/api/types';

import type {
  AdminUser,
  ChangePasswordRequest,
  CreateRoleRequest,
  CreateUserRequest,
  MyPermissions,
  PermissionCatalog,
  ResetPasswordRequest,
  Role,
  RoleList,
  Session,
  SessionList,
  UpdateMeRequest,
  UpdateRoleRequest,
  UpdateUserRequest,
  UserList,
  UserSearchParams,
} from '../types';

// Every call goes through `apiRequest`, which owns token refresh and the
// single 401 retry — never raw fetch.

function userQuery(params: UserSearchParams): string {
  const search = new URLSearchParams();
  if (params.q) search.set('q', params.q);
  if (params.role) search.set('role', params.role);
  // `isActive` is deliberately checked against undefined, not falsiness:
  // `false` is a real filter value ("show me deactivated accounts").
  if (params.isActive !== undefined)
    search.set('is_active', String(params.isActive));
  search.set('limit', String(params.limit ?? 50));
  search.set('offset', String(params.offset ?? 0));
  return search.toString();
}

export function listUsers(params: UserSearchParams): Promise<UserList> {
  return apiRequest<UserList>(`/auth/users?${userQuery(params)}`);
}

export function createUser(body: CreateUserRequest): Promise<AdminUser> {
  return apiRequest<AdminUser>('/auth/users', { method: 'POST', body });
}

export function updateUser(
  userId: string,
  body: UpdateUserRequest,
): Promise<AdminUser> {
  return apiRequest<AdminUser>(`/auth/users/${userId}`, {
    method: 'PATCH',
    body,
  });
}

export function resetUserPassword(
  userId: string,
  body: ResetPasswordRequest,
): Promise<void> {
  return apiRequest<void>(`/auth/users/${userId}/password`, {
    method: 'POST',
    body,
  });
}

export function updateOwnProfile(body: UpdateMeRequest): Promise<User> {
  return apiRequest<User>('/auth/me', { method: 'PATCH', body });
}

export function changeOwnPassword(body: ChangePasswordRequest): Promise<void> {
  return apiRequest<void>('/auth/me/password', { method: 'POST', body });
}

export function listOwnSessions(): Promise<SessionList> {
  return apiRequest<SessionList>('/auth/me/sessions');
}

export function revokeOwnSession(sessionId: Session['id']): Promise<void> {
  return apiRequest<void>(`/auth/me/sessions/${sessionId}`, {
    method: 'DELETE',
  });
}

// ── Role management ───────────────────────────────────────────────

export function listRoles(): Promise<RoleList> {
  return apiRequest<RoleList>('/auth/roles');
}

export function getPermissionCatalog(): Promise<PermissionCatalog> {
  return apiRequest<PermissionCatalog>('/auth/roles/catalog');
}

export function createRole(body: CreateRoleRequest): Promise<Role> {
  return apiRequest<Role>('/auth/roles', { method: 'POST', body });
}

export function updateRole(
  roleId: string,
  body: UpdateRoleRequest,
): Promise<Role> {
  return apiRequest<Role>(`/auth/roles/${roleId}`, { method: 'PATCH', body });
}

export function deleteRole(roleId: string): Promise<void> {
  return apiRequest<void>(`/auth/roles/${roleId}`, { method: 'DELETE' });
}

/** What the signed-in user may do. Needs no permission of its own, so it is
 * safe to call from anywhere in the shell. */
export function getMyPermissions(): Promise<MyPermissions> {
  return apiRequest<MyPermissions>('/auth/me/permissions');
}
