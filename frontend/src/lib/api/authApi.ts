import { parseErrorResponse } from './errors';
import type { LoginRequest, TokenResponse, User } from './types';

// Deliberately not built on `client.ts`'s authenticated `apiRequest` — login
// and refresh happen *before* a valid access token exists (refresh in
// particular is what `apiRequest` itself calls when a token expires, so
// routing it back through `apiRequest` would recurse), and `me`/`logout`
// here take an explicit token argument rather than reading the ambient one,
// so `AuthProvider`'s own boot-time silent-refresh sequence stays a plain,
// readable chain of calls instead of depending on module load order.
const API_BASE = '/api/v1/auth';

async function postJson<TBody, TResult>(
  path: string,
  body: TBody,
  accessToken?: string,
): Promise<TResult> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await parseErrorResponse(response);
  if (response.status === 204) return undefined as TResult;
  return (await response.json()) as TResult;
}

export function login(credentials: LoginRequest): Promise<TokenResponse> {
  return postJson('/login', credentials);
}

export function refresh(refreshToken: string): Promise<TokenResponse> {
  return postJson('/refresh', { refresh_token: refreshToken });
}

export async function logout(
  accessToken: string,
  refreshToken: string,
): Promise<void> {
  await postJson('/logout', { refresh_token: refreshToken }, accessToken);
}

export async function fetchCurrentUser(accessToken: string): Promise<User> {
  const response = await fetch(`${API_BASE}/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw await parseErrorResponse(response);
  return (await response.json()) as User;
}
