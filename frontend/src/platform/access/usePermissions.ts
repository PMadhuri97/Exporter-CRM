import { useQuery } from '@tanstack/react-query';

import { apiRequest } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

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

/** The permissions a screen reads from the server rather than from the role: the
 * senior-work ones (held through the Sales lead and Compliance lead roles, or any role an
 * administrator grants them to) and saving a copy of a document. */
export type AssignmentPermission =
  | 'exporters:assign_rm'
  | 'compliance:assign'
  | 'compliance:approve_high_risk'
  | 'documents:download'
  | 'exporters:approve_bank_accounts'
  | 'exporters:assign_collector';

/**
 * Whether the signed-in user holds one of the senior-work permissions, through whatever
 * role grants it. The administrator holds none of them by default: it runs the system
 * and does not assign or approve business work. For showing a lead's views and actions;
 * the server decides again on every request.
 */
export function useHasPermission(permission: AssignmentPermission): boolean {
  const { granted } = usePermissions();
  return granted.has(permission);
}
