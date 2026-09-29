import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearTokens, setTokens } from '@/lib/api/tokenStorage';

import { recordBackgroundCheckDecision } from './background-check';

const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

// The real path — `recordBackgroundCheckDecision` through `apiRequest` — with only
// `fetch` replaced. The panel's tests mock this function, which is how a body encoded
// twice (a JSON string where the server wants an object, so every move got a 422)
// went unnoticed.
describe('recordBackgroundCheckDecision', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    setTokens({ accessToken: 'access', refreshToken: 'refresh', expiresInSeconds: 900 });
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: 'decision' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    clearTokens();
  });

  it('sends the decision as a JSON object carrying to_value', async () => {
    await recordBackgroundCheckDecision(COMPANY_ID, {
      to_value: 'CLEAR',
      reason: 'All eight items passed',
      risk_rating: 'LOW',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/v1/onboarding/exporters/${COMPANY_ID}/background-check/decisions`);
    expect(init.method).toBe('POST');
    const sent: unknown = JSON.parse(init.body as string);
    expect(typeof sent).toBe('object');
    expect(sent).toEqual({ to_value: 'CLEAR', reason: 'All eight items passed', risk_rating: 'LOW' });
  });
});
