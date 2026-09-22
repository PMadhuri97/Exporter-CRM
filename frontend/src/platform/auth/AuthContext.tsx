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
  refresh as refreshRequest,
} from '@/lib/api/authApi';
import { registerRefreshFailureHandler } from '@/lib/api/client';
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
        // explicitly here before asking for the current user.
        const tokens = await refreshRequest(storedRefreshToken);
        setTokens({
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
          expiresInSeconds: tokens.expires_in,
        });
        const currentUser = await fetchCurrentUser(tokens.access_token);
        if (!cancelled) {
          setUser(currentUser);
          setStatus('authenticated');
        }
      } catch {
        if (!cancelled) {
          clearTokens();
          forceLoggedOut();
        }
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
