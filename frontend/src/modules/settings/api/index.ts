import { apiRequest } from '@/lib/api/client';
import type { User } from '@/lib/api/types';

import type {
  AdminUser,
  ChangePasswordRequest,
  CreateUserRequest,
  ResetPasswordRequest,
  Session,
  SessionList,
  UpdateMeRequest,
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
