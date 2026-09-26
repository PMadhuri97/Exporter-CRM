import type { components } from '@/lib/api/schema';

// Thin aliases onto the generated OpenAPI schema, the same discipline as
// `src/lib/api/types.ts` — never a hand-written copy of a backend shape. If
// the backend reshapes one of these, `pnpm run generate:api` regenerates
// `schema.ts` and every use site here becomes a compile error rather than a
// silent runtime mismatch.
export type AdminUser = components['schemas']['AdminUserResponse'];
export type UserList = components['schemas']['UserListResponse'];
export type CreateUserRequest = components['schemas']['AdminCreateUserRequest'];
export type UpdateUserRequest = components['schemas']['AdminUpdateUserRequest'];
export type ResetPasswordRequest =
  components['schemas']['AdminResetPasswordRequest'];
export type UpdateMeRequest = components['schemas']['UpdateMeRequest'];
export type ChangePasswordRequest =
  components['schemas']['ChangePasswordRequest'];
export type Session = components['schemas']['SessionResponse'];
export type SessionList = components['schemas']['SessionListResponse'];

export interface UserSearchParams {
  q?: string;
  role?: AdminUser['role'];
  /** Tri-state on purpose: `undefined` means "both", matching the backend's
   * optional filter — not a defaulted `true` that would quietly hide
   * deactivated accounts from an administrator looking for them. */
  isActive?: boolean;
  limit?: number;
  offset?: number;
}
