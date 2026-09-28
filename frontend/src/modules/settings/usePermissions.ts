import { useQuery } from '@tanstack/react-query';

import { getMyPermissions } from './api';
import { permissionKey, type PermissionKey } from './types';

/**
 * What the signed-in user may do, as a set of `module:action` keys.
 *
 * Screens branch on this rather than on `user.role === 'ADMIN'`, which is the
 * whole point of role management: granting a permission in the Roles tab takes
 * effect in the UI without a code change.
 *
 * It lives in this module rather than `platform/auth` because settings is the
 * only consumer today. When a second module needs it — and the modules whose
 * permissions are still marked unenforced eventually will — it should move to
 * `platform/`, next to the auth context, rather than be imported across a
 * module boundary from here.
 *
 * `can` returns false while loading. Callers use it to decide whether to render
 * an action, and briefly hiding a control the user does have is recoverable;
 * briefly showing one they do not is the mistake that matters.
 */
export function usePermissions() {
  const query = useQuery({
    queryKey: ['settings', 'myPermissions'],
    queryFn: getMyPermissions,
    // Permissions change rarely, and a stale grant is a wrong screen, so this
    // is deliberately shorter-lived than the client default.
    staleTime: 15_000,
  });

  const granted = new Set<PermissionKey>(
    (query.data?.permissions ?? []).map(permissionKey),
  );

  return {
    isLoading: query.isLoading,
    roleName: query.data?.role_name ?? null,
    granted,
    can: (module: string, action: string): boolean =>
      granted.has(`${module}:${action}`),
  };
}
