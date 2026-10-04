import type { ReactNode } from 'react';

import { NotFound } from '@/components';

import type { Capability } from './capabilities';
import { useCan } from './useCan';

export interface GateProps {
  requires: Capability | readonly Capability[];
  children: ReactNode;
  /**
   * What renders when the role lacks `requires`. The generic `NotFound` unless a
   * caller has a reason — the same component, copy and title as an address that does
   * not exist, so a forbidden URL says nothing about the screen behind it (§4.3).
   */
  fallback?: ReactNode;
}

/**
 * Wraps a route. When the role lacks `requires`, `children` are never rendered — so a
 * `React.lazy` page inside is never downloaded, and its queries never fire.
 */
export function Gate({ requires, children, fallback }: GateProps) {
  const allowed = useCan(requires);
  if (!allowed) return <>{fallback ?? <NotFound />}</>;
  return <>{children}</>;
}
