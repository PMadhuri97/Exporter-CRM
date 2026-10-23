import { fireEvent, render, screen } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearTokens } from '@/lib/api/tokenStorage';
import { queryClient } from '@/lib/queryClient';

import { AuthProvider } from './AuthContext';
import { useAuth } from './useAuth';

const REFRESH_KEY = 'aner.refreshToken';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function Status() {
  const { status, user } = useAuth();
  return <p>{status === 'authenticated' ? `signed in as ${user?.email}` : status}</p>;
}

const fetchMock = vi.fn();

beforeEach(() => {
  localStorage.clear();
  // Signed in and in use a moment ago, unless a test says otherwise: a stored token
  // with no recorded activity is a timed-out session.
  localStorage.setItem('aner.lastActivity', String(Date.now()));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  clearTokens();
});

function refreshCalls(): number {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/auth/refresh')).length;
}

describe('AuthProvider boot', () => {
  it('refreshes once under StrictMode and stays signed in', async () => {
    localStorage.setItem(REFRESH_KEY, 'stored');
    // The server rotates: a second exchange of "stored" would be refused.
    const used = new Set<string>();
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/refresh')) {
        const { refresh_token } = JSON.parse(init?.body as string) as { refresh_token: string };
        if (used.has(refresh_token)) return json({ detail: 'Invalid or revoked' }, 401);
        used.add(refresh_token);
        return json({ access_token: 'access', refresh_token: 'rotated', expires_in: 900 });
      }
      if (url.endsWith('/auth/me')) {
        return json({ id: 'u1', email: 'ops@example.com', role: 'OPERATIONS' });
      }
      return json({ detail: 'not found' }, 404);
    });

    render(
      <StrictMode>
        <AuthProvider>
          <Status />
        </AuthProvider>
      </StrictMode>,
    );

    expect(await screen.findByText('signed in as ops@example.com')).toBeInTheDocument();
    expect(refreshCalls()).toBe(1);
    expect(localStorage.getItem(REFRESH_KEY)).toBe('rotated');
  });

  it('keeps a token another tab stored while its own refresh failed', async () => {
    localStorage.setItem(REFRESH_KEY, 'stale');
    fetchMock.mockImplementation(async () => {
      // Every exchange loses to another tab, which stores a newer token first.
      localStorage.setItem(REFRESH_KEY, `newer-${refreshCalls()}`);
      return json({ detail: 'Invalid or revoked refresh token' }, 401);
    });

    render(
      <AuthProvider>
        <Status />
      </AuthProvider>,
    );

    expect(await screen.findByText('unauthenticated')).toBeInTheDocument();
    // This tab could not sign in, but the other tab's session is left alone.
    expect(localStorage.getItem(REFRESH_KEY)).toMatch(/^newer-/);
  });
});

describe('AuthProvider sign-in', () => {
  it('drops everything the previous user had fetched', async () => {
    queryClient.setQueryData(['companies'], ['fetched by the previous user']);
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/login')) {
        return json({ access_token: 'access', refresh_token: 'refresh', expires_in: 900 });
      }
      if (url.endsWith('/auth/me')) {
        return json({ id: 'u2', email: 'compliance@example.com', role: 'COMPLIANCE' });
      }
      return json({ detail: 'not found' }, 404);
    });

    function SignIn() {
      const { login } = useAuth();
      return (
        <button type="button" onClick={() => void login('compliance@example.com', 'Secret123')}>
          Sign in
        </button>
      );
    }

    render(
      <AuthProvider>
        <Status />
        <SignIn />
      </AuthProvider>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('signed in as compliance@example.com')).toBeInTheDocument();
    expect(queryClient.getQueryData(['companies'])).toBeUndefined();
  });
});

// ── The inactivity timeout ───────────────────────────────────────────────────

const TIMEOUT_S = 30 * 60;

function Session() {
  const { status, endReason, idleWarningSeconds, staySignedIn } = useAuth();
  return (
    <div>
      <p>{status}</p>
      {endReason && <p>reason: {endReason}</p>}
      {idleWarningSeconds !== null && <p>warning {idleWarningSeconds}</p>}
      <button type="button" onClick={staySignedIn}>
        stay
      </button>
    </div>
  );
}

function serveSession(): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith('/auth/refresh')) {
      return json({
        access_token: 'access',
        refresh_token: 'rotated',
        expires_in: 900,
        session_idle_timeout: TIMEOUT_S,
      });
    }
    if (url.endsWith('/auth/me')) return json({ id: 'u1', email: 'ops@example.com', role: 'OPERATIONS' });
    if (url.endsWith('/auth/logout')) return new Response(null, { status: 204 });
    return json({ detail: 'not found' }, 404);
  });
}

function lastUsed(msAgo: number): void {
  localStorage.setItem('aner.lastActivity', String(Date.now() - msAgo));
}

describe('the inactivity timeout', () => {
  it('does not restore a session nobody used within the timeout, and says why', async () => {
    // The emailed link opened the next morning: a token is stored, but nobody has
    // used the CRM in this browser since yesterday.
    localStorage.setItem(REFRESH_KEY, 'stored');
    localStorage.setItem('aner.sessionIdleTimeoutMs', String(TIMEOUT_S * 1000));
    lastUsed(12 * 60 * 60_000);
    serveSession();

    render(
      <AuthProvider>
        <Session />
      </AuthProvider>,
    );

    expect(await screen.findByText('unauthenticated')).toBeInTheDocument();
    expect(screen.getByText(/reason: You were signed out after a period of inactivity/)).toBeInTheDocument();
    expect(refreshCalls()).toBe(0);
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it('warns in the last minute, and "stay signed in" puts the clock back', async () => {
    localStorage.setItem(REFRESH_KEY, 'stored');
    serveSession();
    render(
      <AuthProvider>
        <Session />
      </AuthProvider>,
    );
    expect(await screen.findByText('authenticated')).toBeInTheDocument();

    lastUsed(TIMEOUT_S * 1000 - 30_000);
    expect(await screen.findByText(/warning \d+/)).toBeInTheDocument();

    // A mouse brushed in passing does not dismiss it: staying takes a deliberate click.
    const before = localStorage.getItem('aner.lastActivity');
    fireEvent.mouseMove(window);
    fireEvent.keyDown(window, { key: 'a' });
    fireEvent.scroll(window);
    await new Promise((resolve) => setTimeout(resolve, 1100));
    expect(localStorage.getItem('aner.lastActivity')).toBe(before);
    expect(screen.getByText(/warning \d+/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'stay' }));

    expect(screen.queryByText(/warning \d+/)).not.toBeInTheDocument();
    expect(Date.now() - Number(localStorage.getItem('aner.lastActivity'))).toBeLessThan(1000);
  });

  it('signs out when the timeout passes, revoking the session on the server', async () => {
    localStorage.setItem(REFRESH_KEY, 'stored');
    serveSession();
    render(
      <AuthProvider>
        <Session />
      </AuthProvider>,
    );
    expect(await screen.findByText('authenticated')).toBeInTheDocument();

    lastUsed(TIMEOUT_S * 1000 + 1000);

    expect(await screen.findByText('unauthenticated', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText(/reason: You were signed out after a period of inactivity/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/auth/logout'))).toBe(true);
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it('signs this tab out when another tab signs out', async () => {
    localStorage.setItem(REFRESH_KEY, 'stored');
    serveSession();
    render(
      <AuthProvider>
        <Session />
      </AuthProvider>,
    );
    expect(await screen.findByText('authenticated')).toBeInTheDocument();

    // What another tab's sign-out looks like from here.
    localStorage.removeItem(REFRESH_KEY);
    window.dispatchEvent(new StorageEvent('storage', { key: REFRESH_KEY, newValue: null }));

    expect(await screen.findByText('unauthenticated')).toBeInTheDocument();
  });
});
