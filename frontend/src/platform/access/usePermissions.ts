import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

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
 * administrator grants them to), saving a copy of a document, reading a background
 * check, and reading a tax identifier in full. */
export type AssignmentPermission =
  | 'exporters:assign_rm'
  | 'compliance:view'
  | 'exporters:view_full_tax_id'
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

/**
 * Whether this viewer may read a tax identifier in full — the eye beside a PAN, GSTIN,
 * IEC, CIN or registration number, and the identifier searches the API only answers
 * for a holder.
 *
 * Asked as a permission, because that is what the server decides it by
 * (`exporters:view_full_tax_id`). It was a role list on this side until the two could
 * disagree, and they did: granting the permission to the relationship manager unmasked
 * the values on the way out while the screen went on covering them with no eye to open
 * — the full value crossing the network and no way to read it.
 *
 * Granting it stays a deliberate act in Settings. Compliance holds it by default; the
 * administrator does not.
 */
export function useCanRevealIdentifiers(): boolean {
  return useHasPermission('exporters:view_full_tax_id');
}

/**
 * The same answer, fixed once the server has given it — for a form that has to keep
 * one answer for its whole life.
 *
 * An edit form reads the permission once, at open: the fields are initialised from it,
 * and were it read live a change from false to true mid-edit would leave the email and
 * phone boxes empty and save that emptiness as a deliberate clear.
 *
 * Freezing the *first* answer has its own fault, which is what this fixes: the
 * permissions arrive from the server, so a form opened before they land freezes
 * `false` and keeps it, showing a masked email to somebody entitled to read it for as
 * long as the form stays open. Here nothing is frozen until the answer is real, so
 * late-loading permissions are waited for rather than guessed at.
 *
 * Returns `false` while the answer is still unknown — masked until told otherwise, in
 * keeping with every other reveal decision. When the permissions are already loaded,
 * the answer is there on the **first** render: settled in an effect instead, every form
 * opened `false` and switched to `true` a render later, initialised its email and phone
 * empty, and saved that emptiness as a clear.
 */
export function useCanRevealIdentifiersOnce(): boolean {
  const { isLoading, granted } = usePermissions();
  const answer = granted.has('exporters:view_full_tax_id');
  const [settled, setSettled] = useState<boolean | null>(() => (isLoading ? null : answer));

  useEffect(() => {
    if (!isLoading && settled === null) setSettled(answer);
  }, [isLoading, settled, answer]);

  return settled ?? false;
}
