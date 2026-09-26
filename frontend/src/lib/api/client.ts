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

async function ensureFreshAccessToken(): Promise<string | null> {
  const token = getRefreshToken();
  if (token === null) return getAccessToken();

  if (!isAccessTokenExpiringSoon()) return getAccessToken();

  // Single-flight: concurrent requests that all notice an expiring token at
  // once share one refresh call rather than racing the rotation endpoint
  // (the backend revokes the old refresh token on every use — a second,
  // parallel call with the now-stale token would fail).
  refreshInFlight ??= (async () => {
    try {
      const result = await refreshTokens(token);
      setTokens({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        expiresInSeconds: result.expires_in,
      });
    } catch (error) {
      clearTokens();
      onRefreshFailed?.();
      throw error;
    } finally {
      refreshInFlight = null;
    }
  })();

  await refreshInFlight;
  return getAccessToken();
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
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
  // A non-JSON response (a CSV template, say) comes back as text.
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('json')) return (await response.text()) as TResult;
  return (await response.json()) as TResult;
}
