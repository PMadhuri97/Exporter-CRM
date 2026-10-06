import { fireEvent, render, screen } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearTokens } from '@/lib/api/tokenStorage';
import { queryClient } from '@/lib/queryClient';

import { AuthProvider, useAuth } from './AuthContext';

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
