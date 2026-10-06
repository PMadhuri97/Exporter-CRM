import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import {
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
} from '@/lib/api/authApi';
import { refreshSession, registerRefreshFailureHandler } from '@/lib/api/client';
import { queryClient } from '@/lib/queryClient';
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from '@/lib/api/tokenStorage';
import type { User } from '@/lib/api/types';

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }): ReactNode {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<User | null>(null);

  const forceLoggedOut = useCallback(() => {
    setUser(null);
    setStatus('unauthenticated');
  }, []);

  // Silent boot-time refresh: a stored refresh token means the user was
  // signed in before this page load, so re-establish the session instead of
  // bouncing straight to the login page — this is the difference between
  // "reload the tab" and "log back in every time."
  useEffect(() => {
    const storedRefreshToken = getRefreshToken();
    if (storedRefreshToken === null) {
      setStatus('unauthenticated');
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        // `client.ts`'s own refresh-on-expiry logic only fires once a
        // request is made; on boot there is no request yet, so refresh
        // explicitly here before asking for the current user. Through the
        // same `refreshSession` as every other refresh, so StrictMode's
        // second run of this effect, a request racing it, and other tabs
        // booting at the same moment never spend one refresh token twice.
        await refreshSession();
        const accessToken = getAccessToken();
        if (accessToken === null) throw new Error('No access token after refresh');
        const currentUser = await fetchCurrentUser(accessToken);
        if (!cancelled) {
          setUser(currentUser);
          setStatus('authenticated');
        }
      } catch {
        // A failed refresh has already cleared the tokens — if they were
        // still the ones that failed, and not a newer pair another tab
        // stored meanwhile.
        if (!cancelled) forceLoggedOut();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [forceLoggedOut]);

  // A refresh that fails *during* the session (revoked/expired refresh
  // token, not just at boot) reaches here via the plain callback registered
  // in `client.ts` — see that module's docstring for why it's a callback
  // rather than an import back into this context. Only one `AuthProvider`
  // ever mounts, so last-registration-wins is fine.
  useEffect(() => {
    registerRefreshFailureHandler(forceLoggedOut);
    return () => registerRefreshFailureHandler(() => {});
  }, [forceLoggedOut]);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await loginRequest({ email, password });
    setTokens({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
      expiresInSeconds: tokens.expires_in,
    });
    const currentUser = await fetchCurrentUser(tokens.access_token);
    // Whatever an earlier sign-in on this tab fetched was fetched with that
    // user's role; the new user starts with nothing cached. Done here, while
    // only the sign-in page is mounted, so nothing refetches against it.
    queryClient.clear();
    setUser(currentUser);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async () => {
    const accessToken = getAccessToken();
    const refreshToken = getRefreshToken();
    if (accessToken && refreshToken) {
      try {
        await logoutRequest(accessToken, refreshToken);
      } catch {
        // Best-effort server-side revocation — clear local state regardless,
        // the refresh token is still unusable to this client afterward.
      }
    }
    clearTokens();
    forceLoggedOut();
  }, [forceLoggedOut]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, logout }),
    [status, user, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * A fixed, signed-in user for the dev-only style guide (frontend-plan §12.4), so its
 * role-aware components can be shown as each role sees them. Signing in and out do
 * nothing. Never used by the app's own routes.
 */
export function StaticAuthProvider({ user, children }: { user: User; children: ReactNode }) {
  const value: AuthContextValue = {
    status: 'authenticated',
    user,
    login: async () => undefined,
    logout: async () => undefined,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

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
