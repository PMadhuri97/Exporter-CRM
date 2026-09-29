import { refresh as refreshTokens } from './authApi';
import { ApiError, parseErrorResponse } from './errors';
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  isAccessTokenExpiringSoon,
  setTokens,
} from './tokenStorage';

// Every other ticket's data fetching goes through `apiRequest` below, not
// raw `fetch` — this is the one place a stale/expiring access token gets
// refreshed before a request goes out, and the one place a 401 that slips
// through anyway gets one retry after a forced refresh. `authApi.ts`
// bypasses this deliberately (see its own module docstring) to avoid this
// file's refresh logic calling itself.
let refreshInFlight: Promise<void> | null = null;

// Set by `AuthProvider` so an unrecoverable refresh failure (refresh token
// itself expired/revoked) can force a logout without this module importing
// the auth context back (which would be a platform -> app dependency
// inversion) — a plain callback registration instead.
let onRefreshFailed: (() => void) | null = null;
export function registerRefreshFailureHandler(handler: () => void): void {
  onRefreshFailed = handler;
}

// The refresh token lives in localStorage, shared by every tab, and the
// backend rotates it on every use: a second exchange of the same token is
// refused. So a refresh holds this lock across tabs, and reads the stored
// token only once it holds it — by then any tab that went first has stored
// its successor. Where the Web Locks API is missing, tabs are not
// coordinated, and the failure handling in `rotate` is what keeps one tab
// from signing out the others.
const REFRESH_LOCK = 'aner-refresh';

async function withRefreshLock(task: () => Promise<void>): Promise<void> {
  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks;
  if (!locks) return task();
  await locks.request(REFRESH_LOCK, task);
}

async function rotate(): Promise<void> {
  let token = getRefreshToken();
  if (token === null) throw new ApiError(401, 'Not signed in.');
  for (let attempt = 0; ; attempt += 1) {
    try {
      const result = await refreshTokens(token);
      setTokens({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        expiresInSeconds: result.expires_in,
      });
      return;
    } catch (error) {
      // Only the server refusing the token ends a session. A network error —
      // above all the aborted fetch of a page being reloaded or closed — says
      // nothing about the token, and clearing it here signed out the next load.
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      const stored = getRefreshToken();
      // Another tab stored a newer token while this call was out: retry
      // once with it rather than give up a session that is still alive.
      if (attempt === 0 && stored !== null && stored !== token) {
        token = stored;
        continue;
      }
      // End the session only if the token that failed is still the stored
      // one. Clearing a newer token would sign out the tab that stored it.
      if (stored === null || stored === token) {
        clearTokens();
        onRefreshFailed?.();
      }
      throw error;
    }
  }
}

/**
 * Exchange the stored refresh token for a new pair — the one refresh
 * function for the whole app (the page load's, and an expiring token's).
 *
 * Single-flight within the tab: callers that arrive while a refresh is out
 * (concurrent requests, React StrictMode running the boot effect twice)
 * share its result instead of spending the same token twice. Across tabs,
 * the lock above serialises them. Rejects when the session cannot be
 * renewed; the tokens are cleared then only if they were this call's.
 */
export function refreshSession(): Promise<void> {
  refreshInFlight ??= withRefreshLock(rotate).finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function ensureFreshAccessToken(): Promise<string | null> {
  if (getRefreshToken() === null) return getAccessToken();
  if (!isAccessTokenExpiringSoon()) return getAccessToken();
  await refreshSession();
  return getAccessToken();
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  /**
   * How to read the response body. Defaults to the content-type sniffing below:
   * JSON when the server says JSON, text otherwise.
   *
   * `'blob'` exists for binary downloads — a PDF read as text is corrupted — and
   * is opt-in so nothing else changes. Added for the document download
   * (`modules/onboarding/api/documents.ts`), which has to fetch content with the
   * access token rather than let the browser open a URL that carries none.
   * **Owner: Developer 1** (architecture §8.1) — additive, no existing caller
   * affected.
   */
  parseAs?: 'blob';
  body?: unknown;
}

export async function apiRequest<TResult>(
  path: string,
  options: RequestOptions = {},
): Promise<TResult> {
  const accessToken = await ensureFreshAccessToken();

  // A `FormData` body (a file upload) goes as it is: the browser sets the
  // multipart `Content-Type` with its boundary. Every other body is JSON.
  const isForm = options.body instanceof FormData;
  const doFetch = (token: string | null) =>
    fetch(`/api/v1${path}`, {
      ...options,
      headers: {
        ...(options.body !== undefined && !isForm
          ? { 'Content-Type': 'application/json' }
          : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
      body:
        options.body === undefined
          ? undefined
          : isForm
            ? (options.body as FormData)
            : JSON.stringify(options.body),
    });

  let response = await doFetch(accessToken);

  // A proactive refresh above should make this rare, but a token can still
  // expire mid-flight (slow request, clock skew) — one retry after a forced
  // refresh, never a loop.
  if (response.status === 401 && getRefreshToken() !== null) {
    try {
      const freshToken = await ensureFreshAccessToken();
      response = await doFetch(freshToken);
    } catch {
      throw new ApiError(401, 'Session expired — please sign in again.');
    }
  }

  if (!response.ok) throw await parseErrorResponse(response);
  if (response.status === 204) return undefined as TResult;
  if (options.parseAs === 'blob') return (await response.blob()) as TResult;
  // A non-JSON response (a CSV template, say) comes back as text.
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('json')) return (await response.text()) as TResult;
  return (await response.json()) as TResult;
}
