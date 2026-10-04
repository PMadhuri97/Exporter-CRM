import { useCurrentUser } from '@/platform/auth';

import { can, type Capability } from './capabilities';

/**
 * Whether the signed-in user holds `requires` (every one of them, for a list).
 *
 * For a single control: a button, a link, a card. A control the role may never use is
 * **absent**, not disabled — disabled means "allowed, but not right now".
 */
export function useCan(requires: Capability | readonly Capability[]): boolean {
  const { role } = useCurrentUser();
  return can(role, requires);
}
