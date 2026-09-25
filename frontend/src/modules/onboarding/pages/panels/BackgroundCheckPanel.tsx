/**
 * The background check — **owner: Developer 4** (architecture §9.4).
 *
 * Verification results, the eight-item screening checklist and the
 * bank-activity summary. The background-check gauge itself
 * (`NOT_STARTED` … `CLEAR` / `FLAGGED` / `ON_HOLD`) is not built yet; when it
 * is, it belongs here.
 *
 * A wrapper rather than a rewrite: `VerificationSection` is a 631-line
 * component of Developer 4's that the page rendered directly. Moving its
 * contents would have been a rewrite, not a split, so this panel owns the
 * placement and the role guard, and Developer 4 keeps editing
 * `components/VerificationSection.tsx` as before.
 *
 * The guard is the one the page applied: DEVELOPER may read the CRM but
 * cannot load verification results — the backend answers those with 403 — so
 * the section is not rendered for it at all rather than rendered broken.
 */

import { VerificationSection } from '../../components';

export function BackgroundCheckPanel({
  customerId,
  isStaff,
}: {
  customerId: string;
  isStaff: boolean;
}) {
  if (!isStaff) return null;
  return <VerificationSection customerId={customerId} />;
}
