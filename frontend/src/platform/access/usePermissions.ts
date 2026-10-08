import { useQuery } from '@tanstack/react-query';

import { apiRequest } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';
import { useCurrentUser } from '@/platform/auth';

type MyPermissions = components['schemas']['MyPermissionsResponse'];

/** `module:action`, the shape permission checks compare on. */
type PermissionKey = `${string}:${string}`;

/** What the signed-in user may do. Needs no permission of its own, so it is safe to
 * call from anywhere in the shell. */
function getMyPermissions(): Promise<MyPermissions> {
  return apiRequest<MyPermissions>('/auth/me/permissions');
}

/**
 * What the signed-in user may do, as a set of `module:action` keys.
 *
 * Screens branch on this rather than on `user.role === 'ADMIN'`, which is the
 * whole point of role management: granting a permission in the Roles tab takes
 * effect in the UI without a code change. The CRM reads it for the three assignment
 * permissions (`useHasPermission`). Settings has its own reader of the same route
 * (`modules/settings/usePermissions`), sharing this query key, so the two are one
 * request and one cache entry.
 *
 * `can` returns false while loading. Callers use it to decide whether to render
 * an action, and briefly hiding a control the user does have is recoverable;
 * briefly showing one they do not is the mistake that matters.
 */
function usePermissions() {
  const query = useQuery({
    queryKey: ['settings', 'myPermissions'],
    queryFn: getMyPermissions,
    // Permissions change rarely, and a stale grant is a wrong screen, so this
    // is deliberately shorter-lived than the client default.
    staleTime: 15_000,
  });

  const granted = new Set<PermissionKey>(
    (query.data?.permissions ?? []).map((p) => `${p.module}:${p.action}` as PermissionKey),
  );

  return {
    isLoading: query.isLoading,
    roleName: query.data?.role_name ?? null,
    granted,
    can: (module: string, action: string): boolean => granted.has(`${module}:${action}`),
  };
}

/** The permissions the CRM's assignment rules consult — checked by the server as
 * "ADMIN, or the permission", and so here. */
export type AssignmentPermission =
  | 'exporters:assign_rm'
  | 'compliance:assign'
  | 'compliance:approve_high_risk';

/**
 * Whether the signed-in user holds one of the assignment permissions: ADMIN always
 * (the server's rule, so editing ADMIN's grants never locks administrators out), anyone
 * else through a role that grants it. For showing a lead's views and actions; the
 * server decides again on every request.
 */
export function useHasPermission(permission: AssignmentPermission): boolean {
  const { role } = useCurrentUser();
  const { granted } = usePermissions();
  return role === 'ADMIN' || granted.has(permission);
}
