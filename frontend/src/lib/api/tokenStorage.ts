// The one place tokens live. `accessToken` is memory-only (never touches
// disk, minimizing XSS blast radius); `refreshToken` persists to
// localStorage so a page reload doesn't force a re-login — the accepted
// trade-off for a browser SPA with no backend-for-frontend session layer.
// Read outside React (by `apiClient.ts`, before any component has mounted)
// so this is a plain module-level store with a subscribe/notify pair, not a
// context — `AuthProvider` is the thing that turns this into React state.
const REFRESH_TOKEN_STORAGE_KEY = 'aner.refreshToken';

// Refresh this many ms before actual expiry, so a request that starts just
// under the wire doesn't race the token's own deadline.
const EXPIRY_SAFETY_MARGIN_MS = 60_000;

interface TokenState {
  accessToken: string | null;
  accessTokenExpiresAt: number | null;
}

let state: TokenState = { accessToken: null, accessTokenExpiresAt: null };

type Listener = () => void;
const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function subscribeToTokenState(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAccessToken(): string | null {
  return state.accessToken;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
}

export function isAccessTokenExpiringSoon(): boolean {
  if (state.accessToken === null || state.accessTokenExpiresAt === null) {
    return true;
  }
  return Date.now() >= state.accessTokenExpiresAt - EXPIRY_SAFETY_MARGIN_MS;
}

export function setTokens(params: {
  accessToken: string;
  refreshToken: string;
  expiresInSeconds: number;
}): void {
  state = {
    accessToken: params.accessToken,
    accessTokenExpiresAt: Date.now() + params.expiresInSeconds * 1000,
  };
  localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, params.refreshToken);
  notify();
}

export function clearTokens(): void {
  state = { accessToken: null, accessTokenExpiresAt: null };
  localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  notify();
}
