/**
 * `useCanRevealIdentifiersOnce`: one answer per form, taken once the server has given
 * one.
 *
 * Two faults it sits between. Read live, the permission can flip from false to true
 * while an edit form is open, after the fields were initialised empty — the save then
 * clears a real email. Frozen on the first answer, a form opened before the
 * permissions land freezes `false` and masks the fields from somebody entitled to
 * read them for as long as it stays open.
 *
 * Driven through the real query rather than a stubbed hook, because `usePermissions`
 * is private to the module and the loading phase is the thing under test.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiRequest } from '@/lib/api/client';

import { useCanRevealIdentifiersOnce } from './usePermissions';

vi.mock('@/lib/api/client', () => ({ apiRequest: vi.fn() }));

const REVEAL = { module: 'exporters', action: 'view_full_tax_id' };

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Holds the request out until `settle` is called, so the loading phase is observable. */
function deferred(permissions: readonly object[]) {
  let settle = () => {};
  const promise = new Promise((resolve) => {
    settle = () => resolve({ role_name: 'Compliance', permissions });
  });
  vi.mocked(apiRequest).mockReturnValue(promise as ReturnType<typeof apiRequest>);
  return { settle };
}

describe('useCanRevealIdentifiersOnce', () => {
  beforeEach(() => vi.clearAllMocks());

  it('masks while the answer is still unknown', () => {
    deferred([REVEAL]);

    const { result } = renderHook(() => useCanRevealIdentifiersOnce(), { wrapper });

    // Nothing is frozen yet, and the default until told otherwise is masked.
    expect(result.current).toBe(false);
  });

  it('answers on the first render when the permissions are already loaded', () => {
    // The usual case: the company page loaded them long before any edit form opened.
    // Settled a render late, every form opened `false` and switched to `true`, with its
    // email and phone initialised empty — and the save cleared them.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(['settings', 'myPermissions'], {
      role_name: 'Compliance',
      permissions: [REVEAL],
    });
    const seen: boolean[] = [];

    renderHook(() => seen.push(useCanRevealIdentifiersOnce()), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });

    expect(seen[0]).toBe(true);
    expect(seen).not.toContain(false);
  });

  it('reveals once a late answer says it may', async () => {
    // The fault this hook exists for: the form opened before the permissions landed,
    // and froze the "no" it was given before the server had spoken.
    const { settle } = deferred([REVEAL]);
    const { result } = renderHook(() => useCanRevealIdentifiersOnce(), { wrapper });
    expect(result.current).toBe(false);

    settle();

    await waitFor(() => expect(result.current).toBe(true));
  });

  it('answers a viewer without the permission with a settled no', async () => {
    const { settle } = deferred([]);
    const { result } = renderHook(() => useCanRevealIdentifiersOnce(), { wrapper });

    settle();

    await waitFor(() => expect(vi.mocked(apiRequest)).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });

  it('keeps the answer it settled on when the permission changes afterwards', async () => {
    const { settle } = deferred([REVEAL]);
    const { result, rerender } = renderHook(() => useCanRevealIdentifiersOnce(), {
      wrapper,
    });
    settle();
    await waitFor(() => expect(result.current).toBe(true));

    // The grant is revoked while the form is open. The fields were initialised from
    // the real email, so flipping now would blank them and save that as a clear.
    vi.mocked(apiRequest).mockResolvedValue({
      role_name: 'Compliance',
      permissions: [],
    } as never);
    rerender();

    await waitFor(() => expect(result.current).toBe(true));
  });
});
