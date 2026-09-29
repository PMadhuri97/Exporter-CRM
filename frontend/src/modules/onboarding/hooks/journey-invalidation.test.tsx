import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { recordBackgroundCheckDecision, recordQualificationOutcome } from '../api';
import type { BackgroundCheckDecision, Qualification } from '../types';

import { useRecordBackgroundCheckDecision } from './background-check';
import { useRecordQualificationOutcome } from './qualification';

vi.mock('../api', () => ({
  recordBackgroundCheckDecision: vi.fn(),
  recordQualificationOutcome: vi.fn(),
}));

const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function setUp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const invalidated = () => invalidate.mock.calls.map(([filters]) => filters?.queryKey);
  return { wrapper, invalidated };
}

// Either move can make the company a CUSTOMER on the server in the same request
// (architecture §5). Without these, the header, journey chip, lists and the deals'
// handover state kept the old journey until the page was reloaded.
const JOURNEY_KEYS = [
  ['exporterProfile', COMPANY_ID],
  ['exporterProfiles'],
  ['companyHistory', COMPANY_ID],
  ['deals', COMPANY_ID],
  ['deal'],
];

beforeEach(() => vi.clearAllMocks());

describe('after a background-check decision', () => {
  it('invalidates the company, the lists and the deals as well as the check', async () => {
    vi.mocked(recordBackgroundCheckDecision).mockResolvedValue({} as BackgroundCheckDecision);
    const { wrapper, invalidated } = setUp();
    const { result } = renderHook(() => useRecordBackgroundCheckDecision(COMPANY_ID), {
      wrapper,
    });

    await act(() => result.current.mutateAsync({ to_value: 'CLEAR', reason: 'ok', risk_rating: 'LOW' }));

    expect(invalidated()).toEqual(
      expect.arrayContaining([['backgroundCheck', COMPANY_ID], ...JOURNEY_KEYS]),
    );
  });
});

describe('after a qualification outcome', () => {
  it('invalidates the company, the lists and the deals', async () => {
    vi.mocked(recordQualificationOutcome).mockResolvedValue({} as Qualification);
    const { wrapper, invalidated } = setUp();
    const { result } = renderHook(() => useRecordQualificationOutcome(COMPANY_ID), { wrapper });

    await act(() => result.current.mutateAsync({ outcome: 'QUALIFIED', reason_codes: [] }));

    expect(invalidated()).toEqual(expect.arrayContaining(JOURNEY_KEYS));
  });
});
