/**
 * The auth context and the hooks that read it. Kept apart from `AuthContext.tsx`, whose
 * providers are components, so that file exports only components and React Fast
 * Refresh can reload it in place.
 */

import { createContext, useContext } from 'react';

import type { User } from '@/lib/api/types';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export function useCurrentUser(): User {
  const { user } = useAuth();
  if (user === null) {
    throw new Error(
      'useCurrentUser must only be called where AuthStatus is already "authenticated" (e.g. inside ProtectedRoute)',
    );
  }
  return user;
}
