import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type ClientModule = typeof import('./client');
type TokenModule = typeof import('./tokenStorage');

const REFRESH_KEY = 'aner.refreshToken';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function tokens(refreshToken: string) {
  return { access_token: `access-for-${refreshToken}`, refresh_token: refreshToken, expires_in: 900 };
}

/** The refresh token a `/auth/refresh` call presented. */
function presented(init: RequestInit): string {
  return (JSON.parse(init.body as string) as { refresh_token: string }).refresh_token;
}

/** Every refresh token presented so far, in order. */
function presentedSoFar(mock: ReturnType<typeof vi.fn>): string[] {
  return mock.mock.calls.map((call) => presented(call[1] as RequestInit));
}

/**
 * A fresh copy of the client and its token store — one browser tab. Two calls give two
 * tabs: separate in-memory access tokens and single-flight, one shared localStorage.
 */
async function openTab(): Promise<{ client: ClientModule; store: TokenModule }> {
  vi.resetModules();
  const client = await import('./client');
  const store = await import('./tokenStorage');
  return { client, store };
}

/** An exclusive lock shared by every "tab" in the test, like `navigator.locks`. */
function installWebLocks(): void {
  let tail: Promise<unknown> = Promise.resolve();
  const locks = {
    request: (_name: string, task: () => Promise<unknown>) => {
      const run = tail.then(() => task());
      tail = run.then(
        () => undefined,
        () => undefined,
      );
      return run;
    },
  };
  Object.defineProperty(navigator, 'locks', { value: locks, configurable: true });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, 'locks');
});

describe('apiRequest body encoding', () => {
  it('encodes a plain-object body exactly once', async () => {
    const { client, store } = await openTab();
    store.setTokens({ accessToken: 'a', refreshToken: 'r', expiresInSeconds: 900 });
    fetchMock.mockResolvedValue(json({ ok: true }));

    await client.apiRequest('/things', { method: 'POST', body: { to_value: 'CLEAR' } });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(typeof init.body).toBe('string');
    const decoded: unknown = JSON.parse(init.body as string);
    // Once, not twice: decoding gives the object back, not another string.
    expect(decoded).toEqual({ to_value: 'CLEAR' });
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });
});

describe('refreshSession', () => {
  it('shares one network call between callers that arrive together', async () => {
    const { client, store } = await openTab();
    localStorage.setItem(REFRESH_KEY, 'r1');
    fetchMock.mockImplementation(async () => json(tokens('r2')));

    await Promise.all([client.refreshSession(), client.refreshSession()]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(store.getRefreshToken()).toBe('r2');
    expect(store.getAccessToken()).toBe('access-for-r2');
  });

  it('serialises tabs through the lock, each presenting the newest stored token', async () => {
    installWebLocks();
    // The server rotates each token once; a second use of any token is refused.
    const used = new Set<string>();
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      const token = presented(init);
      if (used.has(token)) return json({ detail: 'Invalid or revoked refresh token' }, 401);
      used.add(token);
      return json(tokens(`${token}+`));
    });
    localStorage.setItem(REFRESH_KEY, 'r1');
    const tabA = await openTab();
    const tabB = await openTab();
    const signedOut = vi.fn();
    tabA.client.registerRefreshFailureHandler(signedOut);
    tabB.client.registerRefreshFailureHandler(signedOut);

    await Promise.all([tabA.client.refreshSession(), tabB.client.refreshSession()]);

    expect(presentedSoFar(fetchMock)).toEqual(['r1', 'r1+']);
    expect(signedOut).not.toHaveBeenCalled();
    expect(localStorage.getItem(REFRESH_KEY)).toBe('r1++');
    expect(tabA.store.getAccessToken()).not.toBeNull();
    expect(tabB.store.getAccessToken()).not.toBeNull();
  });

  it('retries once with a token another tab stored while its own call failed', async () => {
    const { client, store } = await openTab();
    localStorage.setItem(REFRESH_KEY, 'r1');
    const signedOut = vi.fn();
    client.registerRefreshFailureHandler(signedOut);
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      if (presented(init) === 'r1') {
        // Another tab (no Web Locks here) exchanged r1 first and stored r2.
        localStorage.setItem(REFRESH_KEY, 'r2');
        return json({ detail: 'Invalid or revoked refresh token' }, 401);
      }
      return json(tokens('r3'));
    });

    await client.refreshSession();

    expect(presentedSoFar(fetchMock)).toEqual(['r1', 'r2']);
    expect(signedOut).not.toHaveBeenCalled();
    expect(store.getRefreshToken()).toBe('r3');
  });

  it('does not clear a token another tab stored after this one failed', async () => {
    const { client } = await openTab();
    localStorage.setItem(REFRESH_KEY, 'r1');
    const signedOut = vi.fn();
    client.registerRefreshFailureHandler(signedOut);
    let newest = 1;
    fetchMock.mockImplementation(async () => {
      // Every call loses the race: by the time it is refused, a newer token is stored.
      newest += 1;
      localStorage.setItem(REFRESH_KEY, `r${newest}`);
      return json({ detail: 'Invalid or revoked refresh token' }, 401);
    });

    await expect(client.refreshSession()).rejects.toThrow();

    expect(fetchMock).toHaveBeenCalledTimes(2); // the call, and one retry
    expect(localStorage.getItem(REFRESH_KEY)).toBe('r3');
    expect(signedOut).not.toHaveBeenCalled();
  });

  it('keeps the session when the refresh never got an answer (a reload aborted it)', async () => {
    const { client, store } = await openTab();
    localStorage.setItem(REFRESH_KEY, 'r1');
    const signedOut = vi.fn();
    client.registerRefreshFailureHandler(signedOut);
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(client.refreshSession()).rejects.toThrow('Failed to fetch');

    // Nothing says r1 was refused, so the next page load may still use it.
    expect(store.getRefreshToken()).toBe('r1');
    expect(signedOut).not.toHaveBeenCalled();
  });

  it('ends the session when the token that failed is still the stored one', async () => {
    const { client, store } = await openTab();
    localStorage.setItem(REFRESH_KEY, 'r1');
    const signedOut = vi.fn();
    client.registerRefreshFailureHandler(signedOut);
    fetchMock.mockResolvedValue(json({ detail: 'Refresh token has expired' }, 401));

    await expect(client.refreshSession()).rejects.toThrow();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(store.getRefreshToken()).toBeNull();
    expect(signedOut).toHaveBeenCalledTimes(1);
  });
});
