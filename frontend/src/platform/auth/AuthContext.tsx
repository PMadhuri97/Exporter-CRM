import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import {
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
} from '@/lib/api/authApi';
import {
  IDLE_SIGN_OUT_MESSAGE,
  refreshSession,
  registerRefreshFailureHandler,
} from '@/lib/api/client';
import { queryClient } from '@/lib/queryClient';
import {
  clearActivity,
  hasTimedOut,
  lastActivityAt,
  msUntilIdleTimeout,
  recordActivity,
  recordActivityNow,
  renewalDue,
} from '@/lib/api/sessionActivity';
import {
  REFRESH_TOKEN_STORAGE_KEY,
  clearTokens,
  getAccessToken,
  getRefreshToken,
  isAccessTokenExpiringSoon,
  setTokens,
} from '@/lib/api/tokenStorage';
import type { User } from '@/lib/api/types';

import { AuthContext, type AuthContextValue, type AuthStatus } from './useAuth';

/** The warning shows this long before the inactivity timeout. */
const WARN_BEFORE_MS = 60_000;

/**
 * Someone counts as "here" for the keep-alive below if they used the page this
 * recently. Short, so a session left idle is not renewed on its behalf: the server's
 * own window then runs out at most one timeout after they walked away.
 */
const KEEP_ALIVE_IF_ACTIVE_WITHIN_MS = 2 * 60_000;

/** What counts as using the CRM. Not focus or visibility: a tab brought forward by
 * another window is not someone at the desk. */
const ACTIVITY_EVENTS = ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'wheel'];

export function AuthProvider({ children }: { children: ReactNode }): ReactNode {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [endReason, setEndReason] = useState<string | null>(null);
  const [idleWarningSeconds, setIdleWarningSeconds] = useState<number | null>(null);
  // Read by the activity listener, which must not re-subscribe every second.
  const warningShown = useRef(false);

  const forceLoggedOut = useCallback((reason?: string) => {
    setUser(null);
    setIdleWarningSeconds(null);
    setEndReason(reason ?? null);
    setStatus('unauthenticated');
  }, []);

  // Silent boot-time refresh: a stored refresh token means the user was
  // signed in before this page load, so re-establish the session instead of
  // bouncing straight to the login page — this is the difference between
  // "reload the tab" and "log back in every time." Not once the inactivity timeout has
  // passed: a link opened from an email the next morning must ask for the password.
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
        // It also refuses, and clears the tokens, once the session has timed out.
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
        if (!cancelled) forceLoggedOut(hasTimedOut() ? IDLE_SIGN_OUT_MESSAGE : undefined);
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
    // Before the tokens: signing in is activity, and a tab that saw the new token
    // first must not find the session already timed out.
    recordActivityNow();
    setTokens({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
      expiresInSeconds: tokens.expires_in,
      sessionIdleTimeoutSeconds: tokens.session_idle_timeout,
    });
    const currentUser = await fetchCurrentUser(tokens.access_token);
    // Whatever an earlier sign-in on this tab fetched was fetched with that
    // user's role; the new user starts with nothing cached. Done here, while
    // only the sign-in page is mounted, so nothing refetches against it.
    queryClient.clear();
    setEndReason(null);
    setUser(currentUser);
    setStatus('authenticated');
  }, []);

  const endSession = useCallback(
    async (reason?: string) => {
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
      // Only for a sign-out by hand. A timeout leaves the last activity where it was,
      // so a tab loading afterwards still sees that the session timed out.
      if (reason === undefined) clearActivity();
      forceLoggedOut(reason);
    },
    [forceLoggedOut],
  );

  const logout = useCallback(() => endSession(), [endSession]);

  const staySignedIn = useCallback(() => {
    warningShown.current = false;
    recordActivityNow();
    setIdleWarningSeconds(null);
    // The server's window too, now: it runs from the last renewal, which by the time
    // the warning shows was nearly a whole timeout ago. Left to the keep-alive, the
    // server could end the session minutes after the person chose to stay.
    refreshSession().catch(() => {
      // A refused refresh has already signed this tab out through the handler.
    });
  }, []);

  // While signed in: count real use, and watch the clock. One timer per tab, all
  // reading the same shared last-activity time, so every tab warns and signs out
  // together, and work in one keeps the others open.
  useEffect(() => {
    if (status !== 'authenticated') return;

    // Not while the warning is up: a mouse brushed in passing would dismiss it before it
    // was read. Staying signed in then takes the deliberate "Stay signed in" (or closing
    // the dialog), as in other CRMs.
    const onActivity = () => {
      if (!warningShown.current) recordActivity();
    };
    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, onActivity, { capture: true, passive: true });
    }

    const tick = () => {
      const remaining = msUntilIdleTimeout();
      if (remaining <= 0) {
        // Stopped first: the sign-out request is async, and the next tick must not
        // send a second one while it is out.
        window.clearInterval(timer);
        void endSession(IDLE_SIGN_OUT_MESSAGE);
        return;
      }
      const warning = remaining <= WARN_BEFORE_MS ? Math.ceil(remaining / 1000) : null;
      warningShown.current = warning !== null;
      setIdleWarningSeconds(warning);

      // Someone reading a long page makes no requests, so nothing would renew the
      // session and the server's window would close on them while they work. While
      // they are actually here, renew it every minute or so (`renewalDue`) or as the
      // access token comes due — so the server's window, padded by two minutes, always
      // ends after the countdown on screen, whatever the two lifetimes are.
      const last = lastActivityAt();
      if (
        last !== null &&
        Date.now() - last < KEEP_ALIVE_IF_ACTIVE_WITHIN_MS &&
        (renewalDue() || isAccessTokenExpiringSoon())
      ) {
        refreshSession().catch(() => {
          // A refused refresh has already signed this tab out through the handler.
        });
      }
    };
    // Declared before the first tick runs, which is the only time `tick` reads it.
    const timer = window.setInterval(tick, 1000);
    tick();

    return () => {
      window.clearInterval(timer);
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, onActivity, { capture: true });
      }
    };
  }, [status, endSession]);

  // Signed out in another tab — by hand or by the timeout — is signed out here too,
  // at once, rather than when this tab's access token next comes due.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== REFRESH_TOKEN_STORAGE_KEY || event.newValue !== null) return;
      if (getAccessToken() === null) return;
      clearTokens();
      forceLoggedOut(hasTimedOut() ? IDLE_SIGN_OUT_MESSAGE : undefined);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [forceLoggedOut]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, logout, endReason, idleWarningSeconds, staySignedIn }),
    [status, user, login, logout, endReason, idleWarningSeconds, staySignedIn],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * A fixed, signed-in user for the dev-only style guide, so its
 * role-aware components can be shown as each role sees them. Signing in and out do
 * nothing. Never used by the app's own routes.
 */
export function StaticAuthProvider({ user, children }: { user: User; children: ReactNode }) {
  const value: AuthContextValue = {
    status: 'authenticated',
    user,
    login: async () => undefined,
    logout: async () => undefined,
    endReason: null,
    idleWarningSeconds: null,
    staySignedIn: () => undefined,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
