import { Navigate, Outlet } from 'react-router-dom';

import { useAuth } from '@/platform/auth';

/** Skeleton, not a spinner — per the design principle of designing every
 * async state on purpose rather than defaulting to a bare loading indicator. */
function AuthCheckingSkeleton() {
  return (
    <div className="flex h-screen items-center justify-center bg-paper">
      <div className="h-10 w-10 animate-pulse rounded bg-line" />
    </div>
  );
}

export function ProtectedRoute() {
  const { status } = useAuth();

  if (status === 'loading') return <AuthCheckingSkeleton />;

  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
